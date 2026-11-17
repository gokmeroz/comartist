"""Carry accepted canon and approved looks from earlier chapters into a new one.

Only accepted chapters count. Facts keep the story time they held at, so a fact that was
true before a later chapter ("they have not met since school") reads as history, not a rule.
"""

from datetime import date

from pydantic import BaseModel, Field

from comartist.models import ChapterRun, ChapterSpec
from comartist.models.verdict import CanonFact
from comartist.models.visual import CharacterLook


class CarriedFact(BaseModel):
    text: str
    holds_from: date | None = None


class CarryOver(BaseModel):
    sources: list[str] = Field(default_factory=list, description="Accepted chapter IDs, oldest first.")
    facts: list[CarriedFact] = Field(default_factory=list)
    references: dict[str, str] = Field(default_factory=dict)
    locked_looks: list[CharacterLook] = Field(default_factory=list)

    @property
    def canon(self) -> list[str]:
        return [fact.text for fact in self.facts]

    def visible(self, at: date | None) -> list[str]:
        """Facts a chapter set at `at` may know. Facts that start later are left out; undated ones pass."""
        if at is None:
            return self.canon
        return [fact.text for fact in self.facts if fact.holds_from is None or fact.holds_from <= at]

    def time_notes(self, at: date | None) -> list[str]:
        """Run-log lines that say which carried facts could not be time-checked or were left out."""
        if not self.facts:
            return []
        if at is None:
            return [f"No story_date on this chapter: {len(self.facts)} carried facts were not time-checked."]
        notes = []
        if later := sum(1 for fact in self.facts if fact.holds_from and fact.holds_from > at):
            notes.append(f"Left out {later} carried facts that only hold after {at.isoformat()}.")
        if undated := sum(1 for fact in self.facts if fact.holds_from is None):
            notes.append(f"{undated} undated carried facts could not be time-checked.")
        return notes

    def apply(self, spec: ChapterSpec) -> ChapterSpec:
        """The brief wins: its own looks and references replace carried ones; carried canon comes first.

        Only carried facts are filtered by story time; the brief's own canon is always kept.
        """
        own_looks = {look.name.casefold() for look in spec.locked_looks}
        own_refs = {name.casefold() for name in spec.references}
        looks = [look for look in self.locked_looks if look.name.casefold() not in own_looks]
        references = {name: path for name, path in self.references.items() if name.casefold() not in own_refs}
        return spec.model_copy(
            update={
                "canon": list(dict.fromkeys([*self.visible(spec.story_date), *spec.canon])),
                "locked_looks": [*looks, *spec.locked_looks],
                "references": {**references, **spec.references},
            }
        )


def _dated(text: str, story_time: str) -> str:
    if not story_time or text.startswith("As of "):  # already dated by an earlier carry-over
        return text
    return f"As of {story_time}: {text}"


def carry_over(runs: list[ChapterRun], facts: list[CanonFact]) -> CarryOver:
    """A later chapter's look for a character replaces an earlier one."""
    accepted = sorted((run for run in runs if run.accepted), key=lambda run: run.created)
    carried: dict[str, CarriedFact] = {}
    looks: dict[str, CharacterLook] = {}
    references: dict[str, str] = {}
    for run in accepted:
        dated = [(_dated(text, run.spec.timeframe), run.spec.story_date) for text in run.spec.canon]
        dated += [
            (_dated(fact.text, fact.story_time), fact.holds_from or run.spec.story_date)
            for fact in facts
            if fact.chapter_id == run.chapter_id
        ]
        for text, holds_from in dated:
            carried.setdefault(text, CarriedFact(text=text, holds_from=holds_from))
        for look in run.spec.looks():
            looks[look.name.casefold()] = look
        for name, path in run.spec.references.items():
            references = {key: value for key, value in references.items() if key.casefold() != name.casefold()}
            references[name] = path
    return CarryOver(
        sources=[run.chapter_id for run in accepted],
        facts=list(carried.values()),
        references=references,
        locked_looks=list(looks.values()),
    )
