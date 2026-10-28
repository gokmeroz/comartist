"""Live smoke test of the hosted model adapters (Meta, Fireworks), with a hard spend cap.

Run from the repo root (so `.env` is found):

    uv run python scripts/smoke_meta.py                 # text + image, cap $0.05
    uv run python scripts/smoke_meta.py --only text --cap-usd 0.01
    uv run python scripts/smoke_meta.py --probe         # also save raw response shapes
    uv run python scripts/smoke_meta.py --provider fireworks   # check the fallback provider

Results go to `smoke_results/<UTC timestamp>-<provider>/`: `summary.json`, any generated
images, and with `--probe` the raw response bodies with long base64 blobs truncated.
API keys are never written.
"""

import argparse
import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from comartist.adapters import (
    ChatMessage,
    ImageRequest,
    ModelError,
    TextRequest,
    build_image_model,
    build_text_model,
)
from comartist.adapters.openai_compatible import UrllibTransport
from comartist.config import PROVIDERS, FireworksSettings, MetaSettings

RESULTS_DIR = Path("smoke_results")
SETTINGS = {"meta": MetaSettings, "fireworks": FireworksSettings}
TEXT_PROMPT = "Reply with exactly: ComArtist ready"
IMAGE_PROMPT = "Single comic panel, clean ink lines: a fox reading a comic book, golden hour"
# Worst-case estimates used to enforce the cap before spending.
TEXT_WORST_USD = 0.01  # 1,000 output tokens at $20/M, plus a short prompt
IMAGE_WORST_USD = 0.01


class RecordingTransport(UrllibTransport):
    """Keeps each raw response body so `--probe` can save its shape."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def post_json(self, url, payload, headers, timeout_s):
        status, body = super().post_json(url, payload, headers, timeout_s)
        self.bodies.append({"url": url, "status": status, "body": _truncate(body)})
        return status, body


def _truncate(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    if isinstance(value, str) and len(value) > 200:
        return f"{value[:60]}...<{len(value)} chars>"
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=list(SETTINGS), default="meta")
    parser.add_argument("--only", choices=["text", "image"])
    parser.add_argument("--cap-usd", type=float, default=0.05)
    parser.add_argument("--probe", action="store_true", help="save raw response shapes")
    args = parser.parse_args()

    option = PROVIDERS[args.provider]
    if not option.key_present():
        print(f"{option.api_key_env} is not set in the environment or .env", file=sys.stderr)
        return 2
    settings = SETTINGS[args.provider]()
    text_label, image_label = next(iter(settings.text_model_ids)), next(iter(settings.image_model_ids))
    checks = [args.only] if args.only else ["text", "image"]
    worst = sum(TEXT_WORST_USD if c == "text" else IMAGE_WORST_USD for c in checks)
    if worst > args.cap_usd:
        print(f"Worst case ${worst:.2f} exceeds --cap-usd {args.cap_usd:g}; nothing sent.", file=sys.stderr)
        return 2

    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{args.provider}"
    out.mkdir(parents=True)
    transport = RecordingTransport()
    summary: dict[str, Any] = {
        "provider": args.provider,
        "base_url": settings.base_url,
        "cap_usd": args.cap_usd,
        "checks": {},
    }
    spent = 0.0

    if "text" in checks:
        try:
            result = build_text_model(args.provider, text_label, transport=transport).complete(
                TextRequest(messages=[ChatMessage(role="user", content=TEXT_PROMPT)], max_tokens=1000)
            )
            spent += result.cost.usd or 0.0
            summary["checks"]["text"] = {"ok": True, "prompt": TEXT_PROMPT, **result.model_dump()}
        except ModelError as error:
            summary["checks"]["text"] = {"ok": False, "error": str(error), "kind": error.kind}

    if "image" in checks:
        try:
            result = build_image_model(args.provider, image_label, transport=transport).generate(
                ImageRequest(prompt=IMAGE_PROMPT)
            )
            spent += result.cost.usd or 0.0
            record = result.model_dump(exclude={"image_b64"})
            if result.image_b64:
                image_path = out / f"image.{result.mime_type.split('/')[-1]}"
                image_path.write_bytes(base64.b64decode(result.image_b64))
                record["saved_to"] = str(image_path)
            summary["checks"]["image"] = {"ok": True, "prompt": IMAGE_PROMPT, **record}
        except ModelError as error:
            summary["checks"]["image"] = {"ok": False, "error": str(error), "kind": error.kind}

    summary["spent_usd"] = round(spent, 6)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    if args.probe:
        (out / "raw_responses.json").write_text(json.dumps(transport.bodies, indent=2))

    for name, check in summary["checks"].items():
        detail = check.get("text") or check.get("saved_to") or check.get("error")
        print(f"{name}: {'ok' if check['ok'] else 'FAILED'} - {str(detail)[:100]}")
    print(f"spent ${spent:.4f} (cap ${args.cap_usd:g}) -> {out}")
    return 0 if all(c["ok"] for c in summary["checks"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
