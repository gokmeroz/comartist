"""Live Visual Director run on the latest saved script-loop smoke result, spend capped.

Run from the repo root, after `smoke_script_loop.py`:

    uv run python scripts/smoke_visual_director.py             # cap $1.00

Saves `smoke_results/<UTC timestamp>-visual-director/summary.json` and `plan.md`.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import ModelError, build_text_model
from comartist.agents.visual_director import VisualDirector, VisualDirectorError
from comartist.config import PROVIDERS, MetaSettings
from comartist.models import Script
from comartist.workflows.store import parse_brief

RESULTS_DIR = Path("smoke_results")


def worst_case_usd() -> float:
    price = MetaSettings().prices["muse-wonder-1.0"]
    return 2 * (30000 * price.input_per_m_tokens + 12000 * price.output_per_m_tokens) / 1e6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cap-usd", type=float, default=1.0)
    args = parser.parse_args()

    if not PROVIDERS["meta"].key_present():
        print("COMARTIST_META_API_KEY is not set in the environment or .env", file=sys.stderr)
        return 2
    worst = worst_case_usd()
    if worst > args.cap_usd:
        print(f"Worst case ${worst:.2f} exceeds --cap-usd {args.cap_usd:g}; nothing sent.", file=sys.stderr)
        return 2
    source = sorted(RESULTS_DIR.glob("*-script-loop"))[-1]
    spec = parse_brief((source / "brief.yaml").read_text())
    script = Script.model_validate(json.loads((source / "summary.json").read_text())["script"])

    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-visual-director"
    out.mkdir(parents=True)
    try:
        result = VisualDirector(build_text_model("meta", "Muse Wonder")).plan(spec, script)
    except (VisualDirectorError, ModelError) as error:
        (out / "summary.json").write_text(json.dumps({"ok": False, "error": str(error)}, indent=2))
        print(f"FAILED: {error} -> {out}")
        return 1

    (out / "summary.json").write_text(json.dumps({"ok": True, **result.model_dump()}, indent=2))
    lines = [f"# {spec.title}", "", f"Style: {result.plan.style}", ""]
    lines += [f"- {look.name}: {look.appearance} Outfit: {look.outfit}" for look in result.plan.looks]
    for panel in result.plan.panels:
        lines += ["", f"**{panel.panel_id}** {panel.framing}. {panel.composition}", f"- {panel.poses}", f"- {panel.lighting}; {panel.setting}"]
    (out / "plan.md").write_text("\n".join(lines) + "\n")
    print(f"ok: {len(result.plan.panels)} specs in {result.attempts} attempt(s)")
    print(f"spent ${result.cost.usd or 0:.4f} (cap ${args.cap_usd:g}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
