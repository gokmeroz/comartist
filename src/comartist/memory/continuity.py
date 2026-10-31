"""Carry accepted canon and approved looks from earlier chapters into a new one.

Only accepted chapters count. Facts keep the story time they held at, so a fact that was
true before a later chapter ("they have not met since school") reads as history, not a rule.
"""

from pydantic import BaseModel, Field

from comartist.models import ChapterRun, ChapterSpec
from comartist.models.verdict import CanonFact
from comartist.models.visual import CharacterLook


class CarryOver(BaseModel):
    sources: list[str] = Field(default_factory=list, description="Accepted chapter IDs, oldest first.")
    canon: list[str] = Field(default_factory=list)
    references: dict[str, str] = Field(default_factory=dict)
    locked_looks: list[CharacterLook] = Field(default_factory=list)

    def apply(self, spec: ChapterSpec) -> ChapterSpec:
        """The brief wins: its own looks and references replace carried ones; carried canon comes first."""
        own_looks = {look.name.casefold() for look in spec.locked_looks}
        own_refs = {name.casefold() for name in spec.references}
        looks = [look for look in self.locked_looks if look.name.casefold() not in own_looks]
        references = {name: path for name, path in self.references.items() if name.casefold() not in own_refs}
        return spec.model_copy(
            update={
                "canon": list(dict.fromkeys([*self.canon, *spec.canon])),
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
    canon: list[str] = []
    looks: dict[str, CharacterLook] = {}
    references: dict[str, str] = {}
    for run in accepted:
        canon += [_dated(text, run.spec.timeframe) for text in run.spec.canon]
        canon += [_dated(fact.text, fact.story_time) for fact in facts if fact.chapter_id == run.chapter_id]
        for look in run.spec.looks():
            looks[look.name.casefold()] = look
        for name, path in run.spec.references.items():
            references = {key: value for key, value in references.items() if key.casefold() != name.casefold()}
            references[name] = path
    return CarryOver(
        sources=[run.chapter_id for run in accepted],
        canon=list(dict.fromkeys(canon)),
        references=references,
        locked_looks=list(looks.values()),
    )
