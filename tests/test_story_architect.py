"""Story Architect: output validation, bounded repair, provenance, and pipeline wiring."""

import json
from pathlib import Path

import pytest

from comartist.adapters import ModelError, ModelErrorKind
from comartist.adapters.fake import FakeTextModel
from comartist.agents.story_architect import (
    StoryArchitect,
    StoryArchitectError,
    check_outline,
    parse_outline,
)
from comartist.models import ChapterSpec, RunSettings, RunState, Stage, StageState
from comartist.prompts import story_architect as prompt
from comartist.workflows.store import RunStore, chapter_template
from comartist.workflows.stub_pipeline import run_stub_pipeline

SPEC = ChapterSpec(
    title="Rooftop",
    premise="Matt tells Andy he is leaving the city.",
    characters=["Matt", "Andy"],
    canon=["Matt and Andy are brothers."],
    target_pages=2,
)


def outline_json(pages: list[int] | None = None, characters: list[str] | None = None) -> str:
    pages = pages or [1, 2]
    return json.dumps(
        {
            "logline": "A brother says goodbye.",
            "beats": [
                {
                    "page": page,
                    "summary": f"Beat {page}",
                    "characters": characters or ["Matt", "Andy"],
                    "emotion": "tense",
                    "turn": "something shifts",
                }
                for page in pages
            ],
            "proposed_facts": ["Matt got a job offer in Berlin."],
        }
    )


def test_prompt_includes_brief_and_canon() -> None:
    message = prompt.user_message(SPEC)
    assert "Pages: 2" in message
    assert "Characters: Matt, Andy" in message
    assert "- Matt and Andy are brothers." in message


def test_valid_outline_on_first_attempt() -> None:
    model = FakeTextModel([outline_json()])
    result = StoryArchitect(model).plan(SPEC)

    assert result.attempts == 1 and result.rejected == []
    assert [beat.page for beat in result.outline.beats] == [1, 2]
    assert result.outline.proposed_facts == ["Matt got a job offer in Berlin."]
    assert result.prompt_version == prompt.VERSION
    assert model.requests[0].json_mode
    assert model.requests[0].messages[0].content == prompt.SYSTEM


def test_code_fences_are_tolerated() -> None:
    outline, problems = parse_outline(f"```json\n{outline_json()}\n```")
    assert outline is not None and problems == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("not json", "Not valid JSON"),
        ('{"logline": "x", "beats": []}', "beats"),
        ('{"beats": [{"page": 1, "summary": "s", "characters": ["Matt"]}]}', "logline"),
    ],
)
def test_malformed_outlines_are_reported(text: str, problem: str) -> None:
    outline, problems = parse_outline(text)
    assert outline is None
    assert any(problem in p for p in problems)


def test_wrong_page_count_and_unknown_characters_are_caught() -> None:
    outline, _ = parse_outline(outline_json(pages=[1, 3], characters=["Matt", "Zoe"]))
    problems = check_outline(outline, SPEC)
    assert any("pages [1, 2]" in p for p in problems)
    assert any("Zoe" in p for p in problems)


def test_character_names_match_case_insensitively() -> None:
    outline, _ = parse_outline(outline_json(characters=["matt", "ANDY"]))
    assert check_outline(outline, SPEC) == []


def test_rejected_outline_is_repaired_with_feedback() -> None:
    model = FakeTextModel([outline_json(characters=["Zoe"]), outline_json()])
    result = StoryArchitect(model).plan(SPEC)

    assert result.attempts == 2
    assert "Zoe" in result.rejected[0][0]
    repair = model.requests[1].messages
    assert [m.role for m in repair] == ["system", "user", "assistant", "user"]
    assert "Zoe" in repair[-1].content
    first_prompt = sum(len(m.content) // 4 for m in model.requests[0].messages)
    assert result.cost.prompt_tokens > first_prompt  # both attempts are billed


def test_gives_up_after_max_attempts_with_evidence() -> None:
    model = FakeTextModel(["nope", "still nope", "never sent"])
    with pytest.raises(StoryArchitectError) as caught:
        StoryArchitect(model, max_attempts=2).plan(SPEC)
    assert len(caught.value.rejected) == 2
    assert len(model.requests) == 2
    assert caught.value.cost.prompt_tokens > 0


def run_with(tmp_path: Path, model: FakeTextModel):
    store = RunStore(tmp_path)
    chapter_id = store.create(chapter_template()).chapter_id
    settings = RunSettings(provider="meta", text_model="Muse Wonder", image_model="Muse Image")
    run = run_stub_pipeline(
        store, chapter_id, settings, step_seconds=0, sleep=lambda _: None,
        story_architect=StoryArchitect(model),
    )
    return run, store.load(chapter_id)


def test_pipeline_uses_real_story_architect(tmp_path: Path) -> None:
    template_pages = [1, 2, 3, 4]
    run, saved = run_with(tmp_path, FakeTextModel([outline_json(pages=template_pages)]))

    assert run.state is RunState.DONE
    assert saved.outline is not None and len(saved.outline.beats) == 4
    assert saved.prompt_versions[Stage.STORY_ARCHITECT] == prompt.VERSION
    assert saved.stages[Stage.STORY_ARCHITECT].attempts == 1


def test_pipeline_stops_when_story_architect_fails(tmp_path: Path) -> None:
    down = ModelError(ModelErrorKind.QUOTA, "no credits", "meta")
    run, saved = run_with(tmp_path, FakeTextModel([down]))

    assert saved.state is RunState.FAILED
    assert "no credits" in saved.error
    assert saved.stages[Stage.STORY_ARCHITECT].state is StageState.FAILED
    assert saved.stages[Stage.SCRIPT].state is StageState.PENDING
    assert saved.outline is None and saved.panels == []
