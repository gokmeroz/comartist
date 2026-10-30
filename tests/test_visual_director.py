"""Visual Director: script alignment, bounded repair, and approved-reference handling."""

import json

import pytest

from comartist.adapters.fake import FakeTextModel
from comartist.agents.script_writer import parse_script
from comartist.agents.visual_director import (
    VisualDirector,
    VisualDirectorError,
    check_plan,
    parse_plan,
)
from comartist.models import ChapterSpec

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
