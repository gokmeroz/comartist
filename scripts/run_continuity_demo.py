"""Run the two-chapter continuity demo end to end on Meta, then check it. Costs real credits (~$5).

    uv run python scripts/run_continuity_demo.py [chapter-1 run id]

Re-runs chapter 1 if it has no approved verdict, accepts it (committing no proposed facts),
creates chapter 2 from evals/continuity/chapter-2.yaml with carry-over, runs and accepts it,
then runs scripts/check_continuity.py. A chapter the Judge rejects is left unaccepted.
"""

import subprocess
import sys
from pathlib import Path

from comartist.adapters import build_image_model, build_text_model
from comartist.agents.chapter_judge import ChapterJudge
from comartist.agents.critic import Critic
from comartist.agents.script_writer import ScriptWriter
from comartist.agents.story_architect import StoryArchitect
from comartist.agents.visual_director import VisualDirector
from comartist.config import Settings
from comartist.memory.continuity import carry_over
from comartist.models import ChapterRun, RunSettings
from comartist.tools.canon import CanonStore, accept_chapter, blockers
from comartist.workflows.panel_loop import PanelLoop
from comartist.workflows.script_loop import ScriptLoop
from comartist.workflows.store import RunStore
from comartist.workflows.stub_pipeline import run_guarded, run_stub_pipeline

SETTINGS = RunSettings(provider="meta", text_model="Muse Wonder", image_model="Muse Image")
CHAPTER_2 = Path(__file__).resolve().parent.parent / "evals" / "continuity" / "chapter-2.yaml"


def run_chapter(store: RunStore, chapter_id: str) -> ChapterRun:
    text = build_text_model(SETTINGS.provider, SETTINGS.text_model)
    director = VisualDirector(text)
    run_guarded(
        run_stub_pipeline, store, chapter_id, SETTINGS,
        step_seconds=0,
        story_architect=StoryArchitect(text),
        script_loop=ScriptLoop(ScriptWriter(text), Critic(text), SETTINGS.max_script_attempts),
        visual_director=director,
        panel_loop=PanelLoop(
            build_image_model(SETTINGS.provider, SETTINGS.image_model), Critic(text), director,
            SETTINGS.max_panel_attempts,
        ),
        chapter_judge=ChapterJudge(text),
    )
    run = store.load(chapter_id)
    print("\n".join(run.log[-4:]))
    return run


def accept(store: RunStore, canon: CanonStore, run: ChapterRun) -> bool:
    if problems := blockers(run):
        print(f"{run.chapter_id} not accepted: {'; '.join(problems)}")
        return False
    accept_chapter(canon, run, [])
    store.save(run)
    print(f"{run.chapter_id} accepted.")
    return True


def main(first_id: str = "chapter-1-the-reunion") -> int:
    settings = Settings()
    store, canon = RunStore(settings.runs_dir), CanonStore(settings.canon_path)
    first = store.load(first_id)
    if not first.accepted:
        if not (first.verdict and first.verdict.approved):
            first = run_chapter(store, first_id)
        if not accept(store, canon, first):
            return 1
    carry = carry_over(store.list(), canon.facts())
    second = store.create(CHAPTER_2.read_text(), carry)
    print(f"Created {second.chapter_id}: {second.log[0]}")
    second = run_chapter(store, second.chapter_id)
    accept(store, canon, second)
    return subprocess.call([sys.executable, "scripts/check_continuity.py", first_id, second.chapter_id])


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
