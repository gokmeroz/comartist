"""Model access behind provider-neutral interfaces."""

from comartist.adapters.base import (
    ChatMessage,
    ImageModel,
    ImageReference,
    ImageRequest,
    ImageResult,
    ModelError,
    ModelErrorKind,
    TextModel,
    TextRequest,
    TextResult,
)
from comartist.adapters.factory import build_image_model, build_text_model

__all__ = [
    "ChatMessage",
    "ImageModel",
    "ImageReference",
    "ImageRequest",
    "ImageResult",
    "ModelError",
    "ModelErrorKind",
    "TextModel",
    "TextRequest",
    "TextResult",
    "build_image_model",
    "build_text_model",
]
