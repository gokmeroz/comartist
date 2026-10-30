"""Live Story Architect -> Script Writer run on the chapter template, with a hard spend cap.

Run from the repo root:

    uv run python scripts/smoke_script_writer.py             # cap $1.25
    uv run python scripts/smoke_script_writer.py --brief path/to/brief.yaml

Saves `smoke_results/<UTC timestamp>-script-writer/`: `brief.yaml`, `summary.json`
(outline, script, attempts, rejected problems, cost, prompt versions) and `script.md`.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import ModelError, build_text_model
from comartist.agents import script_writer, story_architect
from comartist.agents.script_writer import ScriptWriter, ScriptWriterError
from comartist.agents.story_architect import StoryArchitect, StoryArchitectError
from comartist.config import PROVIDERS, MetaSettings
from comartist.workflows.store import chapter_template, parse_brief

RESULTS_DIR = Path("smoke_results")
MAX_OUTPUT_TOKENS = (8000, 12000)  # matches the agents' requests


def worst_case_usd(prompt_chars: int) -> float:
    price = MetaSettings().prices["muse-wonder-1.0"]
    attempts = story_architect.DEFAULT_MAX_ATTEMPTS, script_writer.DEFAULT_MAX_ATTEMPTS
    total = 0.0
    for tries, output in zip(attempts, MAX_OUTPUT_TOKENS):
        # Each repair resends the draft, so input is bounded by brief + prompt + output.
        input_tokens = prompt_chars + 3000 + output
        total += tries * input_tokens * price.input_per_m_tokens / 1e6
        total += tries * output * price.output_per_m_tokens / 1e6
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brief", type=Path, help="YAML brief (default: the chapter template)")
    parser.add_argument("--cap-usd", type=float, default=1.25)
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

    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-script-writer"
    out.mkdir(parents=True)
    (out / "brief.yaml").write_text(brief_text)
    model = build_text_model("meta", "Muse Wonder")
    try:
        planned = StoryArchitect(model).plan(spec)
        written = ScriptWriter(model).write(spec, planned.outline)
    except (StoryArchitectError, ScriptWriterError, ModelError) as error:
        rejected = getattr(error, "rejected", [])
        (out / "summary.json").write_text(json.dumps({"ok": False, "error": str(error), "rejected": rejected}, indent=2))
        print(f"FAILED: {error} -> {out}")
        return 1

    summary = {"ok": True, "story_architect": planned.model_dump(), "script_writer": written.model_dump()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [f"# {spec.title}", ""]
    for scene in written.script.scenes:
        lines += [f"## {scene.location}", scene.summary, ""]
        for panel in scene.panels:
            lines.append(f"**{panel.panel_id}** {panel.action}")
            if panel.caption:
                lines.append(f"- Caption: {panel.caption}")
            lines += [f"- {line.speaker}: {line.text}" for line in panel.dialogue]
            lines.append("")
    if written.script.proposed_facts:
        lines += ["## Proposed facts (not canon)", *[f"- {fact}" for fact in written.script.proposed_facts]]
    (out / "script.md").write_text("\n".join(lines) + "\n")
    spent = planned.cost.add(written.cost)
    print(f"ok: {len(written.script.panels)} panels in {written.attempts} attempt(s)")
    print(f"spent ${spent.usd or 0:.4f} (cap ${args.cap_usd:g}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
