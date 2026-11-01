"""One-off repair of chapter-1-the-journey-begins. Costs real credits (~$3-4).

Removes the secret from p10-2's caption and action, redraws p6-3 and p10-2, then re-letters
and re-judges once. Backs up the run to smoke_results/ first. Nothing is accepted here.

    uv run python scripts/fix_journey_page10.py
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import build_image_model, build_text_model
from comartist.agents.chapter_judge import ChapterJudge
from comartist.agents.critic import Critic
from comartist.agents.visual_director import VisualDirector
from comartist.models import RunState, Stage
from comartist.workflows.panel_loop import PanelLoop
from comartist.workflows.store import RunStore
from comartist.workflows.stub_pipeline import regenerate_panel

CHAPTER = "chapter-1-the-journey-begins"
ACTION = (
    "A small glowing chart with no words, numbers, or logos sits beside The Dark Lord's hologram "
    "while An Alien from Saturn faces him."
)
P6_3_NOTE = "The alien has exactly four fingers on each hand. Keep the top of the panel uncluttered."
P10_2_NOTE = "The chart is abstract glowing lines only, with no words, numbers, or logos."


def main() -> None:
    root = Path("runs")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copytree(root / CHAPTER, Path("smoke_results") / f"{stamp}-journey-backup")

    store = RunStore(root)
    run = store.load(CHAPTER)
    if run.state is RunState.RUNNING:
        raise SystemExit("Run is active; stop it first.")
    if run.accepted:
        raise SystemExit("Run is accepted; refusing to change it.")
    for scene in run.script.scenes:
        scene.summary = scene.summary.replace(", whose real Bitcoin motive stays unspoken to them", "")
        for panel in scene.panels:
            if panel.panel_id == "p10-2":
                panel.action, panel.caption = ACTION, ""
    target = next(panel for panel in run.panels if panel.panel_id == "p10-2")
    target.description, target.caption = ACTION, ""
    store.save(run)

    settings = run.settings
    text = build_text_model(settings.provider, settings.text_model)
    loop = PanelLoop(
        build_image_model(settings.provider, settings.image_model),
        Critic(text), VisualDirector(text), settings.max_panel_attempts,
    )

    shot = next(item for item in run.visual_plan.panels if item.panel_id == "p6-3")
    action = next(item.action for item in run.script.panels if item.panel_id == "p6-3")
    result = loop.run(
        run.spec, run.visual_plan, shot, action, root / CHAPTER / "panels",
        settings.chapter_budget_usd, [P6_3_NOTE],
    )
    panel = next(item for item in run.panels if item.panel_id == "p6-3")
    status = run.stages[Stage.PANELS]
    status.attempts += len(result.attempts)
    status.cost = status.cost.add(result.cost)
    if result.accepted:
        panel.attempts = result.attempts
    run.log.append(f"{Stage.PANELS}: p6-3 redrawn ({result.stop_reason}), error: {result.error or 'none'}")
    store.save(run)
    print("p6-3 accepted:", result.accepted, result.stop_reason, result.error)

    final = regenerate_panel(store, CHAPTER, settings, loop, ChapterJudge(text), "p10-2", P10_2_NOTE)
    print("\n".join(final.log[-6:]))
    print("state:", final.state, "error:", final.error)
    print("accepted panels:", sum(item.accepted for item in final.panels), "/", len(final.panels))
    if final.verdict:
        print("score:", final.verdict.score, "approved:", final.verdict.approved)
        print(final.verdict.summary)
        for issue in final.verdict.issues:
            print("-", issue.category, issue.page, issue.evidence)


if __name__ == "__main__":
    main()
