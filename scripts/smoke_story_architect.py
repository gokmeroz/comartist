"""Live Story Architect run on the chapter template, with a hard spend cap.

Run from the repo root:

    uv run python scripts/smoke_story_architect.py             # cap $0.50
    uv run python scripts/smoke_story_architect.py --brief path/to/brief.yaml

Saves `smoke_results/<UTC timestamp>-story-architect/`: `brief.yaml`, `summary.json`
(outline, attempts, rejected problems, cost, prompt version) and `outline.md`.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import ModelError, build_text_model
from comartist.agents.story_architect import DEFAULT_MAX_ATTEMPTS, StoryArchitect, StoryArchitectError
from comartist.config import PROVIDERS, MetaSettings
from comartist.workflows.store import chapter_template, parse_brief

RESULTS_DIR = Path("smoke_results")
MAX_OUTPUT_TOKENS = 8000  # matches StoryArchitect's request


def worst_case_usd(prompt_chars: int) -> float:
    price = MetaSettings().prices["muse-wonder-1.0"]
    # Each repair resends the conversation, so input grows; 4x the brief is a safe bound.
    per_attempt = (4 * prompt_chars / 4 + 3000) * price.input_per_m_tokens / 1e6
    per_attempt += MAX_OUTPUT_TOKENS * price.output_per_m_tokens / 1e6
    return DEFAULT_MAX_ATTEMPTS * per_attempt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brief", type=Path, help="YAML brief (default: the chapter template)")
    parser.add_argument("--cap-usd", type=float, default=0.5)
    args = parser.parse_args()

    if not PROVIDERS["meta"].key_present():
        print("COMARTIST_META_API_KEY is not set in the environment or .env", file=sys.stderr)
        return 2
    brief_text = args.brief.read_text() if args.brief else chapter_template()
    spec = parse_brief(brief_text)
    worst = worst_case_usd(len(brief_text))
    if worst > args.cap_usd:
        print(f"Worst case ${worst:.2f} exceeds --cap-usd {args.cap_usd:g}; nothing sent.", file=sys.stderr)
        return 2

    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-story-architect"
    out.mkdir(parents=True)
    (out / "brief.yaml").write_text(brief_text)
    architect = StoryArchitect(build_text_model("meta", "Muse Wonder"))
    try:
        result = architect.plan(spec)
    except StoryArchitectError as error:
        summary = {"ok": False, "error": str(error), "rejected": error.rejected, "cost": error.cost.model_dump()}
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(f"FAILED: {error}\nspent ${error.cost.usd or 0:.4f} -> {out}")
        return 1
    except ModelError as error:
        (out / "summary.json").write_text(json.dumps({"ok": False, "error": str(error)}, indent=2))
        print(f"FAILED: {error} -> {out}")
        return 1

    (out / "summary.json").write_text(json.dumps({"ok": True, **result.model_dump()}, indent=2))
    lines = [f"# {spec.title}", "", f"*{result.outline.logline}*", ""]
    for beat in result.outline.beats:
        lines += [
            f"## Page {beat.page} - {', '.join(beat.characters)} @ {beat.location}",
            beat.summary,
            f"- Emotion: {beat.emotion}",
            f"- Turn: {beat.turn}",
            "",
        ]
    if result.outline.proposed_facts:
        lines += ["## Proposed facts (not canon)", *[f"- {fact}" for fact in result.outline.proposed_facts]]
    (out / "outline.md").write_text("\n".join(lines) + "\n")
    print(f"ok: {len(result.outline.beats)} beats in {result.attempts} attempt(s) - {result.outline.logline}")
    print(f"spent ${result.cost.usd or 0:.4f} (cap ${args.cap_usd:g}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
