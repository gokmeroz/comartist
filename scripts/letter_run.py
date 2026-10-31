"""Re-letter a finished run from its saved panels.

    uv run python scripts/letter_run.py chapter-1-the-reunion           # free
    uv run python scripts/letter_run.py chapter-1-the-reunion --locate  # first find heads
"""

import sys
from pathlib import Path

from comartist.adapters import build_text_model
from comartist.agents.critic import Critic
from comartist.models import Cost, Stage
from comartist.tools.lettering import letter_chapter
from comartist.workflows.panel_loop import data_url
from comartist.workflows.store import RunStore

store = RunStore(Path("runs"))
run = store.load(sys.argv[1])
if "--locate" in sys.argv:
    critic = Critic(build_text_model("meta", "Muse Wonder"))
    shots = {shot.panel_id: shot for shot in run.visual_plan.panels}
    spent = 0.0
    for panel in run.panels:
        panel.heads, cost = critic.locate_heads(data_url(panel.best_image), shots[panel.panel_id].characters)
        spent += cost.usd or 0
    run.stages[Stage.LAYOUT].cost = run.stages[Stage.LAYOUT].cost.add(Cost(usd=spent))
    print(f"located heads for ${spent:.4f}")
run.pages, run.pdf = letter_chapter(run, store.root / run.chapter_id / "pages")
store.save(run)
print(run.pages, run.pdf)
