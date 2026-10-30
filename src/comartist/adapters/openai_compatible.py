"""HTTP adapters for OpenAI-style endpoints.

Wire formats: the Responses API (`/responses`, used by the Meta Model API for both text
and images), Chat Completions (`/chat/completions`, Fireworks text), `/images/generations`,
and Fireworks' FLUX workflow endpoint (images only). The network call goes through a `Transport` so tests never touch the network.
"""

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

from pydantic import SecretStr

from comartist.adapters.base import (
    ImageRequest,
    ImageResult,
    ModelError,
    ModelErrorKind,
    TextRequest,
    TextResult,
)
from comartist.config import ModelPrice
from comartist.models.run import Cost


class Transport(Protocol):
    def post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> tuple[int, dict[str, Any]]: ...


class UrllibTransport:
    """Standard-library HTTP; returns (status, parsed JSON body)."""

    def post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read()
                if content_type.startswith("image/"):
                    # Some image endpoints answer with the bytes; normalise to the JSON shape.
                    return response.status, {
                        "data": [{"b64_json": base64.b64encode(raw).decode()}],
                        "output_format": content_type.split("/", 1)[1].split(";")[0],
                    }
                return response.status, _parse(raw)
        except urllib.error.HTTPError as error:
            return error.code, _parse(error.read())


def _parse(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return {"error": {"message": raw[:200].decode(errors="replace")}}
    return body if isinstance(body, dict) else {"data": body}


def _error_kind(status: int) -> ModelErrorKind:
    if status in (401, 403):
        return ModelErrorKind.AUTH
    if status == 402:
        return ModelErrorKind.QUOTA
    if status == 429:
        return ModelErrorKind.RATE_LIMIT
    if status >= 500:
        return ModelErrorKind.TRANSIENT
    return ModelErrorKind.BAD_REQUEST


def _token_cost(usage: dict[str, Any], price: ModelPrice | None, images: int = 0) -> Cost:
    """Responses API reports input/output_tokens; Chat Completions reports prompt/completion_tokens."""
    prompt = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    completion = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    usd: float | None = None
    if price is not None:
        if images and price.per_image is not None:
            usd = images * price.per_image
        elif not images and None not in (price.input_per_m_tokens, price.output_per_m_tokens):
            usd = (prompt * price.input_per_m_tokens + completion * price.output_per_m_tokens) / 1e6
    return Cost(prompt_tokens=prompt, completion_tokens=completion, images=images, usd=usd)


class _Client:
    def __init__(
        self,
        provider: str,
        model: str,
        base_url: str,
        api_key: SecretStr,
        transport: Transport | None = None,
        timeout_s: float = 120.0,
        price: ModelPrice | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport or UrllibTransport()
        self._timeout_s = timeout_s
        self._price = price

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        try:
            status, body = self._transport.post_json(
                f"{self._base_url}{path}", payload, headers, self._timeout_s
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ModelError(ModelErrorKind.TRANSIENT, str(error), self.provider) from error
        if status >= 400:
            message = str((body.get("error") or {}).get("message", body))[:300]
            kind = _error_kind(status)
            if kind is ModelErrorKind.RATE_LIMIT and "quota" in message.lower():
                kind = ModelErrorKind.QUOTA
            raise ModelError(kind, f"HTTP {status}: {message}", self.provider)
        return body, time.monotonic() - started

    def _bad(self, message: str) -> ModelError:
        return ModelError(ModelErrorKind.BAD_RESPONSE, message, self.provider)


def _input_images(request: TextRequest, message: ChatMessage) -> list[dict[str, Any]]:
    if message is not request.messages[-1]:
        return []
    return [{"type": "input_image", "image_url": url} for url in request.images]


def _chat_message(request: TextRequest, message: ChatMessage) -> dict[str, Any]:
    if message is not request.messages[-1] or not request.images:
        return message.model_dump()
    images = [{"type": "image_url", "image_url": {"url": url}} for url in request.images]
    return {"role": message.role, "content": [{"type": "text", "text": message.content}, *images]}


class ResponsesText(_Client):
    def complete(self, request: TextRequest) -> TextResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": m.role, "content": [{"type": "input_text", "text": m.content}, *_input_images(request, m)]}
                if m.role == "user"
                else {"role": m.role, "content": m.content}
                for m in request.messages
            ],
            "temperature": request.temperature,
            "max_output_tokens": request.max_tokens,
            "stream": False,
        }
        if request.json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        body, latency = self._post("/responses", payload)
        text = body.get("output_text") or "".join(
            part.get("text", "")
            for item in body.get("output") or []
            if isinstance(item, dict) and item.get("type") == "message"
            for part in item.get("content") or []
            if isinstance(part, dict) and part.get("type") == "output_text"
        )
        if not text.strip():
            reason = (body.get("incomplete_details") or {}).get("reason")
            if reason == "max_output_tokens":
                # Reasoning models can spend the whole budget thinking before answering.
                raise self._bad(f"Ran out of tokens before answering (max_tokens={request.max_tokens})")
            raise self._bad("No output_text in response")
        return TextResult(
            text=text,
            provider=self.provider,
            model=self.model,
            cost=_token_cost(body.get("usage") or {}, self._price),
            latency_s=latency,
        )


def _find_image(body: dict[str, Any]) -> tuple[str | None, str | None]:
    """(base64, url) from either the images-endpoint shape or a Responses `output` array."""
    for item in body.get("data") or []:
        if isinstance(item, dict) and (item.get("b64_json") or item.get("url")):
            return item.get("b64_json"), item.get("url")
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image_generation_call" and item.get("result"):
            return item["result"], None
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("b64_json") or part.get("image_base64"):
                return part.get("b64_json") or part.get("image_base64"), None
            url = part.get("image_url") or part.get("url")
            if isinstance(url, dict):
                url = url.get("url")
            if isinstance(url, str) and url:
                if url.startswith("data:") and ";base64," in url:
                    return url.split(";base64,", 1)[1], None
                return None, url
    return None, None


def _mime(body: dict[str, Any]) -> str:
    return f"image/{body.get('output_format') or 'png'}"


class ResponsesImage(_Client):
    def generate(self, request: ImageRequest) -> ImageResult:
        prompt: str | list[dict[str, Any]] = request.prompt
        if request.references:
            content: list[dict[str, Any]] = []
            for ref in request.references:
                if ref.caption:
                    content.append({"type": "input_text", "text": ref.caption})
                content.append({"type": "input_image", "image_url": ref.image_url})
            content.append({"type": "input_text", "text": request.prompt})
            prompt = [{"role": "user", "content": content}]
        body, latency = self._post("/responses", {"model": self.model, "input": prompt})
        image_b64, url = _find_image(body)
        if not image_b64 and not url:
            raise self._bad(f"No image in response (keys: {sorted(body)})")
        return ImageResult(
            image_b64=image_b64,
            url=None if image_b64 else url,
            mime_type=_mime(body),
            provider=self.provider,
            model=self.model,
            cost=_token_cost(body.get("usage") or {}, self._price, images=1),
            latency_s=latency,
        )


class ChatCompletionsText(_Client):
    def complete(self, request: TextRequest) -> TextResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_chat_message(request, m) for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body, latency = self._post("/chat/completions", payload)
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise self._bad("No choices[0].message.content") from error
        if not isinstance(text, str) or not text.strip():
            raise self._bad("Empty completion")
        return TextResult(
            text=text,
            provider=self.provider,
            model=self.model,
            cost=_token_cost(body.get("usage") or {}, self._price),
            latency_s=latency,
        )


class FluxWorkflowImage(_Client):
    """Fireworks FLUX text-to-image. It takes no reference images; they are dropped and counted."""

    def generate(self, request: ImageRequest) -> ImageResult:
        payload: dict[str, Any] = {"prompt": request.prompt, "aspect_ratio": "1:1"}
        if request.seed is not None:
            payload["seed"] = request.seed
        body, latency = self._post(f"/workflows/{self.model}/text_to_image", payload)
        image_b64, url = _find_image(body)
        image_b64 = image_b64 or body.get("base64") or None
        if not image_b64 and not url:
            raise self._bad(f"No image in response (keys: {sorted(body)})")
        return ImageResult(
            image_b64=image_b64,
            url=None if image_b64 else url,
            mime_type=_mime(body),
            ignored_references=len(request.references),
            provider=self.provider,
            model=self.model,
            cost=_token_cost({}, self._price, images=1),
            latency_s=latency,
        )


class ImagesEndpointImage(_Client):
    """`/images/generations`; reference images are not supported on this path."""

    def generate(self, request: ImageRequest) -> ImageResult:
        if request.references:
            raise ModelError(
                ModelErrorKind.BAD_REQUEST, "Reference images need the Responses API", self.provider
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": request.prompt,
            "size": request.size,
            "n": 1,
            "response_format": "b64_json",
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        body, latency = self._post("/images/generations", payload)
        image_b64, url = _find_image(body)
        if not image_b64 and not url:
            raise self._bad("Image has no b64_json or url")
        return ImageResult(
            image_b64=image_b64,
            url=None if image_b64 else url,
            mime_type=_mime(body),
            provider=self.provider,
            model=self.model,
            cost=_token_cost(body.get("usage") or {}, self._price, images=1),
            latency_s=latency,
        )
