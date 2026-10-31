"""Chapter spec, pipeline run status, and cost accounting."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from comartist.models.critique import ScriptCritique
from comartist.models.script import Script
from comartist.models.story import StoryOutline
from comartist.models.verdict import ChapterVerdict
from comartist.models.visual import CharacterLook, VisualPlan


class ChapterSpec(BaseModel):
    """A new chapter request, as filled in from the YAML template."""

    title: str = Field(min_length=1)
    timeframe: str = ""
    location: str = ""
    characters: list[str] = Field(min_length=1)
    canon: list[str] = Field(default_factory=list, description="Facts agents must not change.")
    premise: str = Field(min_length=1)
    tone: list[str] = Field(default_factory=list)
    target_pages: int = Field(default=4, ge=1, le=40)
    references: dict[str, str] = Field(
        default_factory=dict,
        description="Character name -> approved reference image (file path or URL).",
    )
    art_style: str = Field(default="", description="Overrides the default comic style.")
    locked_looks: list[CharacterLook] = Field(
        default_factory=list, description="Looks approved with a reference; visual plans keep them."
    )
    outfits: dict[str, str] = Field(
        default_factory=dict,
        description="Character name -> this chapter's outfit. Overrides a locked look's outfit only.",
    )

    def looks(self) -> list[CharacterLook]:
        """Locked looks with this chapter's outfits applied; appearance never changes here."""
        outfits = {name.casefold(): outfit for name, outfit in self.outfits.items()}
        return [
            look.model_copy(update={"outfit": outfits[look.name.casefold()]})
            if look.name.casefold() in outfits
            else look
            for look in self.locked_looks
        ]


class Stage(StrEnum):
    STORY_ARCHITECT = "Story Architect"
    SCRIPT = "Script ⇄ Critic"
    VISUAL_DIRECTOR = "Visual Director"
    PANELS = "Panels ⇄ Critic"
    LAYOUT = "Lettering & Layout"
    CHAPTER_JUDGE = "Chapter Judge"


class StageState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RunState(StrEnum):
    NOT_STARTED = "not started"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget exhausted"


class Cost(BaseModel):
    """Token and spend totals. `usd` is None when the provider has no known price."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    images: int = 0
    usd: float | None = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: "Cost") -> "Cost":
        usd = None if self.usd is None or other.usd is None else self.usd + other.usd
        return Cost(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            images=self.images + other.images,
            usd=usd,
        )


class PanelAttempt(BaseModel):
    """One generated image for a panel and the Critic's verdict on it."""

    attempt: int = Field(ge=1)
    accepted: bool
    failure: str = Field(default="", description="Failure category, e.g. WRONG_OUTFIT.")
    note: str = ""
    image: str = Field(default="", description="Saved image; empty for simulated attempts.")
    score: float | None = None


class PanelResult(BaseModel):
    """A scripted panel and every image attempt made for it."""

    panel_id: str
    page: int = Field(ge=1)
    index: int = Field(ge=1, description="Position on its page.")
    description: str
    caption: str = ""
    dialogue: str = ""
    attempts: list[PanelAttempt] = Field(default_factory=list)
    heads: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Character -> head box [left, top, right, bottom], as fractions of the image.",
    )

    @property
    def accepted(self) -> bool:
        return any(attempt.accepted for attempt in self.attempts)

    @property
    def best_image(self) -> str:
        """The accepted image, else the highest-scored one. Never the last by default."""
        real = [attempt for attempt in self.attempts if attempt.image]
        if not real:
            return ""
        return max(real, key=lambda attempt: (attempt.accepted, attempt.score or 0)).image


class StageStatus(BaseModel):
    state: StageState = StageState.PENDING
    detail: str = ""
    attempts: int = 0
    cost: Cost = Field(default_factory=Cost)


class RunSettings(BaseModel):
    """Sidebar choices, recorded with the run for provenance."""

    provider: str
    text_model: str
    image_model: str
    max_script_attempts: int = Field(default=3, ge=1, le=10)
    max_panel_attempts: int = Field(default=3, ge=1, le=10)
    chapter_budget_usd: float = Field(default=5.0, gt=0)


def _now() -> datetime:
    return datetime.now(UTC)


class ChapterRun(BaseModel):
    """Everything the UI shows about one chapter's pipeline run."""

    chapter_id: str
    spec: ChapterSpec
    state: RunState = RunState.NOT_STARTED
    settings: RunSettings | None = None
    stages: dict[Stage, StageStatus] = Field(
        default_factory=lambda: {stage: StageStatus() for stage in Stage}
    )
    outline: StoryOutline | None = None
    script: Script | None = None
    script_critique: ScriptCritique | None = None
    visual_plan: VisualPlan | None = None
    reference_drafts: dict[str, str] = Field(
        default_factory=dict, description="Character -> generated sheet awaiting approval."
    )
    reference_cost: Cost = Field(default_factory=Cost)
    prompt_versions: dict[str, str] = Field(default_factory=dict, description="Stage -> prompt version.")
    panels: list[PanelResult] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list, description="Lettered page images.")
    pdf: str = ""
    verdict: ChapterVerdict | None = None
    accepted: bool = Field(default=False, description="Set only at the acceptance boundary.")
    log: list[str] = Field(default_factory=list)
    error: str = ""
    created: datetime = Field(default_factory=_now)
    updated: datetime = Field(default_factory=_now)

    @property
    def cost(self) -> Cost:
        total = self.reference_cost
        for status in self.stages.values():
            total = total.add(status.cost)
        return total
