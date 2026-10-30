"""Script Writer: output validation, bounded repair, canon safety, and pipeline wiring."""

import json
from pathlib import Path

import pytest

from comartist.adapters import ModelError, ModelErrorKind
from comartist.adapters.fake import FakeTextModel
from comartist.agents.critic import Critic
from comartist.agents.script_writer import (
    ScriptWriter,
    ScriptWriterError,
    check_script,
    parse_script,
)
from comartist.agents.story_architect import StoryArchitect
from comartist.models import (
    ChapterRun,
    ChapterSpec,
    PageBeat,
    RunSettings,
    RunState,
    Stage,
    StageState,
    StoryOutline,
)
from comartist.prompts import script_writer as prompt
from comartist.workflows.script_loop import ScriptLoop
from comartist.workflows.store import RunStore, chapter_template
from comartist.workflows.stub_pipeline import run_stub_pipeline

SPEC = ChapterSpec(
    title="Rooftop",
    premise="Matt tells Andy he is leaving the city.",
    characters=["Matt", "Andy"],
    canon=["Matt and Andy are brothers."],
    target_pages=2,
)
OUTLINE = StoryOutline(
    logline="A brother says goodbye.",
    beats=[
        PageBeat(page=1, summary="Matt waits alone.", characters=["Matt"], location="Rooftop"),
        PageBeat(page=2, summary="Andy arrives.", characters=["Matt", "Andy"], location="Rooftop"),
    ],
)


def panel(page: int, index: int, characters: list[str], speaker: str = "Matt") -> dict:
    return {
        "page": page,
        "index": index,
        "action": f"Moment {page}.{index}",
        "characters": characters,
        "dialogue": [{"speaker": speaker, "text": "Hey."}],
    }


def script_json(panels: list[dict] | None = None) -> str:
    panels = panels or [panel(1, 1, ["Matt"]), panel(1, 2, ["Matt"]), panel(2, 1, ["Matt", "Andy"])]
    return json.dumps(
        {
            "scenes": [{"location": "Rooftop", "panels": panels}],
            "proposed_facts": ["Matt sold his bike."],
        }
    )


def problems_for(panels: list[dict]) -> list[str]:
    script, _ = parse_script(script_json(panels))
    return check_script(script, SPEC, OUTLINE)


def test_prompt_includes_outline_and_canon() -> None:
    message = prompt.user_message(SPEC, OUTLINE)
    assert "- Matt and Andy are brothers." in message
    assert "Page 2 (Matt, Andy; location: Rooftop): Andy arrives." in message


def test_valid_script_on_first_attempt() -> None:
    model = FakeTextModel([script_json()])
    result = ScriptWriter(model).write(SPEC, OUTLINE)

    assert result.attempts == 1 and result.rejected == []
    assert [p.panel_id for p in result.script.panels] == ["p1-1", "p1-2", "p2-1"]
    assert result.script.proposed_facts == ["Matt sold his bike."]
    assert result.prompt_version == prompt.VERSION
    assert model.requests[0].json_mode


def test_valid_script_passes_checks() -> None:
    script, _ = parse_script(script_json())
    assert check_script(script, SPEC, OUTLINE) == []


def test_missing_page_is_caught() -> None:
    assert any("cover pages" in p for p in problems_for([panel(1, 1, ["Matt"])]))


def test_numbering_gap_is_caught() -> None:
    problems = problems_for([panel(1, 2, ["Matt"]), panel(2, 1, ["Andy"])])
    assert any("without gaps" in p for p in problems)


def test_out_of_order_panels_are_caught() -> None:
    problems = problems_for([panel(2, 1, ["Andy"]), panel(1, 1, ["Matt"])])
    assert any("reading order" in p for p in problems)


def test_too_many_panels_are_caught() -> None:
    panels = [panel(1, i, ["Matt"]) for i in range(1, 8)] + [panel(2, 1, ["Andy"])]
    assert any("maximum" in p for p in problems_for(panels))


def test_character_outside_page_beat_is_caught() -> None:
    problems = problems_for([panel(1, 1, ["Andy"]), panel(2, 1, ["Andy"])])
    assert any("p1-1" in p and "Andy" in p for p in problems)


def test_invented_speaker_is_caught() -> None:
    problems = problems_for([panel(1, 1, ["Matt"], speaker="Zoe"), panel(2, 1, ["Andy"])])
    assert any("Zoe" in p for p in problems)


def test_rejected_script_is_repaired_with_feedback() -> None:
    bad = script_json([panel(1, 1, ["Matt"], speaker="Zoe"), panel(2, 1, ["Andy"])])
    model = FakeTextModel([bad, script_json()])
    result = ScriptWriter(model).write(SPEC, OUTLINE)

    assert result.attempts == 2
    assert "Zoe" in result.rejected[0][0]
    assert "Zoe" in model.requests[1].messages[-1].content


def test_gives_up_after_max_attempts_with_evidence() -> None:
    model = FakeTextModel(["nope", "still nope", "never sent"])
    with pytest.raises(ScriptWriterError) as caught:
        ScriptWriter(model, max_attempts=2).write(SPEC, OUTLINE)
    assert len(caught.value.rejected) == 2
    assert len(model.requests) == 2


def run_with(tmp_path: Path, replies: list) -> ChapterRun:
    store = RunStore(tmp_path)
    chapter_id = store.create(chapter_template()).chapter_id
    spec = store.load(chapter_id).spec
    name = spec.characters[0]
    beats = [{"page": n, "summary": "s", "characters": [name]} for n in range(1, spec.target_pages + 1)]
    outline = json.dumps({"logline": "x", "beats": beats})
    panels = [panel(n, 1, [name], speaker=name) for n in range(1, spec.target_pages + 1)]
    replies = [outline, *[script_json(panels) if r == "script" else r for r in replies]]
    model = FakeTextModel(replies)
    settings = RunSettings(provider="meta", text_model="Muse Wonder", image_model="Muse Image")
    run_stub_pipeline(
        store, chapter_id, settings, step_seconds=0, sleep=lambda _: None,
        story_architect=StoryArchitect(model), script_loop=ScriptLoop(ScriptWriter(model), Critic(model)),
    )
    return store.load(chapter_id)


def test_pipeline_uses_real_script(tmp_path: Path) -> None:
    saved = run_with(tmp_path, ["script", '{"approved": true, "score": 0.9}'])

    assert saved.state is RunState.DONE
    assert saved.script is not None
    assert [p.panel_id for p in saved.panels] == [p.panel_id for p in saved.script.panels]
    assert saved.panels[0].description == "Moment 1.1"
    assert saved.panels[0].dialogue.endswith(": Hey.")
    assert prompt.VERSION in saved.prompt_versions[Stage.SCRIPT]


def test_pipeline_stops_when_script_writer_fails(tmp_path: Path) -> None:
    saved = run_with(tmp_path, [ModelError(ModelErrorKind.QUOTA, "no credits", "meta")])

    assert saved.state is RunState.FAILED
    assert saved.stages[Stage.SCRIPT].state is StageState.FAILED
    assert saved.stages[Stage.VISUAL_DIRECTOR].state is StageState.PENDING
    assert saved.script is None and saved.panels == []
