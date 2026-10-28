"""Story Architect output: the chapter's dramatic structure, one beat per page."""

from pydantic import BaseModel, Field


class PageBeat(BaseModel):
    """What one page must accomplish dramatically."""

    page: int = Field(ge=1)
    summary: str = Field(min_length=1, description="What happens on this page.")
    characters: list[str] = Field(min_length=1, description="Names from the brief only.")
    location: str = ""
    emotion: str = Field(default="", description="The emotional note readers should feel.")
    turn: str = Field(default="", description="What changes by the end of the page.")


class StoryOutline(BaseModel):
    """A candidate structure. Nothing here is canon until a chapter is accepted."""

    logline: str = Field(min_length=1)
    beats: list[PageBeat] = Field(min_length=1)
    proposed_facts: list[str] = Field(
        default_factory=list,
        description="Lasting facts the outline invents; candidates for canon, never auto-committed.",
    )
