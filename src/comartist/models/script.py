"""Script Writer output: scenes of panels with dialogue, captions, and transitions."""

from pydantic import BaseModel, Field


class DialogueLine(BaseModel):
    speaker: str = Field(min_length=1, description="A name from the brief.")
    text: str = Field(min_length=1)


class ScriptPanel(BaseModel):
    page: int = Field(ge=1)
    index: int = Field(ge=1, description="Position on its page.")
    action: str = Field(min_length=1, description="What is visibly happening.")
    characters: list[str] = Field(default_factory=list, description="Who is visible.")
    dialogue: list[DialogueLine] = Field(default_factory=list)
    caption: str = ""
    transition: str = Field(default="", description="How the reader moves from the previous panel.")

    @property
    def panel_id(self) -> str:
        return f"p{self.page}-{self.index}"


class Scene(BaseModel):
    location: str = Field(min_length=1)
    summary: str = ""
    panels: list[ScriptPanel] = Field(min_length=1)


class Script(BaseModel):
    """A candidate script. Nothing here is canon until a chapter is accepted."""

    scenes: list[Scene] = Field(min_length=1)
    proposed_facts: list[str] = Field(
        default_factory=list,
        description="Lasting facts the script invents; candidates for canon, never auto-committed.",
    )

    @property
    def panels(self) -> list[ScriptPanel]:
        return [panel for scene in self.scenes for panel in scene.panels]
