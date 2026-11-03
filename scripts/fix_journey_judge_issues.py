"""One-off repair of chapter-1-the-journey-begins for the Chapter Judge's 0.55 verdict. Costs real credits.

Fixes, in one pass: p5-4 (helmets/void instead of pub), p6-2 (crowded bubbles), p10 (missing
"caught" beat, via p10-4), p12-3 and p12-4 (portal drifts). Redraws those panels in parallel,
locates heads only on the redrawn panels, then re-letters and re-judges once. Backs up the run
first. Nothing is accepted here.

    uv run python scripts/fix_journey_judge_issues.py
"""

import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import ModelError, build_image_model, build_text_model
from comartist.agents.chapter_judge import ChapterJudge
from comartist.agents.critic import Critic
from comartist.agents.visual_director import VisualDirector
from comartist.models import Cost, RunState, Stage, StageState
from comartist.tools.lettering import letter_chapter
from comartist.workflows.panel_loop import PanelLoop, data_url
from comartist.workflows.store import RunStore

CHAPTER = "chapter-1-the-journey-begins"
PORTAL = "the same blue circular swirling portal as the rest of the chamber, ringed by circular machinery"

# panel_id -> (shot updates, script updates, note for the image prompt)
FIXES = {
    "p5-4": (
        {
            "setting": "The same cozy galaxy pub: wooden table, mugs, starfield windows, silhouetted patrons",
            "composition": "G. Maert O'zd at left and the Alien at right laugh across the pub table, both "
            "helmets resting on the table between the mugs, starfield window behind them, with clear "
            "negative space above for dialogue and no text in the image",
        },
        {},
        "Inside the pub, not a plain background. Both characters are bare-headed; their space helmets "
        "sit on the table beside the mugs.",
    ),
    "p6-2": (
        {},
        {},
        "Frame the characters low in the panel, heads in the lower half, leaving the whole top third "
        "as empty dark pub wall for two speech bubbles.",
    ),
    "p10-4": (
        {
            "composition": "An Alien from Saturn drags G. Maert O'zd out from behind the toppled crates by "
            "the arm, smiling falsely, while The Dark Lord's hologram looms large at right, turned toward "
            "him, with clear negative space above for dialogue and no text in the image",
        },
        {
            "action": "Caught: An Alien from Saturn hauls G. Maert O'zd out from behind the crates by the "
            "arm with a friendly smile while The Dark Lord's hologram turns toward him.",
            "caption": "Spotted.",
        },
        "Show the moment he is caught: crates knocked aside, the Alien pulling him out into the open.",
    ),
    "p12-3": ({"setting": f"Portal chamber with {PORTAL}"}, {}, f"The portal is {PORTAL}. Not orange."),
    "p12-4": ({"setting": f"Portal chamber threshold with {PORTAL}"}, {}, f"The portal is {PORTAL}, not a rectangular gate."),
}


def main() -> None:
    root = Path("runs")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copytree(root / CHAPTER, Path("smoke_results") / f"{stamp}-journey-judge-fix-backup")
    store = RunStore(root)
    run = store.load(CHAPTER)
    if run.state is RunState.RUNNING or run.accepted:
        raise SystemExit(f"Refusing: run is {run.state}, accepted={run.accepted}")

    shots = {shot.panel_id: shot for shot in run.visual_plan.panels}
    for panel_id, (shot_update, script_update, _) in FIXES.items():
        run.visual_plan.panels = [
            shot.model_copy(update=shot_update) if shot.panel_id == panel_id else shot
            for shot in run.visual_plan.panels
        ]
        if script_update:
            for scene in run.script.scenes:
                for panel in scene.panels:
                    if panel.panel_id == panel_id:
                        for key, value in script_update.items():
                            setattr(panel, key, value)
            result_panel = next(item for item in run.panels if item.panel_id == panel_id)
            result_panel.description = script_update.get("action", result_panel.description)
            result_panel.caption = script_update.get("caption", result_panel.caption)
    shots = {shot.panel_id: shot for shot in run.visual_plan.panels}
    actions = {panel.panel_id: panel.action for panel in run.script.panels}
    run.state = RunState.RUNNING
    run.log.append(f"Judge-issue repair started for {', '.join(FIXES)}")
    store.save(run)

    settings = run.settings
    text = build_text_model(settings.provider, settings.text_model)
    critic = Critic(text)
    loop = PanelLoop(
        build_image_model(settings.provider, settings.image_model), critic, VisualDirector(text),
        settings.max_panel_attempts,
    )
    folder = root / CHAPTER / "panels"

    def redraw(panel_id: str):
        return panel_id, loop.run(
            run.spec, run.visual_plan, shots[panel_id], actions[panel_id], folder,
            settings.chapter_budget_usd, [FIXES[panel_id][2]],
        )

    with ThreadPoolExecutor(max_workers=len(FIXES)) as pool:
        results = list(pool.map(redraw, FIXES))

    status = run.stages[Stage.PANELS]
    changed = []
    for panel_id, result in results:
        panel = next(item for item in run.panels if item.panel_id == panel_id)
        status.attempts += len(result.attempts)
        status.cost = status.cost.add(result.cost)
        if result.accepted:
            panel.attempts = result.attempts
            changed.append(panel)
        run.log.append(f"{Stage.PANELS}: {panel_id} redrawn ({result.stop_reason}) error: {result.error or 'none'}")
        print(panel_id, result.stop_reason, [(a.failure, a.score) for a in result.attempts], result.error)
    store.save(run)

    layout = run.stages[Stage.LAYOUT]
    for panel in changed:
        visible = {name.casefold() for name in shots[panel.panel_id].characters}
        looks = [look for look in run.visual_plan.looks if look.name.casefold() in visible]
        try:
            panel.heads, spent = critic.locate_heads(data_url(panel.best_image), looks)
        except ModelError:
            panel.heads, spent = {}, Cost()
        layout.cost = layout.cost.add(spent)
    run.pages, run.pdf = letter_chapter(run, root / CHAPTER / "pages")
    run.log.append(f"{Stage.LAYOUT}: {len(run.pages)} pages re-lettered")
    store.save(run)

    judge = run.stages[Stage.CHAPTER_JUDGE]
    try:
        judged = ChapterJudge(text).judge(run.spec, run.script, run.pages)
    except Exception as error:
        run.state, run.error = RunState.FAILED, f"Chapter Judge failed after re-lettering: {error}"
        judge.state, judge.detail = StageState.FAILED, "no verdict"
        run.log.append(f"{Stage.CHAPTER_JUDGE}: FAILED - {error}")
        store.save(run)
        raise
    run.verdict = judged.verdict
    judge.state, judge.cost = StageState.DONE, judge.cost.add(judged.cost)
    judge.detail = f"{'approved' if judged.verdict.approved else 'not approved'}, score {judged.verdict.score:.2f}"
    run.log.append(f"{Stage.CHAPTER_JUDGE}: {judge.detail}")
    run.state, run.error = RunState.DONE, ""
    store.save(run)

    print("accepted panels:", sum(item.accepted for item in run.panels), "/", len(run.panels))
    print("verdict:", judged.verdict.approved, judged.verdict.score, judged.verdict.summary)
    for issue in judged.verdict.issues:
        print("-", issue.category, issue.page, issue.evidence)
    print(f"total chapter cost: ${run.cost.usd:.3f}")


if __name__ == "__main__":
    main()
