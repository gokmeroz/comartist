"""Visual Director: script alignment, bounded repair, and approved-reference handling."""

import json
from pathlib import Path

import pytest

from comartist.adapters.fake import FakeImageModel, FakeTextModel
from comartist.agents.script_writer import parse_script
from comartist.agents.visual_director import (
    VisualDirector,
    VisualDirectorError,
    check_plan,
    parse_plan,
)
from comartist.models import ChapterSpec, CharacterLook
from comartist.tools.character_sheets import approve_sheet, generate_sheet
from comartist.workflows.store import RunStore, chapter_template

SPEC = ChapterSpec(
    title="Roof", premise="A goodbye.", characters=["Matt", "Andy"], target_pages=1,
    references={"Matt": "data:image/png;base64,AAAA"},
)
SCRIPT, _ = parse_script(
    json.dumps(
        {
            "scenes": [
                {
                    "location": "Roof",
                    "panels": [
                        {"page": 1, "index": 1, "action": "Matt waits.", "characters": ["Matt"]},
                        {"page": 1, "index": 2, "action": "Andy arrives.", "characters": ["Matt", "Andy"]},
                    ],
                }
            ]
        }
    )
)


def shot(panel_id: str, characters: list[str], **extra: object) -> dict:
    fields = ("framing", "composition", "poses", "lighting", "setting")
    return {"panel_id": panel_id, "characters": characters, **{f: "x" for f in fields}, **extra}


def plan_json(panels: list[dict] | None = None, looks: list[str] | None = None) -> str:
    panels = panels or [shot("p1-1", ["Matt"]), shot("p1-2", ["Matt", "Andy"])]
    names = looks or ["Matt", "Andy"]
    return json.dumps(
        {
            "style": "Ink and flat colour",
            "looks": [{"name": n, "appearance": "tall", "outfit": "green jacket"} for n in names],
            "panels": panels,
        }
    )


def problems_for(text: str) -> list[str]:
    plan, _ = parse_plan(text)
    return check_plan(plan, SCRIPT)


def test_valid_plan_attaches_only_approved_references() -> None:
    result = VisualDirector(FakeTextModel([plan_json()])).plan(SPEC, SCRIPT)

    assert result.attempts == 1
    assert [panel.references for panel in result.plan.panels] == [["Matt"], ["Matt"]]


def test_model_cannot_claim_a_reference() -> None:
    claimed = plan_json([shot("p1-1", ["Matt"]), shot("p1-2", ["Matt", "Andy"], references=["Andy"])])
    result = VisualDirector(FakeTextModel([claimed])).plan(SPEC, SCRIPT)
    assert "Andy" not in result.plan.panels[1].references


def test_missing_panel_is_caught() -> None:
    assert any("in order" in p for p in problems_for(plan_json([shot("p1-1", ["Matt"])])))


def test_wrong_cast_is_caught() -> None:
    text = plan_json([shot("p1-1", ["Andy"]), shot("p1-2", ["Matt", "Andy"])])
    assert any("p1-1 must show" in p for p in problems_for(text))


def test_character_without_look_is_caught() -> None:
    assert any("no look" in p and "andy" in p for p in problems_for(plan_json(looks=["Matt"])))


def test_rejected_plan_is_repaired_with_feedback() -> None:
    model = FakeTextModel([plan_json(looks=["Matt"]), plan_json()])
    result = VisualDirector(model).plan(SPEC, SCRIPT)
    assert result.attempts == 2
    assert "no look" in model.requests[1].messages[-1].content


def test_gives_up_after_max_attempts() -> None:
    model = FakeTextModel(["nope", "nope", "never sent"])
    with pytest.raises(VisualDirectorError) as caught:
        VisualDirector(model, max_attempts=2).plan(SPEC, SCRIPT)
    assert len(caught.value.rejected) == 2 and len(model.requests) == 2


def test_locked_look_overrides_the_model_and_reaches_the_prompt() -> None:
    locked = CharacterLook(name="Matt", appearance="short", outfit="red coat")
    spec = SPEC.model_copy(update={"locked_looks": [locked]})
    model = FakeTextModel([plan_json()])
    result = VisualDirector(model).plan(spec, SCRIPT)

    assert result.plan.looks[0] == locked
    assert "red coat" in model.requests[0].messages[1].content


def test_sheet_stays_a_draft_until_approved(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = store.create(chapter_template())
    look = CharacterLook(name="Matt", appearance="short", outfit="red coat")
    model = FakeImageModel()

    location = generate_sheet(model, store, run, look, "Ink")
    saved = store.load(run.chapter_id)
    assert Path(location).exists() and saved.reference_cost.images == 1
    assert saved.spec.references == {} and saved.spec.locked_looks == []
    assert "red coat" in model.requests[0].prompt

    approve_sheet(store, saved, look)
    saved = store.load(run.chapter_id)
    assert saved.spec.references == {"Matt": location}
    assert saved.spec.locked_looks == [look]


def test_regenerating_keeps_the_approved_file(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = store.create(chapter_template())
    look = CharacterLook(name="Matt", appearance="short", outfit="red coat")
    first = generate_sheet(FakeImageModel(), store, run, look, "Ink")
    approve_sheet(store, run, look)
    second = generate_sheet(FakeImageModel(), store, run, look, "Ink")

    assert first != second and Path(first).exists()
    assert run.spec.references["Matt"] == first


def test_style_is_fixed_and_layout_sets_panel_size() -> None:
    result = VisualDirector(FakeTextModel([plan_json()])).plan(SPEC, SCRIPT)
    assert "American superhero comic" in result.plan.style
    custom = SPEC.model_copy(update={"art_style": "Noir"})
    assert VisualDirector(FakeTextModel([plan_json()])).plan(custom, SCRIPT).plan.style == "Noir"


def test_layout_with_wrong_panel_count_is_rejected() -> None:
    three = SCRIPT.model_copy(deep=True)
    third = three.scenes[0].panels[1].model_copy(update={"index": 3})
    three.scenes[0].panels.append(third)
    plan = json.loads(plan_json([shot("p1-1", ["Matt"]), shot("p1-2", ["Matt", "Andy"]), shot("p1-3", ["Matt", "Andy"])]))
    plan["layouts"] = [{"page": 1, "template": "offset_grid"}]
    parsed, _ = parse_plan(json.dumps(plan))
    assert any("choose a layout" in p for p in check_plan(parsed, three))
