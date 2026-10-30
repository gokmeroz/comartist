"""Panel loop: routing by failure category, limits, budget, and best-attempt selection."""

import json
from pathlib import Path

from comartist.adapters import ModelError, ModelErrorKind
from comartist.adapters.fake import FakeImageModel, FakeTextModel
from comartist.agents.critic import Critic
from comartist.agents.visual_director import VisualDirector
from comartist.models import (
    ChapterSpec,
    CharacterLook,
    PanelAttempt,
    PanelResult,
    PanelSpec,
    VisualPlan,
)
from comartist.workflows.panel_loop import PanelLoop, PanelStop

SHOT = PanelSpec(
    panel_id="p1-1", framing="wide", composition="centered", poses="still", lighting="noon",
    setting="roof", characters=["Matt"], references=["Matt"],
)
PLAN = VisualPlan(
    style="Ink",
    looks=[CharacterLook(name="Matt", appearance="short", outfit="red coat")],
    panels=[SHOT],
)
APPROVED = json.dumps({"approved": True, "score": 0.9})


def rejected(category: str = "COMPOSITION", score: float = 0.4) -> str:
    return json.dumps(
        {"approved": False, "score": score,
         "issues": [{"category": category, "evidence": "Off.", "repair": "Center him."}]}
    )


def run(tmp_path: Path, replies: list, budget: float = 5.0, images: FakeImageModel | None = None):
    reference = tmp_path / "matt.png"
    reference.write_bytes(b"png")
    spec = ChapterSpec(title="R", premise="p", characters=["Matt"], references={"Matt": str(reference)})
    text = FakeTextModel(replies)
    images = images or FakeImageModel()
    loop = PanelLoop(images, Critic(text), VisualDirector(text))
    return loop.run(spec, PLAN, SHOT, "Matt waits.", tmp_path, budget), text, images


def test_accepted_first_try_uses_approved_reference(tmp_path: Path) -> None:
    result, text, images = run(tmp_path, [APPROVED])

    assert result.accepted and result.stop_reason is PanelStop.ACCEPTED
    assert Path(result.attempts[0].image).exists()
    assert images.requests[0].references[0].image_url.startswith("data:image/png;base64,")
    assert "red coat" in images.requests[0].prompt
    assert len(text.requests[0].images) == 2


def test_rendering_failure_retries_generation_with_repair(tmp_path: Path) -> None:
    result, text, images = run(tmp_path, [rejected(), APPROVED])

    assert result.accepted and len(result.attempts) == 2
    assert "Must fix: Center him." in images.requests[1].prompt
    assert len(text.requests) == 2  # no Visual Director call


def test_script_mismatch_goes_to_director_once(tmp_path: Path) -> None:
    new_shot = SHOT.model_copy(update={"framing": "close-up", "characters": ["Zoe"]}).model_dump_json()
    result, text, _ = run(tmp_path, [rejected("SCRIPT_MISMATCH"), new_shot, rejected("MISSING_CHARACTER"), APPROVED])

    assert result.shot.framing == "close-up"
    assert result.shot.characters == ["Matt"]  # the director cannot change who is visible
    assert len(text.requests) == 4
    assert result.accepted


def test_stops_at_max_attempts_and_best_score_wins(tmp_path: Path) -> None:
    result, _, _ = run(
        tmp_path, [rejected("COMPOSITION", 0.3), rejected("STYLE_DRIFT", 0.8), rejected("ARTIFACT", 0.5), "unused"]
    )
    assert result.stop_reason is PanelStop.ATTEMPTS_EXHAUSTED and not result.accepted
    panel = PanelResult(panel_id="p", page=1, index=1, description="d", attempts=result.attempts)
    assert panel.best_image == result.attempts[1].image


def test_repeated_failure_stops_early(tmp_path: Path) -> None:
    result, _, _ = run(tmp_path, [rejected(), rejected(), "unused"])
    assert result.stop_reason is PanelStop.REPEATED_FAILURE and len(result.attempts) == 2


def test_budget_stops_retries(tmp_path: Path) -> None:
    result, _, images = run(tmp_path, [rejected(), "unused"], budget=0.0)
    assert result.stop_reason is PanelStop.BUDGET_EXHAUSTED and len(images.requests) == 1


def test_image_failure_is_reported_not_accepted(tmp_path: Path) -> None:
    images = FakeImageModel(errors=[ModelError(ModelErrorKind.QUOTA, "no credits", "meta")])
    result, _, _ = run(tmp_path, [], images=images)
    assert result.stop_reason is PanelStop.ERROR and "no credits" in result.error
    assert not result.accepted


def test_simulated_attempts_have_no_image() -> None:
    panel = PanelResult(
        panel_id="p", page=1, index=1, description="d", attempts=[PanelAttempt(attempt=1, accepted=True)]
    )
    assert panel.best_image == ""
