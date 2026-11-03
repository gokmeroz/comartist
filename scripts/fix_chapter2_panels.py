"""One-off repair of chapter-2-welcome-to-2016-2: its 5 rejected panels and the Judge issues (p1 placeholder, p3 outfit flips). Costs real credits.

Fixes, in one pass: p5-4 (helmets/void instead of pub), p6-2 (crowded bubbles), p10 (missing
"caught" beat, via p10-4), p12-3 and p12-4 (portal drifts). Redraws those panels in parallel,
locates heads only on the redrawn panels, then re-letters and re-judges once. Backs up the run
first. Nothing is accepted here.

    uv run python scripts/fix_chapter2_panels.py
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

CHAPTER = "chapter-2-welcome-to-2016-2"
OUTFIT = "The Alien always wears his wide-brimmed hat, the beige trench coat with collar up, dark sunglasses and white gloves on both four-fingered hands. G. Maert O'zd wears the white t-shirt, jeans and red sneakers with his sunglasses pushed up on his head. Leave the top of the panel empty for speech bubbles."

# panel_id -> (shot updates, script updates, note for the image prompt)
FIXES = {
    "p1-2": (
        {"poses": "An Alien from Saturn stumbles forward out of the glowing portal onto the cobblestones, arms out for "
                  "balance, while G. Maert O'zd stands beside it looking surprised"},
        {"action": "An Alien from Saturn stumbles out of the glowing portal onto the cobblestone street while "
                    "G. Maert O'zd, already through, watches in surprise."},
        "A friendly, comedic arrival on a sunny Istanbul street. " + OUTFIT,
    ),
    "p2-2": ({}, {}, "Tall vertical over-the-shoulder close shot on the blinking scanner between them. " + OUTFIT),
    "p2-4": ({}, {}, "Close-up on the Alien's gloved hand covering the blinking scanner, G. Maert O'zd's face beside it. " + OUTFIT),
    "p3-2": ({}, {}, "The Dark Lord appears only as a soft red glow at the frame edge. " + OUTFIT),
    "p3-3": ({}, {}, "The red hologram of The Dark Lord leans forward, arms crossed, calm and stern; both heroes look up at it. " + OUTFIT),
}


def main() -> None:
    root = Path("runs")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copytree(root / CHAPTER, Path("smoke_results") / f"{stamp}-ch2-panel-fix-backup")
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
