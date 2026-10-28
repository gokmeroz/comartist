"""Provider-neutral request/result types and interfaces for text and image models."""

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from comartist.models.run import Cost


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class TextRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1)  # includes hidden reasoning tokens
    json_mode: bool = False


class TextResult(BaseModel):
    text: str
    provider: str
    model: str
    cost: Cost = Field(default_factory=Cost)
    latency_s: float = 0.0


class ImageReference(BaseModel):
    """An approved reference image: a public URL or a `data:image/...;base64,` URL."""

    image_url: str = Field(min_length=1)
    caption: str = ""  # sent just before the image, e.g. "Matt's approved character sheet:"


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    references: list[ImageReference] = Field(default_factory=list)
    size: str = "1024x1024"  # chat_completions-style endpoints only
    seed: int | None = None  # chat_completions-style endpoints only


class ImageResult(BaseModel):
    """Exactly one of `image_b64` or `url` is set."""

    image_b64: str | None = None
    url: str | None = None
    mime_type: str = "image/png"
    ignored_references: int = 0  # references the backend could not use (e.g. FLUX fallback)
    provider: str
    model: str
    cost: Cost = Field(default_factory=Cost)
    latency_s: float = 0.0


class ModelErrorKind(StrEnum):
    CONFIG = "config"  # missing key, unknown provider
    AUTH = "auth"
    QUOTA = "quota"  # out of credits / payment required
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"  # timeouts, 5xx, connection errors
    BAD_REQUEST = "bad_request"
    BAD_RESPONSE = "bad_response"  # provider answered but the payload is unusable


# Failures another provider might not share, so a fallback is worth trying.
FALLBACK_KINDS = {
    ModelErrorKind.CONFIG,
    ModelErrorKind.AUTH,
    ModelErrorKind.QUOTA,
    ModelErrorKind.RATE_LIMIT,
    ModelErrorKind.TRANSIENT,
}


class ModelError(Exception):
    def __init__(self, kind: ModelErrorKind, message: str, provider: str = "") -> None:
        super().__init__(f"[{provider or '?'}:{kind}] {message}")
        self.kind = kind
        self.provider = provider


class TextModel(Protocol):
    provider: str
    model: str

    def complete(self, request: TextRequest) -> TextResult: ...


class ImageModel(Protocol):
    provider: str
    model: str

    def generate(self, request: ImageRequest) -> ImageResult: ...
