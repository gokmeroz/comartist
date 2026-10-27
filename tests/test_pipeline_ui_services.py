"""Brief parsing, run storage, and the stub pipeline behind the UI."""

from pathlib import Path

import pytest

from comartist.models import Cost, RunSettings, RunState, Stage, StageState
from comartist.workflows.store import BriefError, RunStore, chapter_template, parse_brief
from comartist.workflows.stub_pipeline import run_stub_pipeline

SETTINGS = RunSettings(provider="stub", text_model="stub-text", image_model="stub-image")


def test_template_is_a_valid_brief() -> None:
    spec = parse_brief(chapter_template())
    assert spec.characters == ["Matt", "Andy"]
    assert spec.target_pages == 4


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("title: [unclosed", "Invalid YAML"),
        ("- just a list", "mapping"),
        ("title: X\npremise: Y\ncharacters: []", "characters"),
        ("title: X\ncharacters: [A]", "premise"),
    ],
)
def test_bad_briefs_are_rejected(text: str, message: str) -> None:
    with pytest.raises(BriefError, match=message):
        parse_brief(text)


def test_store_keeps_brief_and_avoids_id_collisions(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    first = store.create(chapter_template())
    second = store.create(chapter_template())

    assert first.chapter_id == "chapter-1-the-reunion"
    assert second.chapter_id == "chapter-1-the-reunion-2"
    assert (tmp_path / first.chapter_id / "brief.yaml").read_text() == chapter_template()
    assert [run.chapter_id for run in store.list()] == [first.chapter_id, second.chapter_id]


def test_stub_run_completes_every_stage_with_bounded_attempts(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    chapter_id = store.create(chapter_template()).chapter_id
    settings = SETTINGS.model_copy(update={"max_panel_attempts": 1})

    run = run_stub_pipeline(store, chapter_id, settings, sleep=lambda _: None)

    assert run.state is RunState.DONE
    assert all(status.state is StageState.DONE for status in run.stages.values())
    panels = run.spec.target_pages * 4
    assert run.stages[Stage.PANELS].attempts == panels
    assert run.cost.usd == 0.0
    assert run.cost.total_tokens > 0
    assert store.load(chapter_id).state is RunState.DONE


def test_unknown_price_makes_total_usd_unknown() -> None:
    total = Cost(prompt_tokens=10, usd=0.5).add(Cost(completion_tokens=5, usd=None))
    assert total.total_tokens == 15
    assert total.usd is None


def test_stub_run_records_panel_attempts_and_exhaustion(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    chapter_id = store.create(chapter_template()).chapter_id

    full = run_stub_pipeline(store, chapter_id, SETTINGS, sleep=lambda _: None)
    assert len(full.panels) == 16
    assert all(panel.accepted for panel in full.panels)
    retried = [panel for panel in full.panels if len(panel.attempts) > 1]
    assert retried and all(not attempt.accepted for attempt in retried[0].attempts[:-1])

    capped = run_stub_pipeline(
        store, chapter_id, SETTINGS.model_copy(update={"max_panel_attempts": 1}), sleep=lambda _: None
    )
    assert all(len(panel.attempts) == 1 for panel in capped.panels)
    assert not all(panel.accepted for panel in capped.panels)
