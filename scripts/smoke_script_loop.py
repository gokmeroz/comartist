"""Live Story Architect -> Script Writer <-> Critic run on the chapter template, spend capped.

Run from the repo root:

    uv run python scripts/smoke_script_loop.py             # cap $4.00

Saves `smoke_results/<UTC timestamp>-script-loop/`: `brief.yaml`, `summary.json` (every draft,
critique, cost, and prompt version) and `script.md` (the best draft and its verdict).
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import ModelError, build_text_model
from comartist.agents.critic import Critic
from comartist.agents.script_writer import ScriptWriter
from comartist.agents.story_architect import StoryArchitect, StoryArchitectError
from comartist.config import PROVIDERS, MetaSettings
from comartist.workflows.script_loop import ScriptLoop, ScriptLoopError
from comartist.workflows.store import chapter_template, parse_brief

RESULTS_DIR = Path("smoke_results")
MAX_DRAFTS = 3
# (calls, max output tokens): architect and each draft and critique may need one repair.
CALLS = [(2, 8000), (2 * MAX_DRAFTS, 12000), (2 * MAX_DRAFTS, 4000)]


def worst_case_usd() -> float:
    price = MetaSettings().prices["muse-wonder-1.0"]
    total = 0.0
    for calls, output in CALLS:
        total += calls * (30000 * price.input_per_m_tokens + output * price.output_per_m_tokens) / 1e6
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brief", type=Path, help="YAML brief (default: the chapter template)")
    parser.add_argument("--cap-usd", type=float, default=4.0)
    args = parser.parse_args()

    if not PROVIDERS["meta"].key_present():
        print("COMARTIST_META_API_KEY is not set in the environment or .env", file=sys.stderr)
        return 2
    worst = worst_case_usd()
    if worst > args.cap_usd:
        print(f"Worst case ${worst:.2f} exceeds --cap-usd {args.cap_usd:g}; nothing sent.", file=sys.stderr)
        return 2
    brief_text = args.brief.read_text() if args.brief else chapter_template()
    spec = parse_brief(brief_text)

    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-script-loop"
    out.mkdir(parents=True)
    (out / "brief.yaml").write_text(brief_text)
    model = build_text_model("meta", "Muse Wonder")
    try:
        planned = StoryArchitect(model).plan(spec)
        result = ScriptLoop(ScriptWriter(model), Critic(model), MAX_DRAFTS).run(spec, planned.outline)
    except (StoryArchitectError, ScriptLoopError, ModelError) as error:
        (out / "summary.json").write_text(json.dumps({"ok": False, "error": str(error)}, indent=2))
        print(f"FAILED: {error} -> {out}")
        return 1

    summary = {"ok": True, "outline": planned.outline.model_dump(), **result.model_dump(mode="json")}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [f"# {spec.title}", "", f"Approved: {result.approved} ({result.stop_reason})", ""]
    for panel in result.script.panels:
        lines.append(f"**{panel.panel_id}** {panel.action}")
        lines += [f"- {line.speaker}: {line.text}" for line in panel.dialogue]
        lines.append("")
    lines += ["## Critique per draft"]
    for number, draft in enumerate(result.drafts, 1):
        lines.append(f"- Draft {number}: approved={draft.critique.approved} score={draft.critique.score}")
        lines += [f"  - [{i.category}] {i.panel_id}: {i.evidence}" for i in draft.critique.issues]
    (out / "script.md").write_text("\n".join(lines) + "\n")
    spent = planned.cost.add(result.cost)
    print(f"approved={result.approved} ({result.stop_reason}) after {result.attempts} draft(s)")
    print(f"spent ${spent.usd or 0:.4f} (cap ${args.cap_usd:g}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
