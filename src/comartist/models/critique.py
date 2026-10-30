"""Critic output for scripts: structured failures with evidence and a suggested repair."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class ScriptFailure(StrEnum):
    CANON_VIOLATION = "CANON_VIOLATION"
    KNOWLEDGE_LEAK = "KNOWLEDGE_LEAK"
    OUTLINE_MISMATCH = "OUTLINE_MISMATCH"
    CHARACTER_VOICE = "CHARACTER_VOICE"
    PACING = "PACING"
    CLARITY = "CLARITY"


class PanelFailure(StrEnum):
    STYLE_DRIFT = "STYLE_DRIFT"
    COMPOSITION = "COMPOSITION"
    POSE_MISMATCH = "POSE_MISMATCH"
    WRONG_OUTFIT = "WRONG_OUTFIT"
    IDENTITY_DRIFT = "IDENTITY_DRIFT"
    UNWANTED_TEXT = "UNWANTED_TEXT"
    ARTIFACT = "ARTIFACT"
    MISSING_CHARACTER = "MISSING_CHARACTER"
    SCRIPT_MISMATCH = "SCRIPT_MISMATCH"


# These mean the shot itself is wrong, so the Visual Director repairs them, not a re-render.
REDIRECT_FAILURES = {PanelFailure.MISSING_CHARACTER, PanelFailure.SCRIPT_MISMATCH}


class PanelIssue(BaseModel):
    category: PanelFailure
    evidence: str = Field(min_length=1)
    repair: str = Field(min_length=1)


class PanelCritique(BaseModel):
    """`score` is an uncalibrated estimate, used only to rank attempts at one panel."""

    approved: bool
    score: float = Field(ge=0, le=1)
    issues: list[PanelIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def rejection_needs_issues(self) -> Self:
        if not self.approved and not self.issues:
            raise ValueError("A rejected panel must list at least one issue")
        return self

    @property
    def signature(self) -> frozenset[PanelFailure]:
        return frozenset(issue.category for issue in self.issues)


class ScriptIssue(BaseModel):
    category: ScriptFailure
    panel_id: str = Field(default="", description="e.g. p2-3; empty for chapter-wide issues.")
    evidence: str = Field(min_length=1, description="What in the script shows the failure.")
    repair: str = Field(min_length=1, description="The specific change that would fix it.")


class ScriptCritique(BaseModel):
    """`score` is an uncalibrated estimate, used only to rank drafts of one chapter."""

    approved: bool
    score: float = Field(ge=0, le=1)
    issues: list[ScriptIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def rejection_needs_issues(self) -> Self:
        if not self.approved and not self.issues:
            raise ValueError("A rejected script must list at least one issue")
        return self

    @property
    def signature(self) -> frozenset[tuple[ScriptFailure, str]]:
        """Identifies the failures, so a loop can stop when a revision repeats them."""
        return frozenset((issue.category, issue.panel_id) for issue in self.issues)
