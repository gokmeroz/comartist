"""Retry a run from the Visual Director, keeping its approved script. Costs real credits.

    uv run python scripts/resume_from_visual_director.py chapter-2-welcome-to-2016-2 [tries]

For runs whose script is approved but whose Visual Director call failed (e.g. the Meta API
dropped the connection). Retries the Visual Director up to `tries` times, a minute apart, then
continues panels -> lettering -> Chapter Judge exactly as the app does. Nothing is accepted.
"""

import sys
import time
from pathlib import Path

from comartist.adapters import ModelError, build_image_model, build_text_model
from comartist.agents.chapter_judge import ChapterJudge
from comartist.agents.critic import Critic
from comartist.agents.visual_director import VisualDirector, VisualDirectorError
from comartist.models import RunState, Stage, StageState
from comartist.workflows.panel_loop import PanelLoop
from comartist.workflows.store import RunStore
from comartist.workflows.stub_pipeline import _finish_real


def main(chapter_id: str, tries: int = 10) -> int:
    store = RunStore(Path("runs"))
    run = store.load(chapter_id)
    if run.state is RunState.RUNNING or run.accepted:
        raise SystemExit(f"Refusing: state={run.state}, accepted={run.accepted}")
    if run.script is None or not run.panels or run.stages[Stage.SCRIPT].state is not StageState.DONE:
        raise SystemExit("Refusing: this run has no approved script to keep.")
    settings = run.settings
    text = build_text_model(settings.provider, settings.text_model)
    director = VisualDirector(text)
    status = run.stages[Stage.VISUAL_DIRECTOR]
    run.state, run.error = RunState.RUNNING, ""
    status.state, status.detail = StageState.RUNNING, ""
    run.log.append(f"{Stage.VISUAL_DIRECTOR}: retrying, keeping the approved script")
    store.save(run)

    for attempt in range(1, tries + 1):
        print(f"visual director try {attempt} at {time.strftime('%H:%M:%S')}", flush=True)
        try:
            directed = director.plan(run.spec, run.script)
            break
        except (VisualDirectorError, ModelError) as error:
            if isinstance(error, VisualDirectorError):
                status.cost = status.cost.add(error.cost)
            run.log.append(f"{Stage.VISUAL_DIRECTOR}: try {attempt} FAILED - {error}")
            store.save(run)
            print(f"  failed: {error}", flush=True)
            if attempt < tries:
                time.sleep(60)
    else:
        status.state, status.detail = StageState.FAILED, "no valid visual plan"
        run.state, run.error = RunState.FAILED, f"Visual Director failed {tries} times; script is kept."
        store.save(run)
        return 1

    run.visual_plan = directed.plan
    run.prompt_versions[Stage.VISUAL_DIRECTOR] = directed.prompt_version
    status.state, status.attempts = StageState.DONE, directed.attempts
    status.cost = status.cost.add(directed.cost)
    status.detail = f"{len(directed.plan.panels)} panel specs ({directed.provider})"
    run.log.append(f"{Stage.VISUAL_DIRECTOR}: {status.detail}")
    store.save(run)
    print(f"visual director ok: {status.detail}", flush=True)

    loop = PanelLoop(
        build_image_model(settings.provider, settings.image_model), Critic(text), director,
        settings.max_panel_attempts,
    )
    final = _finish_real(store, run, settings, loop, ChapterJudge(text))
    print(f"state: {final.state} {final.error}", flush=True)
    print(*final.log[-4:], sep="\n")
    if final.verdict:
        print("verdict:", final.verdict.approved, final.verdict.score)
    print(f"total cost: ${final.cost.usd or 0:.2f}")
    return 0 if final.state is RunState.DONE else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], *(int(arg) for arg in sys.argv[2:3])))
