"""Probe: does Meta drop long-running /v1/responses calls? Times one long non-streaming request."""

import time

from comartist.adapters.base import TextRequest
from comartist.adapters.factory import build_text_model

model = build_text_model("meta", "Muse Wonder")
model._retries = 0  # one attempt, so the timing is for a single connection
prompt = "Write a 6000-word short story about five friends on a road trip. Return JSON {\"story\": \"...\"}."
start = time.monotonic()
try:
    result = model.complete(
        TextRequest(messages=[{"role": "user", "content": prompt}], max_tokens=24000, json_mode=True)
    )
    print(f"OK after {time.monotonic() - start:.1f}s, cost={result.cost}")
except Exception as error:  # report the failure and how long the connection lived
    print(f"FAILED after {time.monotonic() - start:.1f}s: {error}")
