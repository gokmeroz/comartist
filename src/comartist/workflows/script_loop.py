"""LangGraph loop: Script Writer <-> Critic, bounded by attempts and repeated failures.

An unapproved best draft is returned with `approved=False`, never marked accepted.
"""

from enum import StrEnum

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from comartist.adapters import ModelError
from comartist.agents.critic import Critic, CriticError
from comartist.agents.script_writer import ScriptWriter, ScriptWriterError
from comartist.models.critique import ScriptCritique
from comartist.models.run import ChapterSpec, Cost
from comartist.models.script import Script
from comartist.models.story import StoryOutline


class StopReason(StrEnum):
    APPROVED = "approved"
    ATTEMPTS_EXHAUSTED = "attempts exhausted"
    REPEATED_FAILURE = "same failures repeated"


class ScriptDraft(BaseModel):
    script: Script
    critique: ScriptCritique


class ScriptLoopResult(BaseModel):
    script: Script
    critique: ScriptCritique
    approved: bool
    stop_reason: StopReason
    attempts: int = Field(ge=1)
    drafts: list[ScriptDraft]
    cost: Cost
    prompt_versions: dict[str, str]
    provider: str
    model: str


class ScriptLoopError(Exception):
    """A stage failed outright. Carries spend and any drafts finished before the failure."""

    def __init__(self, cause: Exception, cost: Cost, drafts: list[ScriptDraft]) -> None:
        super().__init__(str(cause))
        self.cost = cost
        self.drafts = drafts


class _State(BaseModel):
    spec: ChapterSpec
    outline: StoryOutline
    script: Script | None = None
    drafts: list[ScriptDraft] = Field(default_factory=list)
    cost: Cost = Field(default_factory=Cost)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    provider: str = ""
    model: str = ""
    stop_reason: StopReason | None = None
    error: str = ""


class ScriptLoop:
    def __init__(self, writer: ScriptWriter, critic: Critic, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._writer = writer
        self._critic = critic
        self._max_attempts = max_attempts
        self._cause: Exception | None = None
        graph = StateGraph(_State)
        graph.add_node("write", self._write)
        graph.add_node("critique", self._critique)
        graph.set_entry_point("write")
        graph.add_conditional_edges("write", self._after_write, {"critique": "critique", END: END})
        graph.add_conditional_edges("critique", self._after_critique, {"write": "write", END: END})
        self._graph = graph.compile()

    def _fail(self, state: _State, error: Exception) -> dict:
        self._cause = error
        cost = getattr(error, "cost", None) or Cost()
        return {"error": str(error), "cost": state.cost.add(cost)}

    def _write(self, state: _State) -> dict:
        try:
            if state.drafts:
                last = state.drafts[-1]
                result = self._writer.revise(state.spec, state.outline, last.script, last.critique)
            else:
                result = self._writer.write(state.spec, state.outline)
        except (ScriptWriterError, ModelError) as error:
            return self._fail(state, error)
        return {
            "script": result.script,
            "cost": state.cost.add(result.cost),
            "prompt_versions": {**state.prompt_versions, "writer": result.prompt_version},
            "provider": result.provider,
            "model": result.model,
        }

    def _critique(self, state: _State) -> dict:
        try:
            result = self._critic.review_script(state.spec, state.outline, state.script)
        except (CriticError, ModelError) as error:
            return self._fail(state, error)
        drafts = [*state.drafts, ScriptDraft(script=state.script, critique=result.critique)]
        reason = None
        if result.critique.approved:
            reason = StopReason.APPROVED
        elif len(drafts) >= self._max_attempts:
            reason = StopReason.ATTEMPTS_EXHAUSTED
        elif state.drafts and state.drafts[-1].critique.signature == result.critique.signature:
            reason = StopReason.REPEATED_FAILURE
        return {
            "drafts": drafts,
            "cost": state.cost.add(result.cost),
            "prompt_versions": {**state.prompt_versions, "critic": result.prompt_version},
            "stop_reason": reason,
        }

    @staticmethod
    def _after_write(state: _State) -> str:
        return END if state.error else "critique"

    @staticmethod
    def _after_critique(state: _State) -> str:
        return END if state.error or state.stop_reason else "write"

    def run(self, spec: ChapterSpec, outline: StoryOutline) -> ScriptLoopResult:
        self._cause = None
        final = _State.model_validate(
            self._graph.invoke(
                _State(spec=spec, outline=outline),
                {"recursion_limit": 2 * self._max_attempts + 2},
            )
        )
        if final.error:
            raise ScriptLoopError(self._cause or RuntimeError(final.error), final.cost, final.drafts)
        best = max(final.drafts, key=lambda draft: (draft.critique.approved, draft.critique.score))
        return ScriptLoopResult(
            script=best.script,
            critique=best.critique,
            approved=best.critique.approved,
            stop_reason=final.stop_reason,
            attempts=len(final.drafts),
            drafts=final.drafts,
            cost=final.cost,
            prompt_versions=final.prompt_versions,
            provider=final.provider,
            model=final.model,
        )
