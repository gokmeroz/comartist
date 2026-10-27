"""Chapter spec, pipeline run status, and cost accounting."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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


class PanelResult(BaseModel):
    """A scripted panel and every image attempt made for it."""

    panel_id: str
    page: int = Field(ge=1)
    index: int = Field(ge=1, description="Position on its page.")
    description: str
    caption: str = ""
    dialogue: str = ""
    attempts: list[PanelAttempt] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return any(attempt.accepted for attempt in self.attempts)


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
    panels: list[PanelResult] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)
    error: str = ""
    created: datetime = Field(default_factory=_now)
    updated: datetime = Field(default_factory=_now)

    @property
    def cost(self) -> Cost:
        total = Cost()
        for status in self.stages.values():
            total = total.add(status.cost)
        return total
