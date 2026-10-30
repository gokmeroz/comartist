"""Visual Director output: a locked look per character and a shot spec per panel."""

from pydantic import BaseModel, Field


class CharacterLook(BaseModel):
    """Repeated verbatim in image prompts so a character stays recognisable across panels."""

    name: str = Field(min_length=1)
    appearance: str = Field(min_length=1, description="Face, hair, build, age.")
    outfit: str = Field(min_length=1)


class PanelSpec(BaseModel):
    panel_id: str = Field(min_length=1, description="The script panel this directs, e.g. p2-3.")
    framing: str = Field(min_length=1, description="Shot size and camera angle.")
    composition: str = Field(min_length=1, description="Where subjects sit in the frame.")
    poses: str = Field(min_length=1, description="Pose and expression of each visible character.")
    lighting: str = Field(min_length=1)
    setting: str = Field(min_length=1, description="Visible environment.")
    characters: list[str] = Field(default_factory=list, description="Who is visible.")
    references: list[str] = Field(
        default_factory=list,
        description="Characters with an approved reference. Set from the brief, never by the model.",
    )


class VisualPlan(BaseModel):
    """A candidate plan. Nothing here is canon until a chapter is accepted."""

    style: str = Field(min_length=1, description="One art style for the whole chapter.")
    looks: list[CharacterLook] = Field(min_length=1)
    panels: list[PanelSpec] = Field(min_length=1)
