"""Try providers in order, moving on only for failures another provider might not share.

Rate limits and transient errors are retried on the same provider first, with exponential
backoff, because they usually clear within seconds.
"""

import time
from collections.abc import Callable
from typing import TypeVar

from comartist.adapters.base import (
    FALLBACK_KINDS,
    ImageModel,
    ImageRequest,
    ImageResult,
    ModelError,
    ModelErrorKind,
    TextModel,
    TextRequest,
    TextResult,
)

RETRY_KINDS = {ModelErrorKind.RATE_LIMIT, ModelErrorKind.TRANSIENT}

Model = TypeVar("Model")
Result = TypeVar("Result")


class _Chain:
    def __init__(
        self,
        models: list,
        retries: int = 2,
        backoff_s: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not models:
            raise ValueError("A fallback chain needs at least one model")
        self._models = models
        self._retries = retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self.provider = models[0].provider
        self.model = models[0].model
        self.errors: list[ModelError] = []  # failures from the most recent call

    def _run(self, call: Callable[[Model], Result]) -> Result:
        self.errors = []
        for candidate in self._models:
            for attempt in range(self._retries + 1):
                try:
                    return call(candidate)
                except ModelError as error:
                    self.errors.append(error)
                    if error.kind not in FALLBACK_KINDS:
                        raise
                    if error.kind not in RETRY_KINDS or attempt == self._retries:
                        break
                    self._sleep(self._backoff_s * 2**attempt)
        summary = "; ".join(str(e) for e in self.errors)
        raise ModelError(self.errors[-1].kind, f"All providers failed: {summary}", "fallback")


class FallbackText(_Chain):
    def __init__(self, models: list[TextModel], **kwargs) -> None:
        super().__init__(models, **kwargs)

    def complete(self, request: TextRequest) -> TextResult:
        return self._run(lambda model: model.complete(request))


class FallbackImage(_Chain):
    def __init__(self, models: list[ImageModel], **kwargs) -> None:
        super().__init__(models, **kwargs)

    def generate(self, request: ImageRequest) -> ImageResult:
        return self._run(lambda model: model.generate(request))
