"""Initial chapter workflow state."""

from pydantic import BaseModel, Field

from comartist.models.chapter import ChapterBrief
from comartist.models.character import Character


class ComicState(BaseModel):
    """Chapter inputs and draft artifacts, before orchestration exists."""

    chapter_brief: ChapterBrief
    characters: list[Character] = Field(default_factory=list)
    story_outline: str = ""
    script: str = ""
    revision_count: int = Field(default=0, ge=0)
