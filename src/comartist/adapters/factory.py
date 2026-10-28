"""Build text and image models from the sidebar's provider choice and env settings.

Every hosted model is wrapped in a fallback chain so it gets same-provider retries. When
the Fireworks key is set, Fireworks is appended as the fallback for both text and images.
"""

import time
from collections.abc import Callable

from comartist.adapters.base import ImageModel, ModelError, ModelErrorKind, TextModel
from comartist.adapters.fake import FakeImageModel, FakeTextModel
from comartist.adapters.fallback import FallbackImage, FallbackText
from comartist.adapters.openai_compatible import (
    ChatCompletionsText,
    FluxWorkflowImage,
    ImagesEndpointImage,
    ResponsesImage,
    ResponsesText,
    Transport,
)
from comartist.config import EndpointSettings, FireworksSettings, MetaSettings

FALLBACK_PROVIDER = "fireworks"
TEXT_CLASSES = {"responses": ResponsesText, "chat_completions": ChatCompletionsText}
IMAGE_CLASSES = {
    "responses": ResponsesImage,
    "images": ImagesEndpointImage,
    "flux_workflow": FluxWorkflowImage,
}


def _endpoints() -> dict[str, EndpointSettings]:
    return {"meta": MetaSettings(), FALLBACK_PROVIDER: FireworksSettings()}


def _client(cls: type, provider: str, endpoint: EndpointSettings, model: str, transport: Transport | None):
    if endpoint.api_key is None:
        raise ModelError(ModelErrorKind.CONFIG, "API key is not set", provider)
    return cls(
        provider,
        model,
        endpoint.base_url,
        endpoint.api_key,
        transport=transport,
        timeout_s=endpoint.timeout_s,
        price=endpoint.prices.get(model),
    )


def _chain(
    kind: str,
    provider: str,
    label: str,
    endpoints: dict[str, EndpointSettings] | None,
    transport: Transport | None,
) -> list:
    endpoints = endpoints or _endpoints()
    if provider not in endpoints:
        raise ModelError(ModelErrorKind.CONFIG, "Provider not implemented", provider)

    def build(name: str, endpoint: EndpointSettings, model_label: str):
        ids = endpoint.text_model_ids if kind == "text" else endpoint.image_model_ids
        if model_label not in ids:
            raise ModelError(ModelErrorKind.CONFIG, f"Unknown model {model_label!r}", name)
        style = endpoint.api_style if kind == "text" else endpoint.image_style
        cls = (TEXT_CLASSES if kind == "text" else IMAGE_CLASSES)[style]
        return _client(cls, name, endpoint, ids[model_label], transport)

    chain = [build(provider, endpoints[provider], label)]
    backup = endpoints.get(FALLBACK_PROVIDER)
    if provider != FALLBACK_PROVIDER and backup and backup.api_key:
        ids = backup.text_model_ids if kind == "text" else backup.image_model_ids
        if ids:
            chain.append(build(FALLBACK_PROVIDER, backup, next(iter(ids))))
    return chain


def build_text_model(
    provider: str,
    label: str,
    endpoints: dict[str, EndpointSettings] | None = None,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TextModel:
    if provider == "stub":
        return FakeTextModel(provider="stub", model=label)
    return FallbackText(_chain("text", provider, label, endpoints, transport), sleep=sleep)


def build_image_model(
    provider: str,
    label: str,
    endpoints: dict[str, EndpointSettings] | None = None,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ImageModel:
    if provider == "stub":
        return FakeImageModel(provider="stub", model=label)
    return FallbackImage(_chain("image", provider, label, endpoints, transport), sleep=sleep)
