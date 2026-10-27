"""Offline stand-in for the chapter workflow so the UI runs end to end.

Each stage reports believable progress, attempt counts, and token usage, but no model is
called and the cost is $0. The real LangGraph workflow will replace this behind the same
`ChapterRun` status updates.
"""

import time
from collections.abc import Callable

from comartist.models import (
    ChapterRun,
    ChapterSpec,
    Cost,
    PanelAttempt,
    PanelResult,
    RunSettings,
    RunState,
    Stage,
    StageState,
)
from comartist.workflows.store import RunStore

PANELS_PER_PAGE = 4
SHOTS = ["Wide establishing shot", "Medium two-shot", "Close-up", "Over-the-shoulder shot"]
STUB_FAILURES = [
    ("WRONG_OUTFIT", "Jacket colour differs from the reference sheet."),
    ("POSE_MISMATCH", "Script asks for a wave; the figure is standing still."),
    ("MISSING_CHARACTER", "Only one of the two characters is visible."),
    ("STYLE_DRIFT", "Line weight drifts from the chapter style."),
]


def _tokens(text: str) -> int:
    """Rough 4-characters-per-token estimate."""
    return max(1, len(text) // 4)


def _stub_panel_attempts(panel_index: int, max_attempts: int) -> int:
    """Deterministic: every fifth panel needs one retry, every eleventh needs two."""
    needed = 1 + (panel_index % 5 == 2) + (panel_index % 11 == 7)
    return min(needed, max_attempts)


def _stub_panels(spec: ChapterSpec) -> list[PanelResult]:
    panels = []
    for number in range(spec.target_pages * PANELS_PER_PAGE):
        page, index = divmod(number, PANELS_PER_PAGE)
        speaker = spec.characters[number % len(spec.characters)]
        place = spec.location or "the scene"
        panels.append(
            PanelResult(
                panel_id=f"p{page + 1}-{index + 1}",
                page=page + 1,
                index=index + 1,
                description=f"{SHOTS[index]} of {', '.join(spec.characters)} in {place}.",
                caption=f"{spec.timeframe}, {place}." if index == 0 else "",
                dialogue=f"{speaker}: (stub line {number + 1})" if index else "",
            )
        )
    return panels


def _stub_attempts(panel_index: int, max_attempts: int) -> list[PanelAttempt]:
    needed = _stub_panel_attempts(panel_index, max_attempts=99)
    attempts = []
    for number in range(1, min(needed, max_attempts) + 1):
        if number == needed:
            attempts.append(PanelAttempt(attempt=number, accepted=True, note="Matches script and references."))
        else:
            failure, note = STUB_FAILURES[(panel_index + number) % len(STUB_FAILURES)]
            attempts.append(PanelAttempt(attempt=number, accepted=False, failure=failure, note=note))
    return attempts


def run_stub_pipeline(
    store: RunStore,
    chapter_id: str,
    settings: RunSettings,
    *,
    step_seconds: float = 0.6,
    sleep: Callable[[float], None] = time.sleep,
) -> ChapterRun:
    run = store.load(chapter_id)
    run.settings = settings
    run.state = RunState.RUNNING
    run.error = ""
    run.panels = []
    run.log = [f"Run started with {settings.provider} / {settings.text_model}."]
    for status in run.stages.values():
        status.state, status.detail, status.attempts, status.cost = StageState.PENDING, "", 0, Cost()
    store.save(run)

    spec = run.spec
    brief_tokens = _tokens(spec.model_dump_json())
    panels = spec.target_pages * PANELS_PER_PAGE

    def stage(name: Stage, detail: str, attempts: int, cost: Cost) -> None:
        status = run.stages[name]
        status.state = StageState.RUNNING
        run.log.append(f"{name}: running...")
        store.save(run)
        sleep(step_seconds)
        status.state, status.detail, status.attempts, status.cost = (
            StageState.DONE, detail, attempts, cost,
        )
        run.log.append(f"{name}: {detail}")
        store.save(run)

    stage(
        Stage.STORY_ARCHITECT,
        f"{spec.target_pages} page beats",
        1,
        Cost(prompt_tokens=brief_tokens + 400, completion_tokens=150 * spec.target_pages, usd=0.0),
    )
    stage(
        Stage.SCRIPT,
        f"{panels} panels scripted, approved on revision 2",
        2,
        Cost(prompt_tokens=2 * (brief_tokens + 900), completion_tokens=2 * 120 * panels, usd=0.0),
    )
    run.panels = _stub_panels(spec)
    store.save(run)
    stage(
        Stage.VISUAL_DIRECTOR,
        f"{panels} panel specs",
        1,
        Cost(prompt_tokens=brief_tokens + 80 * panels, completion_tokens=90 * panels, usd=0.0),
    )
    status = run.stages[Stage.PANELS]
    status.state = StageState.RUNNING
    run.log.append(f"{Stage.PANELS}: running...")
    for number, panel in enumerate(run.panels):
        panel.attempts = _stub_attempts(number, settings.max_panel_attempts)
        tries = len(panel.attempts)
        status.attempts += tries
        status.cost = status.cost.add(
            Cost(prompt_tokens=300 * tries, completion_tokens=60 * tries, images=tries, usd=0.0)
        )
        status.detail = f"{number + 1}/{panels} panels"
        store.save(run)
        sleep(step_seconds / PANELS_PER_PAGE)
    accepted = sum(panel.accepted for panel in run.panels)
    status.state = StageState.DONE
    status.detail = (
        f"{accepted}/{panels} panels accepted in {status.attempts} images "
        f"({status.attempts / panels:.2f}/panel)"
    )
    run.log.append(f"{Stage.PANELS}: {status.detail}")
    store.save(run)
    stage(Stage.LAYOUT, f"{spec.target_pages} pages lettered", 1, Cost())
    stage(
        Stage.CHAPTER_JUDGE,
        "coherent sequence, no canon violations (stub)",
        1,
        Cost(prompt_tokens=200 * panels, completion_tokens=300, usd=0.0),
    )

    run.state = RunState.DONE
    run.log.append("Run finished.")
    store.save(run)
    return run
