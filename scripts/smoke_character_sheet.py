"""Live character sheets from the latest Visual Director smoke result, one image per look.

    uv run python scripts/smoke_character_sheet.py     # about $0.01 per character

Saves into `smoke_results/<UTC timestamp>-character-sheets/`.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import build_image_model
from comartist.models import ChapterRun, ChapterSpec, VisualPlan
from comartist.tools.character_sheets import generate_sheet
from comartist.workflows.store import RunStore

RESULTS_DIR = Path("smoke_results")


def main() -> None:
    source = sorted(RESULTS_DIR.glob("*-visual-director"))[-1]
    plan = VisualPlan.model_validate(json.loads((source / "summary.json").read_text())["plan"])
    store = RunStore(RESULTS_DIR)
    name = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-character-sheets"
    (RESULTS_DIR / name).mkdir()
    run = ChapterRun(chapter_id=name, spec=ChapterSpec(title="Sheets", premise="-", characters=["-"]))
    model = build_image_model("meta", "Muse Image")
    for look in plan.looks:
        print(generate_sheet(model, store, run, look, plan.style))
    print(f"spent ${run.reference_cost.usd or 0:.4f}")


if __name__ == "__main__":
    main()
