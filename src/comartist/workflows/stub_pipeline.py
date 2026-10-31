"""Offline stand-in for the chapter workflow so the UI runs end to end.

Each stage reports believable progress, attempt counts, and token usage, but no model is
called and the cost is $0. The real LangGraph workflow will replace this behind the same
`ChapterRun` status updates.
"""

import time
from collections.abc import Callable

from comartist.adapters import ModelError
from comartist.agents.chapter_judge import ChapterJudge, ChapterJudgeError
from comartist.agents.story_architect import StoryArchitect, StoryArchitectError
from comartist.agents.visual_director import VisualDirector, VisualDirectorError
from comartist.models import (
    ChapterRun,
    ChapterSpec,
    Cost,
    PanelAttempt,
    PanelResult,
    RunSettings,
    RunState,
    Script,
    Stage,
    StageState,
)
from comartist.tools.lettering import letter_chapter
from comartist.workflows.panel_loop import PanelLoop
from comartist.workflows.script_loop import ScriptLoop, ScriptLoopError
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


def _script_panels(script: Script) -> list[PanelResult]:
    return [
        PanelResult(
            panel_id=panel.panel_id,
            page=panel.page,
            index=panel.index,
            description=panel.action,
            caption=panel.caption,
            dialogue="\n".join(f"{line.speaker}: {line.text}" for line in panel.dialogue),
        )
        for panel in script.panels
    ]


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


def _stub_panel_stage(store, run, settings, status, panels, step_seconds, sleep) -> None:
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


def _real_panels(store: RunStore, run: ChapterRun, settings: RunSettings, loop: PanelLoop) -> bool:
    """Generate every panel. True means the run stopped early and has been marked so."""
    status = run.stages[Stage.PANELS]
    shots = {shot.panel_id: shot for shot in run.visual_plan.panels}
    actions = {panel.panel_id: panel.action for panel in run.script.panels}
    folder = store.root / run.chapter_id / "panels"
    folder.mkdir(exist_ok=True)
    for number, panel in enumerate(run.panels):
        if panel.attempts:  # already tried, on a run being resumed
            continue
        remaining = settings.chapter_budget_usd - (run.cost.usd or 0)
        if remaining <= 0:
            status.state, status.detail = StageState.FAILED, f"budget spent at {number}/{len(run.panels)} panels"
            run.state, run.error = RunState.BUDGET_EXHAUSTED, "Chapter budget exhausted; finished panels are kept."
            run.log.append(f"{Stage.PANELS}: {status.detail}")
            store.save(run)
            return True
        result = loop.run(
            run.spec, run.visual_plan, shots[panel.panel_id], actions[panel.panel_id], folder, remaining
        )
        panel.attempts = result.attempts
        status.attempts += len(result.attempts)
        status.cost = status.cost.add(result.cost)
        status.detail = f"{number + 1}/{len(run.panels)} panels"
        run.prompt_versions[Stage.PANELS] = ", ".join(sorted(result.prompt_versions))
        run.log.append(f"{Stage.PANELS}: {panel.panel_id} {result.stop_reason} after {len(result.attempts)}")
        store.save(run)
        if result.error:
            status.state, status.detail = StageState.FAILED, f"stopped at {panel.panel_id}"
            run.state, run.error = RunState.FAILED, result.error
            run.log.append(f"{Stage.PANELS}: FAILED - {result.error}")
            store.save(run)
            return True
    return False


def _finish_real(
    store: RunStore, run: ChapterRun, settings: RunSettings, loop: PanelLoop, judge: ChapterJudge | None
) -> ChapterRun:
    """Panels onward: generate what is missing, letter, and judge."""
    status = run.stages[Stage.PANELS]
    status.state = StageState.RUNNING
    store.save(run)
    if _real_panels(store, run, settings, loop):
        return run
    accepted = sum(panel.accepted for panel in run.panels)
    status.state = StageState.DONE
    status.detail = f"{accepted}/{len(run.panels)} panels accepted in {status.attempts} attempts"
    run.log.append(f"{Stage.PANELS}: {status.detail}")
    status = run.stages[Stage.LAYOUT]
    status.state = StageState.RUNNING
    store.save(run)
    status.cost = loop.locate_heads(run)
    run.pages, run.pdf = letter_chapter(run, store.root / run.chapter_id / "pages")
    status.state, status.attempts = StageState.DONE, 1
    status.detail = f"{len(run.pages)} pages lettered, PDF exported"
    run.log.append(f"{Stage.LAYOUT}: {status.detail}")
    store.save(run)
    status = run.stages[Stage.CHAPTER_JUDGE]
    if judge is None:
        status.state, status.detail = StageState.PENDING, "no judge configured"
    else:
        status.state = StageState.RUNNING
        run.log.append(f"{Stage.CHAPTER_JUDGE}: running ({settings.text_model})...")
        store.save(run)
        try:
            judged = judge.judge(run.spec, run.script, run.pages)
        except (ChapterJudgeError, ModelError) as error:
            status.state, status.detail = StageState.FAILED, "no valid verdict"
            if isinstance(error, ChapterJudgeError):
                status.cost = error.cost
            run.state, run.error = RunState.FAILED, str(error)
            run.log.append(f"{Stage.CHAPTER_JUDGE}: FAILED - {error}")
            store.save(run)
            return run
        run.verdict = judged.verdict
        run.prompt_versions[Stage.CHAPTER_JUDGE] = judged.prompt_version
        status.state, status.attempts, status.cost = StageState.DONE, 1, judged.cost
        outcome = "approved" if judged.verdict.approved else "not approved"
        status.detail = f"{outcome}, score {judged.verdict.score:.2f}"
        run.log.append(f"{Stage.CHAPTER_JUDGE}: {status.detail}")
    run.state = RunState.DONE
    run.log.append("Run finished. Nothing is canon until the chapter is accepted.")
    store.save(run)
    return run


def can_resume(run: ChapterRun) -> bool:
    """A stopped run with a plan can finish without repaying for finished stages."""
    return (
        run.state in (RunState.FAILED, RunState.BUDGET_EXHAUSTED)
        and run.visual_plan is not None
        and run.script is not None
        and bool(run.panels)
    )


def resume_pipeline(
    store: RunStore,
    chapter_id: str,
    settings: RunSettings,
    panel_loop: PanelLoop,
    chapter_judge: ChapterJudge | None,
) -> ChapterRun:
    run = store.load(chapter_id)
    run.state, run.error, run.settings = RunState.RUNNING, "", settings
    run.log.append("Resumed: keeping finished panels.")
    return _finish_real(store, run, settings, panel_loop, chapter_judge)


def regenerate_panel(
    store: RunStore,
    chapter_id: str,
    settings: RunSettings,
    panel_loop: PanelLoop,
    chapter_judge: ChapterJudge | None,
    panel_id: str,
    note: str,
) -> ChapterRun:
    """Redo one panel with a person's note, then re-letter and re-judge the chapter."""
    run = store.load(chapter_id)
    run.state, run.error, run.accepted, run.verdict = RunState.RUNNING, "", False, None
    store.save(run)
    panel = next(item for item in run.panels if item.panel_id == panel_id)
    shot = next(item for item in run.visual_plan.panels if item.panel_id == panel_id)
    action = next(item.action for item in run.script.panels if item.panel_id == panel_id)
    folder = store.root / run.chapter_id / "panels"
    folder.mkdir(parents=True, exist_ok=True)
    result = panel_loop.run(
        run.spec, run.visual_plan, shot, action, folder,
        settings.chapter_budget_usd, [note],
    )
    status = run.stages[Stage.PANELS]
    status.attempts += len(result.attempts)
    status.cost = status.cost.add(result.cost)
    if result.accepted:
        panel.attempts = result.attempts  # the note outranks the earlier, higher-scored image
    run.log.append(f"{Stage.PANELS}: {panel_id} regenerated ({result.stop_reason}): {note}")
    return _finish_real(store, run, settings, panel_loop, chapter_judge)


def run_guarded(pipeline: Callable[..., ChapterRun], store: RunStore, chapter_id: str, *args, **kwargs) -> None:
    """Thread entry point: a crash must show up on the run, never vanish with the thread."""
    try:
        pipeline(store, chapter_id, *args, **kwargs)
    except Exception as error:  # noqa: BLE001 - recorded and shown, not swallowed
        run = store.load(chapter_id)
        run.state, run.error = RunState.FAILED, f"{type(error).__name__}: {error}"
        run.log.append(f"CRASHED - {run.error}")
        store.save(run)


def run_stub_pipeline(
    store: RunStore,
    chapter_id: str,
    settings: RunSettings,
    *,
    step_seconds: float = 0.6,
    sleep: Callable[[float], None] = time.sleep,
    story_architect: StoryArchitect | None = None,
    script_loop: ScriptLoop | None = None,
    visual_director: VisualDirector | None = None,
    panel_loop: PanelLoop | None = None,
    chapter_judge: ChapterJudge | None = None,
) -> ChapterRun:
    """Stages given an agent call a real model; the rest stay simulated.

    `script_loop` needs an outline and `visual_director` an approved script, so each runs
    only when the stage before it was real.
    """
    run = store.load(chapter_id)
    run.settings = settings
    run.state = RunState.RUNNING
    run.error = ""
    run.outline = None
    run.script = None
    run.script_critique = None
    run.visual_plan = None
    run.prompt_versions = {}
    run.panels = []
    run.pages, run.pdf = [], ""
    run.verdict, run.accepted = None, False
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

    if story_architect is None:
        stage(
            Stage.STORY_ARCHITECT,
            f"{spec.target_pages} page beats",
            1,
            Cost(prompt_tokens=brief_tokens + 400, completion_tokens=150 * spec.target_pages, usd=0.0),
        )
    else:
        status = run.stages[Stage.STORY_ARCHITECT]
        status.state = StageState.RUNNING
        run.log.append(f"{Stage.STORY_ARCHITECT}: running ({settings.text_model})...")
        store.save(run)
        try:
            result = story_architect.plan(spec)
        except (StoryArchitectError, ModelError) as error:
            status.state, status.detail = StageState.FAILED, "no valid outline"
            if isinstance(error, StoryArchitectError):
                status.attempts, status.cost = len(error.rejected), error.cost
            run.state, run.error = RunState.FAILED, str(error)
            run.log.append(f"{Stage.STORY_ARCHITECT}: FAILED - {error}")
            store.save(run)
            return run
        run.outline = result.outline
        run.prompt_versions[Stage.STORY_ARCHITECT] = result.prompt_version
        status.state, status.attempts, status.cost = StageState.DONE, result.attempts, result.cost
        status.detail = f"{len(result.outline.beats)} page beats ({result.provider})"
        run.log.append(
            f"{Stage.STORY_ARCHITECT}: {result.outline.logline} "
            f"[{result.model}, {result.prompt_version}, attempt {result.attempts}]"
        )
        store.save(run)
    if script_loop is None or run.outline is None:
        stage(
            Stage.SCRIPT,
            f"{panels} panels scripted, approved on revision 2",
            2,
            Cost(prompt_tokens=2 * (brief_tokens + 900), completion_tokens=2 * 120 * panels, usd=0.0),
        )
        run.panels = _stub_panels(spec)
    else:
        status = run.stages[Stage.SCRIPT]
        status.state = StageState.RUNNING
        run.log.append(f"{Stage.SCRIPT}: running ({settings.text_model})...")
        store.save(run)
        try:
            written = script_loop.run(spec, run.outline)
        except (ScriptLoopError, ModelError) as error:
            status.state, status.detail = StageState.FAILED, "no reviewed script"
            if isinstance(error, ScriptLoopError):
                status.attempts, status.cost = len(error.drafts), error.cost
            run.state, run.error = RunState.FAILED, str(error)
            run.log.append(f"{Stage.SCRIPT}: FAILED - {error}")
            store.save(run)
            return run
        run.script, run.script_critique = written.script, written.critique
        run.prompt_versions[Stage.SCRIPT] = ", ".join(sorted(written.prompt_versions.values()))
        status.attempts, status.cost = written.attempts, written.cost
        if not written.approved:
            status.state = StageState.FAILED
            status.detail = f"not approved: {written.stop_reason}, best score {written.critique.score:.2f}"
            run.state = RunState.FAILED
            run.error = f"Script not approved after {written.attempts} drafts ({written.stop_reason})."
            run.log.append(f"{Stage.SCRIPT}: {status.detail}")
            store.save(run)
            return run
        run.panels = _script_panels(written.script)
        panels = len(run.panels)
        status.state = StageState.DONE
        status.detail = f"{panels} panels approved on draft {written.attempts} ({written.provider})"
        run.log.append(
            f"{Stage.SCRIPT}: {status.detail} [{written.model}, {run.prompt_versions[Stage.SCRIPT]}]"
        )
    store.save(run)
    if visual_director is None or run.script is None:
        stage(
            Stage.VISUAL_DIRECTOR,
            f"{panels} panel specs",
            1,
            Cost(prompt_tokens=brief_tokens + 80 * panels, completion_tokens=90 * panels, usd=0.0),
        )
    else:
        status = run.stages[Stage.VISUAL_DIRECTOR]
        status.state = StageState.RUNNING
        run.log.append(f"{Stage.VISUAL_DIRECTOR}: running ({settings.text_model})...")
        store.save(run)
        try:
            directed = visual_director.plan(spec, run.script)
        except (VisualDirectorError, ModelError) as error:
            status.state, status.detail = StageState.FAILED, "no valid visual plan"
            if isinstance(error, VisualDirectorError):
                status.attempts, status.cost = len(error.rejected), error.cost
            run.state, run.error = RunState.FAILED, str(error)
            run.log.append(f"{Stage.VISUAL_DIRECTOR}: FAILED - {error}")
            store.save(run)
            return run
        run.visual_plan = directed.plan
        run.prompt_versions[Stage.VISUAL_DIRECTOR] = directed.prompt_version
        status.state, status.attempts, status.cost = StageState.DONE, directed.attempts, directed.cost
        status.detail = f"{len(directed.plan.panels)} panel specs ({directed.provider})"
        run.log.append(
            f"{Stage.VISUAL_DIRECTOR}: {status.detail} "
            f"[{directed.model}, {directed.prompt_version}, attempt {directed.attempts}]"
        )
        unreferenced = sorted(set(spec.characters) - set(spec.references))
        if unreferenced:
            run.log.append(f"{Stage.VISUAL_DIRECTOR}: no approved reference for {', '.join(unreferenced)}")
        store.save(run)
    status = run.stages[Stage.PANELS]
    status.state = StageState.RUNNING
    run.log.append(f"{Stage.PANELS}: running...")
    if panel_loop is not None and run.visual_plan is not None and run.script is not None:
        return _finish_real(store, run, settings, panel_loop, chapter_judge)
    _stub_panel_stage(store, run, settings, status, panels, step_seconds, sleep)
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
    run.log.append("Run finished. Nothing is canon until the chapter is accepted.")
    store.save(run)
    return run
