"""Resuming a stopped run keeps paid-for panels; crashes are recorded on the run."""

from pathlib import Path

from PIL import Image

from comartist.adapters.base import ModelError, ModelErrorKind
from comartist.adapters.fake import FakeImageModel, FakeTextModel
from comartist.agents.chapter_judge import ChapterJudge
from comartist.agents.critic import Critic
from comartist.agents.visual_director import VisualDirector
from comartist.models import (
    ChapterVerdict,
    CharacterLook,
    PanelAttempt,
    PanelResult,
    PanelSpec,
    RunSettings,
    RunState,
    Scene,
    Script,
    ScriptPanel,
    VisualPlan,
)
from comartist.workflows.panel_loop import PanelLoop
from comartist.workflows.store import RunStore, chapter_template
from comartist.workflows.stub_pipeline import can_resume, regenerate_panel, resume_pipeline, run_guarded

SETTINGS = RunSettings(provider="meta", text_model="m", image_model="i")
APPROVED = '{"approved": true, "score": 0.9}'
VERDICT = ChapterVerdict(approved=True, score=0.9, summary="Good.").model_dump_json()


def shot(panel_id: str) -> PanelSpec:
    return PanelSpec(
        panel_id=panel_id, framing="f", composition="c", poses="p", lighting="l", setting="s", characters=["Matt"]
    )


def stopped_run(store: RunStore, tmp_path: Path):
    run = store.create(chapter_template())
    finished = tmp_path / "done.png"
    Image.new("RGB", (600, 400)).save(finished)
    run.script = Script(scenes=[Scene(location="Roof", panels=[
        ScriptPanel(page=1, index=1, action="a", characters=["Matt"]),
        ScriptPanel(page=1, index=2, action="b", characters=["Matt"]),
    ])])
    run.visual_plan = VisualPlan(
        style="Ink", looks=[CharacterLook(name="Matt", appearance="a", outfit="o")],
        panels=[shot("p1-1"), shot("p1-2")],
    )
    run.panels = [
        PanelResult(panel_id="p1-1", page=1, index=1, description="a",
                    attempts=[PanelAttempt(attempt=1, accepted=True, image=str(finished), score=0.9)]),
        PanelResult(panel_id="p1-2", page=1, index=2, description="b"),
    ]
    run.state = RunState.FAILED
    store.save(run)
    return run


def test_resume_generates_only_missing_panels_and_finishes(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = stopped_run(store, tmp_path)
    assert can_resume(run)
    text, images = FakeTextModel([APPROVED, '{"heads": {}}', '{"heads": {}}', VERDICT]), FakeImageModel()
    loop = PanelLoop(images, Critic(text), VisualDirector(text))

    resume_pipeline(store, run.chapter_id, SETTINGS, loop, ChapterJudge(text))
    saved = store.load(run.chapter_id)

    assert len(images.requests) == 1
    assert saved.state is RunState.DONE and saved.verdict.approved and saved.pages


def test_resume_retries_a_panel_an_error_interrupted(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = stopped_run(store, tmp_path)
    run.panels[1].attempts = [PanelAttempt(attempt=1, accepted=False, failure="CRITIC_ERROR")]
    run.panels[1].interrupted = True
    store.save(run)
    text, images = FakeTextModel([APPROVED, '{"heads": {}}', '{"heads": {}}', VERDICT]), FakeImageModel()
    loop = PanelLoop(images, Critic(text), VisualDirector(text))

    resume_pipeline(store, run.chapter_id, SETTINGS, loop, ChapterJudge(text))
    saved = store.load(run.chapter_id)

    assert len(images.requests) == 1
    assert saved.panels[1].accepted and not saved.panels[1].interrupted
    assert saved.panels[1].attempts[0].failure == "CRITIC_ERROR"  # the earlier attempt stays on record
    assert saved.state is RunState.DONE


def test_crash_is_recorded_on_the_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = store.create(chapter_template())

    def explode(*_: object) -> None:
        raise TypeError("old code")

    run_guarded(explode, store, run.chapter_id)
    saved = store.load(run.chapter_id)
    assert saved.state is RunState.FAILED and "old code" in saved.error


def test_regenerate_uses_note_and_clears_old_verdict(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = stopped_run(store, tmp_path)
    run.panels[1].attempts = [PanelAttempt(attempt=1, accepted=True, image=run.panels[0].best_image, score=0.99)]
    run.state = RunState.DONE
    run.verdict = ChapterVerdict(approved=True, score=0.9, summary="Old.")
    store.save(run)
    text = FakeTextModel([APPROVED.replace("0.9", "0.5"), '{"heads": {}}', '{"heads": {}}', VERDICT])
    images = FakeImageModel()
    loop = PanelLoop(images, Critic(text), VisualDirector(text))

    regenerate_panel(store, run.chapter_id, SETTINGS, loop, ChapterJudge(text), "p1-2", "Keep the rain")
    saved = store.load(run.chapter_id)

    assert "Must fix: Keep the rain" in images.requests[0].prompt
    assert saved.panels[1].attempts[0].score == 0.5
    assert saved.verdict.summary == "Good." and saved.state is RunState.DONE


def test_failed_regeneration_stops_before_judging(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = stopped_run(store, tmp_path)
    old = run.panels[0].attempts
    run.state = RunState.DONE
    store.save(run)
    text = FakeTextModel([])
    images = FakeImageModel([ModelError(ModelErrorKind.TRANSIENT, "no network", "meta")])
    loop = PanelLoop(images, Critic(text), VisualDirector(text))

    regenerate_panel(store, run.chapter_id, SETTINGS, loop, ChapterJudge(text), "p1-1", "Keep the rain")
    saved = store.load(run.chapter_id)

    assert saved.state is RunState.FAILED and "no network" in saved.error
    assert saved.panels[0].attempts == old and saved.verdict is None
    assert "p1-1 regeneration FAILED" in saved.log[-1]
