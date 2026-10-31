"""Chapter Judge verdicts and the acceptance boundary for canon."""

import json
from pathlib import Path

import pytest
from PIL import Image

from comartist.adapters.fake import FakeTextModel
from comartist.agents.chapter_judge import ChapterJudge, ChapterJudgeError
from comartist.models import (
    ChapterRun,
    ChapterSpec,
    ChapterVerdict,
    PageBeat,
    PanelAttempt,
    PanelResult,
    RunState,
    Scene,
    Script,
    ScriptPanel,
    StoryOutline,
)
from comartist.tools.canon import AcceptanceError, CanonStore, accept_chapter, blockers, proposed_facts

SPEC = ChapterSpec(title="T", premise="p", characters=["Matt"], timeframe="2024", canon=["Andy moved in 2020."])
SCRIPT = Script(
    scenes=[Scene(location="Roof", panels=[ScriptPanel(page=1, index=1, action="a")])],
    proposed_facts=["Matt sold his bike."],
)
APPROVED = ChapterVerdict(approved=True, score=0.9, summary="Good.")


def good_run(**changes: object) -> ChapterRun:
    run = ChapterRun(
        chapter_id="c",
        spec=SPEC,
        state=RunState.DONE,
        script=SCRIPT,
        verdict=APPROVED,
        outline=StoryOutline(
            logline="x", beats=[PageBeat(page=1, summary="s", characters=["Matt"])],
            proposed_facts=["They grew up together."],
        ),
        panels=[
            PanelResult(
                panel_id="p1-1", page=1, index=1, description="d",
                attempts=[PanelAttempt(attempt=1, accepted=True)],
            )
        ],
    )
    return run.model_copy(update=changes)


def page(tmp_path: Path) -> str:
    path = tmp_path / "page.png"
    Image.new("RGB", (2000, 3000)).save(path)
    return str(path)


def test_judge_sees_pages_and_canon(tmp_path: Path) -> None:
    model = FakeTextModel([APPROVED.model_dump_json()])
    result = ChapterJudge(model).judge(SPEC, SCRIPT, [page(tmp_path)])
    assert result.verdict.approved
    assert "Andy moved in 2020." in model.requests[0].messages[1].content
    assert model.requests[0].images[0].startswith("data:image/jpeg")


def test_rejection_without_issues_is_repaired_then_fails(tmp_path: Path) -> None:
    bad = json.dumps({"approved": False, "score": 0.2, "summary": "No."})
    with pytest.raises(ChapterJudgeError):
        ChapterJudge(FakeTextModel([bad, bad])).judge(SPEC, SCRIPT, [page(tmp_path)])


def test_only_selected_facts_reach_canon(tmp_path: Path) -> None:
    canon = CanonStore(tmp_path / "canon.json")
    run = good_run()
    accept_chapter(canon, run, ["Matt sold his bike."])

    assert run.accepted
    assert [fact.text for fact in canon.facts()] == ["Matt sold his bike."]
    assert canon.facts()[0].chapter_id == "c" and canon.facts()[0].story_time == "2024"


def test_nothing_reaches_canon_before_acceptance(tmp_path: Path) -> None:
    canon = CanonStore(tmp_path / "canon.json")
    assert proposed_facts(good_run()) == ["They grew up together.", "Matt sold his bike."]
    assert canon.facts() == []


def test_repeat_acceptance_does_not_duplicate(tmp_path: Path) -> None:
    canon = CanonStore(tmp_path / "canon.json")
    accept_chapter(canon, good_run(), ["Matt sold his bike."])
    assert accept_chapter(canon, good_run(), ["Matt sold his bike."]) == []
    assert len(canon.facts()) == 1


def test_invented_fact_cannot_be_committed(tmp_path: Path) -> None:
    with pytest.raises(AcceptanceError, match="Not proposed"):
        accept_chapter(CanonStore(tmp_path / "canon.json"), good_run(), ["Matt can fly."])


@pytest.mark.parametrize(
    "changes",
    [
        {"state": RunState.FAILED},
        {"verdict": None},
        {"verdict": ChapterVerdict(approved=False, score=0.2, summary="No.", issues=[
            {"category": "PACING", "evidence": "e", "repair": "r"}])},
    ],
)
def test_blocked_runs_cannot_be_accepted(tmp_path: Path, changes: dict) -> None:
    canon = CanonStore(tmp_path / "canon.json")
    with pytest.raises(AcceptanceError):
        accept_chapter(canon, good_run(**changes), [])
    assert canon.facts() == []


def test_unaccepted_panel_blocks_acceptance() -> None:
    panel = PanelResult(panel_id="p1-1", page=1, index=1, description="d",
                        attempts=[PanelAttempt(attempt=1, accepted=False, failure="ARTIFACT")])
    assert any("p1-1" in p for p in blockers(good_run(panels=[panel])))
