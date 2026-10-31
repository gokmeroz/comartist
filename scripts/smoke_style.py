"""Live test of the comic style: new plan and sheets from a run's script, then one page.

    uv run python scripts/smoke_style.py chapter-1-the-reunion --page 1   # about $1.20

Saves `smoke_results/<UTC timestamp>-style/`.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import build_image_model, build_text_model
from comartist.agents.critic import Critic
from comartist.agents.visual_director import VisualDirector, attach_references
from comartist.models import ChapterRun, PanelResult
from comartist.tools.character_sheets import approve_sheet, generate_sheet
from comartist.tools.lettering import letter_chapter
from comartist.workflows.panel_loop import PanelLoop
from comartist.workflows.store import RunStore

parser = argparse.ArgumentParser()
parser.add_argument("chapter")
parser.add_argument("--page", type=int, default=1)
args = parser.parse_args()

source = RunStore(Path("runs")).load(args.chapter)
root = Path("smoke_results")
name = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-style"
out = root / name
out.mkdir()
store = RunStore(root)
spec = source.spec.model_copy(update={"references": {}, "locked_looks": []})
run = ChapterRun(chapter_id=name, spec=spec, script=source.script)
text, images = build_text_model("meta", "Muse Wonder"), build_image_model("meta", "Muse Image")
director = VisualDirector(text)
planned = director.plan(spec, source.script)
spent = planned.cost.usd or 0
for look in planned.plan.looks:
    generate_sheet(images, store, run, look, planned.plan.style)
    approve_sheet(store, run, look)
run.visual_plan = attach_references(planned.plan, run.spec)
print("layouts", [(l.page, l.template) for l in run.visual_plan.layouts])
loop = PanelLoop(images, Critic(text), director)
actions = {panel.panel_id: panel for panel in source.script.panels}
for shot in run.visual_plan.panels:
    panel = actions[shot.panel_id]
    if panel.page != args.page:
        continue
    result = loop.run(run.spec, run.visual_plan, shot, panel.action, out, 1.5)
    spent += result.cost.usd or 0
    print(shot.panel_id, shot.size, result.stop_reason, [a.score for a in result.attempts], result.error)
    run.panels.append(
        PanelResult(panel_id=shot.panel_id, page=panel.page, index=panel.index, description=panel.action, attempts=result.attempts)
    )
spent += (loop.locate_heads(run).usd or 0) + (run.reference_cost.usd or 0)
run.pages, run.pdf = letter_chapter(run, out / "pages")
store.save(run)
print(f"spent ${spent:.2f} -> {run.pages}")
