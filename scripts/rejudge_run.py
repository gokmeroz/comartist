"""Re-run only the Chapter Judge on a run's current pages. Costs one Judge call (~$0.25).

    uv run python scripts/rejudge_run.py chapter-1-the-journey-begins

Nothing is redrawn or re-lettered, and nothing is accepted. On failure the run is marked failed.
"""

import sys
from pathlib import Path

from comartist.adapters import ModelError, build_text_model
from comartist.agents.chapter_judge import ChapterJudge, ChapterJudgeError
from comartist.models import RunState, Stage, StageState
from comartist.workflows.store import RunStore


def main(chapter_id: str) -> int:
    store = RunStore(Path("runs"))
    run = store.load(chapter_id)
    if run.state is RunState.RUNNING or run.accepted or not run.pages:
        raise SystemExit(f"Refusing: state={run.state}, accepted={run.accepted}, pages={len(run.pages)}")
    status = run.stages[Stage.CHAPTER_JUDGE]
    settings = run.settings
    try:
        judged = ChapterJudge(build_text_model(settings.provider, settings.text_model)).judge(
            run.spec, run.script, run.pages
        )
    except (ModelError, ChapterJudgeError) as error:
        run.state, run.error = RunState.FAILED, f"Chapter Judge failed: {error}"
        status.state, status.detail = StageState.FAILED, "no verdict"
        run.log.append(f"{Stage.CHAPTER_JUDGE}: FAILED - {error}")
        store.save(run)
        print(run.error)
        return 1
    verdict = judged.verdict
    run.verdict = verdict
    status.state, status.attempts, status.cost = StageState.DONE, 1, status.cost.add(judged.cost)
    status.detail = f"{'approved' if verdict.approved else 'not approved'}, score {verdict.score:.2f}"
    run.state, run.error = RunState.DONE, ""
    run.log.append(f"{Stage.CHAPTER_JUDGE}: {status.detail}")
    store.save(run)
    print(f"{status.detail}\n{verdict.summary}")
    for issue in verdict.issues:
        print(f"- {issue.category} page {issue.page}: {issue.evidence}")
    print(f"total chapter cost: ${run.cost.usd:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
