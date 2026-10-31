"""Chapter Judge output and the canon facts an accepted chapter may add."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class ChapterFailure(StrEnum):
    PACING = "PACING"
    READABILITY = "READABILITY"
    CONTINUITY = "CONTINUITY"
    CANON_VIOLATION = "CANON_VIOLATION"
    COHERENCE = "COHERENCE"


class ChapterIssue(BaseModel):
    category: ChapterFailure
    page: int | None = Field(default=None, ge=1, description="Empty for chapter-wide issues.")
    evidence: str = Field(min_length=1)
    repair: str = Field(min_length=1)


class ChapterVerdict(BaseModel):
    """`score` is an uncalibrated estimate, not a measured probability."""

    approved: bool
    score: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    issues: list[ChapterIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def rejection_needs_issues(self) -> Self:
        if not self.approved and not self.issues:
            raise ValueError("A rejected chapter must list at least one issue")
        return self


class CanonFact(BaseModel):
    """A fact committed by an explicit acceptance, with its provenance."""

    text: str = Field(min_length=1)
    chapter_id: str = Field(min_length=1)
    story_time: str = ""
    source: str = "accepted chapter"
