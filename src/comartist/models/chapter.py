"""User intent for a comic chapter."""

from pydantic import BaseModel, Field


class ChapterBrief(BaseModel):
    """A premise with explicit boundaries for creative execution."""

    premise: str = Field(min_length=1)
    hard_constraints: list[str] = Field(
        default_factory=list, description="Requirements that must be respected."
    )
    soft_preferences: list[str] = Field(
        default_factory=list, description="Desired qualities that may be balanced."
    )
    creative_freedom: list[str] = Field(
        default_factory=list, description="Areas the system is free to invent."
    )
