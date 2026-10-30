"""Critic script mode and the bounded Script Writer <-> Critic loop."""

import json
from pathlib import Path

import pytest

from comartist.adapters import ModelError, ModelErrorKind
from comartist.adapters.fake import FakeTextModel
from comartist.agents.critic import Critic, CriticError
from comartist.agents.script_writer import ScriptWriter, parse_script
from comartist.agents.story_architect import StoryArchitect
from comartist.models import (
    ChapterSpec,
    PageBeat,
    RunSettings,
    RunState,
    ScriptCritique,
    Stage,
    StageState,
    StoryOutline,
)
from comartist.workflows.script_loop import ScriptLoop, ScriptLoopError, StopReason
from comartist.workflows.store import RunStore, chapter_template
from comartist.workflows.stub_pipeline import run_stub_pipeline

SPEC = ChapterSpec(title="Roof", premise="A goodbye.", characters=["Matt"], target_pages=1)
OUTLINE = StoryOutline(
    logline="x", beats=[PageBeat(page=1, summary="Matt waits.", characters=["Matt"])]
)


def script(action: str = "Matt waits.", page: int = 1, name: str = "Matt") -> str:
    panel = {"page": page, "index": 1, "action": action, "characters": [name]}
    return json.dumps({"scenes": [{"location": "Roof", "panels": [panel]}]})


def rejected(score: float = 0.4, panel: str = "p1-1", category: str = "PACING") -> str:
    issue = {"category": category, "panel_id": panel, "evidence": "Flat.", "repair": "Add a turn."}
    return json.dumps({"approved": False, "score": score, "issues": [issue]})


APPROVED = json.dumps({"approved": True, "score": 0.9})


def loop_for(replies: list, max_attempts: int = 3) -> tuple[ScriptLoop, FakeTextModel]:
    model = FakeTextModel(replies)
    return ScriptLoop(ScriptWriter(model), Critic(model), max_attempts), model


def test_rejection_without_issues_is_invalid() -> None:
    with pytest.raises(ValueError):
        ScriptCritique(approved=False, score=0.1)


def test_unknown_failure_category_is_repaired_then_given_up() -> None:
    bad = rejected(category="VIBES")
    model = FakeTextModel([bad, bad])
    with pytest.raises(CriticError) as caught:
        Critic(model).review_script(SPEC, OUTLINE, parse_script(script())[0])
    assert len(caught.value.rejected) == 2


def test_approved_first_draft_stops_immediately() -> None:
    loop, model = loop_for([script(), APPROVED])
    result = loop.run(SPEC, OUTLINE)

    assert result.approved and result.stop_reason is StopReason.APPROVED
    assert result.attempts == 1 and len(model.requests) == 2
    assert set(result.prompt_versions) == {"writer", "critic"}


def test_rejection_routes_back_to_writer_with_evidence() -> None:
    loop, model = loop_for([script(), rejected(), script("Matt turns."), APPROVED])
    result = loop.run(SPEC, OUTLINE)

    assert result.approved and result.attempts == 2
    assert result.script.panels[0].action == "Matt turns."
    revision = model.requests[2].messages[-1].content
    assert "[PACING] p1-1" in revision and "Add a turn." in revision


def test_stops_at_max_attempts_keeping_best_unapproved_draft() -> None:
    loop, model = loop_for(
        [
            script("one"), rejected(0.3, "p1-1"),
            script("two"), rejected(0.8, ""),
            script("three"), rejected(0.5, "p1-1"),
            "never sent",
        ]
    )
    result = loop.run(SPEC, OUTLINE)

    assert not result.approved and result.stop_reason is StopReason.ATTEMPTS_EXHAUSTED
    assert result.attempts == 3 and len(model.requests) == 6
    assert result.script.panels[0].action == "two"


def test_repeated_failure_stops_early() -> None:
    loop, model = loop_for([script("one"), rejected(), script("two"), rejected(), "never sent"])
    result = loop.run(SPEC, OUTLINE)

    assert result.stop_reason is StopReason.REPEATED_FAILURE
    assert result.attempts == 2 and not result.approved


def test_failure_during_revision_keeps_spend_and_drafts() -> None:
    down = ModelError(ModelErrorKind.QUOTA, "no credits", "meta")
    loop, _ = loop_for([script(), rejected(), down])
    with pytest.raises(ScriptLoopError) as caught:
        loop.run(SPEC, OUTLINE)
    assert "no credits" in str(caught.value)
    assert len(caught.value.drafts) == 1
    assert caught.value.cost.prompt_tokens > 0


def test_max_attempts_comes_from_settings_default() -> None:
    settings = RunSettings(provider="meta", text_model="m", image_model="i")
    assert settings.max_script_attempts == 3


def test_pipeline_surfaces_unapproved_script_as_failed(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    chapter_id = store.create(chapter_template()).chapter_id
    spec = store.load(chapter_id).spec
    name = spec.characters[0]
    pages = range(1, spec.target_pages + 1)
    outline = json.dumps(
        {"logline": "x", "beats": [{"page": n, "summary": "s", "characters": [name]} for n in pages]}
    )
    panels = [{"page": n, "index": 1, "action": "a", "characters": [name]} for n in pages]
    draft = json.dumps({"scenes": [{"location": "Roof", "panels": panels}]})
    model = FakeTextModel([outline, draft, rejected(), draft, rejected()])
    settings = RunSettings(provider="meta", text_model="m", image_model="i")
    run_stub_pipeline(
        store, chapter_id, settings, step_seconds=0, sleep=lambda _: None,
        story_architect=StoryArchitect(model),
        script_loop=ScriptLoop(ScriptWriter(model), Critic(model)),
    )
    saved = store.load(chapter_id)

    assert saved.state is RunState.FAILED
    assert saved.stages[Stage.SCRIPT].state is StageState.FAILED
    assert saved.script is not None and not saved.script_critique.approved
    assert saved.panels == []
    assert saved.stages[Stage.VISUAL_DIRECTOR].state is StageState.PENDING
