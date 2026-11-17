"""Contract every CanonRepository implementation must meet."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from comartist.tools.canon import CanonRepository, CanonStore, InMemoryCanonStore

Factory = Callable[[Path], CanonRepository]
FACTORIES: dict[str, Factory] = {
    "json": lambda tmp: CanonStore(tmp / "canon.json"),
    "memory": lambda tmp: InMemoryCanonStore(),
}


@pytest.fixture(params=list(FACTORIES))
def canon(request: pytest.FixtureRequest, tmp_path: Path) -> CanonRepository:
    return FACTORIES[request.param](tmp_path)


def test_starts_empty(canon: CanonRepository) -> None:
    assert canon.facts() == []


def test_commit_records_provenance(canon: CanonRepository) -> None:
    added = canon.commit("c1", "2024", ["Matt sold his bike."])
    assert [(f.text, f.chapter_id, f.story_time) for f in added] == [("Matt sold his bike.", "c1", "2024")]
    assert canon.facts() == added


def test_repeat_commit_adds_nothing(canon: CanonRepository) -> None:
    canon.commit("c1", "2024", ["A.", "B."])
    assert canon.commit("c1", "2024", ["B.", "A."]) == []
    assert [f.text for f in canon.facts()] == ["A.", "B."]


def test_duplicates_in_one_commit_collapse(canon: CanonRepository) -> None:
    assert [f.text for f in canon.commit("c1", "2024", ["A.", "A."])] == ["A."]


def test_same_text_in_another_chapter_is_kept(canon: CanonRepository) -> None:
    canon.commit("c1", "2024", ["A."])
    canon.commit("c2", "2025", ["A."])
    assert [(f.chapter_id, f.story_time) for f in canon.facts()] == [("c1", "2024"), ("c2", "2025")]


def test_empty_commit_adds_nothing(canon: CanonRepository) -> None:
    assert canon.commit("c1", "2024", []) == []
    assert canon.facts() == []


def test_returned_facts_cannot_change_canon(canon: CanonRepository) -> None:
    canon.commit("c1", "2024", ["A."])
    facts = canon.facts()
    facts.clear()
    assert len(canon.facts()) == 1


def test_json_store_persists_across_instances(tmp_path: Path) -> None:
    CanonStore(tmp_path / "canon.json").commit("c1", "2024", ["A."])
    assert [f.text for f in CanonStore(tmp_path / "canon.json").facts()] == ["A."]


def test_commit_records_story_date(canon: CanonRepository) -> None:
    canon.commit("c1", "Summer 2024", ["A."], date(2024, 7, 1))
    assert canon.facts()[0].holds_from == date(2024, 7, 1)
