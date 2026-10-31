"""Two-chapter continuity: carry-over of canon and looks, outfit changes, and the eval checks."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from comartist.memory.continuity import carry_over
from comartist.models import (
    ChapterRun,
    ChapterSpec,
    ChapterVerdict,
    CharacterLook,
    DialogueLine,
    Scene,
    Script,
    ScriptPanel,
)
from comartist.models.verdict import CanonFact
from comartist.tools.continuity_check import ContinuityExpectations, check_continuity
from comartist.workflows.store import RunStore, parse_brief

EVALS = Path(__file__).resolve().parent.parent / "evals" / "continuity"
MATT = CharacterLook(name="Matt", appearance="short, mole on left cheek", outfit="teal t-shirt")
ANDY = CharacterLook(name="Andy", appearance="tall, freckles", outfit="striped shirt")
START = datetime(2026, 1, 1, tzinfo=UTC)


def chapter(chapter_id: str, *, accepted: bool = True, day: int = 0, lines: tuple[str, ...] = ("Hey.",), **spec) -> ChapterRun:
    fields = {"title": chapter_id, "premise": "p", "characters": ["Matt", "Andy"], "location": "New York City"}
    panel = ScriptPanel(
        page=1, index=1, action="a", characters=["Matt", "Andy"],
        dialogue=[DialogueLine(speaker="Andy", text=text) for text in lines],
    )
    return ChapterRun(
        chapter_id=chapter_id,
        spec=ChapterSpec(**{**fields, **spec}),
        script=Script(scenes=[Scene(location="NYU", panels=[panel])]),
        verdict=ChapterVerdict(approved=True, score=0.9, summary="Good."),
        accepted=accepted,
        created=START + timedelta(days=day),
    )


def first_chapter() -> ChapterRun:
    return chapter(
        "ch1", timeframe="Summer 2024", canon=["They have not met since middle school."],
        locked_looks=[MATT, ANDY], references={"Matt": "matt.png", "Andy": "andy.png"},
    )


def test_only_accepted_chapters_carry_over() -> None:
    carry = carry_over([first_chapter(), chapter("draft", accepted=False, canon=["Matt can fly."])], [])
    assert carry.sources == ["ch1"]
    assert carry.canon == ["As of Summer 2024: They have not met since middle school."]
    assert carry.references == {"Matt": "matt.png", "Andy": "andy.png"}


def test_committed_facts_carry_with_their_story_time() -> None:
    fact = CanonFact(text="Matt sold his bike.", chapter_id="ch1", story_time="Summer 2024")
    stray = CanonFact(text="From a chapter that is gone.", chapter_id="gone")
    assert "As of Summer 2024: Matt sold his bike." in carry_over([first_chapter()], [fact, stray]).canon
    assert all("gone" not in text for text in carry_over([first_chapter()], [fact, stray]).canon)


def test_carried_facts_are_not_dated_twice() -> None:
    second = chapter("ch2", day=1, timeframe="August 2024", canon=["As of Summer 2024: They met at NYU."])
    assert carry_over([second], []).canon == ["As of Summer 2024: They met at NYU."]


def test_new_chapter_keeps_faces_and_changes_only_the_outfit(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    brief = "title: Ch2\ncharacters: [Matt]\npremise: p\ncanon: [Andy has a secret.]\noutfits:\n  matt: navy blazer\n"
    run = store.create(brief, carry_over([first_chapter()], []))

    looks = {look.name: look for look in run.spec.looks()}
    assert looks["Matt"].appearance == MATT.appearance and looks["Matt"].outfit == "navy blazer"
    assert looks["Andy"] == ANDY
    assert run.spec.references["Matt"] == "matt.png"
    assert run.spec.canon == ["As of Summer 2024: They have not met since middle school.", "Andy has a secret."]
    assert "Carried over from ch1" in run.log[0]
    assert "outfits" in (tmp_path / run.chapter_id / "brief.yaml").read_text()  # what the person wrote


def test_brief_without_carry_over_starts_fresh(tmp_path: Path) -> None:
    run = RunStore(tmp_path).create("title: Ch2\ncharacters: [Matt]\npremise: p\n")
    assert run.spec.locked_looks == [] and run.spec.canon == [] and run.log == []


def test_brief_looks_override_carried_ones(tmp_path: Path) -> None:
    other = CharacterLook(name="matt", appearance="grew a beard", outfit="coat")
    spec = ChapterSpec(title="t", premise="p", characters=["Matt"], locked_looks=[other], references={"MATT": "new.png"})
    merged = carry_over([first_chapter()], []).apply(spec)
    assert [look.appearance for look in merged.locked_looks if look.name.casefold() == "matt"] == ["grew a beard"]
    assert merged.references == {"Andy": "andy.png", "MATT": "new.png"}


def expectations() -> ContinuityExpectations:
    return ContinuityExpectations.model_validate(yaml.safe_load((EVALS / "expectations.yaml").read_text()))


def second_chapter(**changes) -> ChapterRun:
    carry = carry_over([first_chapter()], [])
    spec = carry.apply(ChapterSpec(
        title="ch2", premise="p", characters=["Matt", "Andy"], location="New York City",
        outfits={"Matt": "navy blazer", "Andy": "bomber jacket"},
    ))
    return chapter("ch2", day=1).model_copy(update={"spec": spec, **changes})


def test_eval_passes_when_continuity_holds() -> None:
    failed = [c for c in check_continuity(first_chapter(), second_chapter(), expectations()) if not c.passed]
    assert failed == []


def test_eval_catches_a_leaked_secret_and_ignores_lookalikes() -> None:
    leaky = chapter("ch2", day=1, lines=("I took a job in los angeles.",))
    fine = chapter("ch2", day=1, lines=("La la la, the view is great.",))
    leaks = [c for c in check_continuity(first_chapter(), leaky, expectations()) if "secret" in c.name]
    clean = [c for c in check_continuity(first_chapter(), fine, expectations()) if "secret" in c.name]
    assert not leaks[0].passed and "ch2 p1-1" in leaks[0].evidence
    assert clean[0].passed


def test_eval_fails_a_second_chapter_that_forgot_the_looks() -> None:
    fresh = chapter("ch2", day=1)  # what chapter 2 looked like before carry-over existed
    failed = {c.name for c in check_continuity(first_chapter(), fresh, expectations()) if not c.passed}
    assert {"Matt keeps the same appearance", "Andy keeps the same reference image", "Matt changes outfit"} <= failed


def test_eval_fails_when_outfit_is_unchanged_or_chapter_unaccepted() -> None:
    same = second_chapter(accepted=False)
    same.spec.outfits = {}
    failed = {c.name for c in check_continuity(first_chapter(), same, expectations()) if not c.passed}
    assert {"Matt changes outfit", "Andy changes outfit", "ch2 accepted"} <= failed


def test_eval_briefs_are_valid_and_change_outfits() -> None:
    first = parse_brief((EVALS / "chapter-1.yaml").read_text())
    second = parse_brief((EVALS / "chapter-2.yaml").read_text())
    assert first.location == second.location == expectations().location
    assert set(second.outfits) == set(expectations().outfit_changes)
