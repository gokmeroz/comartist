"""Live panel loop on the latest saved script, plan, and character sheets, spend capped.

    uv run python scripts/smoke_panels.py --panels 4     # cap $1.00

Saves panels and `summary.json` into `smoke_results/<UTC timestamp>-panels/`.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import build_image_model, build_text_model
from comartist.agents.critic import Critic
from comartist.agents.visual_director import VisualDirector
from comartist.models import Script, VisualPlan
from comartist.workflows.panel_loop import PanelLoop
from comartist.workflows.store import parse_brief

RESULTS_DIR = Path("smoke_results")


def latest(pattern: str) -> Path:
    return sorted(RESULTS_DIR.glob(pattern))[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--panels", type=int, default=4)
    parser.add_argument("--cap-usd", type=float, default=1.0)
    args = parser.parse_args()

    source = latest("*-script-loop")
    spec = parse_brief((source / "brief.yaml").read_text())
    script = Script.model_validate(json.loads((source / "summary.json").read_text())["script"])
    plan = VisualPlan.model_validate(json.loads((latest("*-visual-director") / "summary.json").read_text())["plan"])
    sheets = latest("*-character-sheets") / "references"
    spec.references = {look.name: str(sheets / f"{look.name.lower()}.png") for look in plan.looks}
    spec.locked_looks = plan.looks

    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-panels"
    out.mkdir(parents=True)
    text = build_text_model("meta", "Muse Wonder")
    loop = PanelLoop(build_image_model("meta", "Muse Image"), Critic(text), VisualDirector(text))
    actions = {panel.panel_id: panel.action for panel in script.panels}
    spent, rows = 0.0, []
    for shot in plan.panels[: args.panels]:
        shot = shot.model_copy(update={"references": shot.characters})
        result = loop.run(spec, plan, shot, actions[shot.panel_id], out, args.cap_usd - spent)
        spent += result.cost.usd or 0
        rows.append(result.model_dump(mode="json"))
        scores = [attempt.score for attempt in result.attempts]
        print(shot.panel_id, result.stop_reason, scores, [a.failure for a in result.attempts], result.error)
        (out / "summary.json").write_text(json.dumps(rows, indent=2))
        if spent >= args.cap_usd:
            print("cap reached")
            break
    print(f"spent ${spent:.4f} (cap ${args.cap_usd:g}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
