"""Deterministic in-memory models for tests and the offline stub provider."""

import base64
from collections.abc import Callable

from comartist.adapters.base import (
    ImageRequest,
    ImageResult,
    ModelError,
    TextRequest,
    TextResult,
)
from comartist.models.run import Cost

# 1x1 transparent PNG.
BLANK_PNG_B64 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
).decode()


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeTextModel:
    """Replies with queued responses (str or ModelError to raise), else echoes the last message."""

    def __init__(
        self,
        responses: list[str | ModelError] | None = None,
        provider: str = "fake",
        model: str = "fake-text",
        reply: Callable[[TextRequest], str] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._responses = list(responses or [])
        self._reply = reply
        self.requests: list[TextRequest] = []

    def complete(self, request: TextRequest) -> TextResult:
        self.requests.append(request)
        if self._responses:
            next_response = self._responses.pop(0)
            if isinstance(next_response, ModelError):
                raise next_response
            text = next_response
        elif self._reply:
            text = self._reply(request)
        else:
            text = f"(fake reply to: {request.messages[-1].content[:60]})"
        prompt = sum(_tokens(m.content) for m in request.messages)
        return TextResult(
            text=text,
            provider=self.provider,
            model=self.model,
            cost=Cost(prompt_tokens=prompt, completion_tokens=_tokens(text), usd=0.0),
        )


class FakeImageModel:
    """Returns a blank PNG, or raises queued errors first."""

    def __init__(
        self,
        errors: list[ModelError] | None = None,
        provider: str = "fake",
        model: str = "fake-image",
    ) -> None:
        self.provider = provider
        self.model = model
        self._errors = list(errors or [])
        self.requests: list[ImageRequest] = []

    def generate(self, request: ImageRequest) -> ImageResult:
        self.requests.append(request)
        if self._errors:
            raise self._errors.pop(0)
        return ImageResult(
            image_b64=BLANK_PNG_B64,
            provider=self.provider,
            model=self.model,
            cost=Cost(images=1, usd=0.0),
        )
