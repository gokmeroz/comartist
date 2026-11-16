"""The acceptance boundary. Canon only changes here, after an explicit human decision."""

import threading
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from comartist.models import ChapterRun, RunState
from comartist.models.verdict import CanonFact


class AcceptanceError(Exception):
    pass


class CanonRepository(Protocol):
    """Accepted canon. Implementations must make `commit` idempotent per (chapter, text)."""

    def facts(self) -> list[CanonFact]: ...

    def commit(self, chapter_id: str, story_time: str, texts: list[str]) -> list[CanonFact]: ...


def _new_facts(existing: list[CanonFact], chapter_id: str, story_time: str, texts: list[str]) -> list[CanonFact]:
    known = {(fact.chapter_id, fact.text) for fact in existing}
    return [
        CanonFact(text=text, chapter_id=chapter_id, story_time=story_time)
        for text in dict.fromkeys(texts)
        if (chapter_id, text) not in known
    ]


class InMemoryCanonStore:
    """Canon held in memory, for tests and offline runs."""

    def __init__(self, facts: list[CanonFact] | None = None) -> None:
        self._facts = list(facts or [])
        self._lock = threading.Lock()

    def facts(self) -> list[CanonFact]:
        with self._lock:
            return [fact.model_copy() for fact in self._facts]

    def commit(self, chapter_id: str, story_time: str, texts: list[str]) -> list[CanonFact]:
        """Add facts once. Repeating a commit adds nothing."""
        with self._lock:
            added = _new_facts(self._facts, chapter_id, story_time, texts)
            self._facts += added
            return added


class _Ledger(BaseModel):
    facts: list[CanonFact] = Field(default_factory=list)


class CanonStore:
    """Accepted facts in one JSON file. A stand-in for PostgreSQL behind `CanonRepository`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def facts(self) -> list[CanonFact]:
        if not self._path.exists():
            return []
        return _Ledger.model_validate_json(self._path.read_text()).facts

    def commit(self, chapter_id: str, story_time: str, texts: list[str]) -> list[CanonFact]:
        """Add facts once. Repeating a commit adds nothing."""
        with self._lock:
            facts = self.facts()
            added = _new_facts(facts, chapter_id, story_time, texts)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(_Ledger(facts=[*facts, *added]).model_dump_json(indent=2))
            return added


def blockers(run: ChapterRun) -> list[str]:
    """Why a run cannot be accepted. Empty means a person may accept it."""
    problems = []
    if run.state is not RunState.DONE:
        problems.append(f"Run is {run.state}")
    if run.verdict is None:
        problems.append("No Chapter Judge verdict")
    elif not run.verdict.approved:
        problems.append("Chapter Judge did not approve")
    rejected = [panel.panel_id for panel in run.panels if not panel.accepted]
    if rejected:
        problems.append(f"Panels not accepted: {', '.join(rejected)}")
    return problems


def proposed_facts(run: ChapterRun) -> list[str]:
    outline = run.outline.proposed_facts if run.outline else []
    script = run.script.proposed_facts if run.script else []
    return list(dict.fromkeys([*outline, *script]))


def accept_chapter(canon: CanonRepository, run: ChapterRun, approved_facts: list[str]) -> list[CanonFact]:
    """Mark the run accepted and commit only the facts the person selected."""
    problems = blockers(run)
    if problems:
        raise AcceptanceError("; ".join(problems))
    offered = proposed_facts(run)
    unknown = [fact for fact in approved_facts if fact not in offered]
    if unknown:
        raise AcceptanceError(f"Not proposed by this run: {', '.join(unknown)}")
    added = canon.commit(run.chapter_id, run.spec.timeframe, approved_facts)
    run.accepted = True
    run.log.append(f"Accepted by user; {len(added)} facts committed to canon.")
    return added
