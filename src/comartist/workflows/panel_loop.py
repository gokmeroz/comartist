"""LangGraph loop for one panel: generate <-> Critic, with routing by failure category.

Rendering failures retry generation with the Critic's repairs. Missing characters or script
mismatches go to the Visual Director once. The loop stops at `max_attempts`, on a repeated
failure, or when the budget runs out; unaccepted attempts are kept but never marked accepted.
"""

import base64
from enum import StrEnum
from pathlib import Path

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from comartist.adapters import ImageModel, ImageReference, ImageRequest, ModelError
from comartist.agents.critic import Critic, CriticError
from comartist.agents.visual_director import VisualDirector, VisualDirectorError
from comartist.models.critique import REDIRECT_FAILURES, PanelCritique
from comartist.models.run import ChapterRun, ChapterSpec, Cost, PanelAttempt
from comartist.models.visual import PanelSpec, VisualPlan
from comartist.prompts import panel_image


class PanelStop(StrEnum):
    ACCEPTED = "accepted"
    ATTEMPTS_EXHAUSTED = "attempts exhausted"
    REPEATED_FAILURE = "same failure repeated"
    BUDGET_EXHAUSTED = "budget exhausted"
    ERROR = "error"


class PanelLoopResult(BaseModel):
    attempts: list[PanelAttempt]
    accepted: bool
    stop_reason: PanelStop
    cost: Cost
    shot: PanelSpec
    prompt_versions: list[str]
    error: str = ""


class _State(BaseModel):
    spec: ChapterSpec
    plan: VisualPlan
    shot: PanelSpec
    action: str
    folder: Path
    budget_usd: float
    attempts: list[PanelAttempt] = Field(default_factory=list)
    critique: PanelCritique | None = None
    pending_image: str = ""
    redirected: bool = False
    cost: Cost = Field(default_factory=Cost)
    stop_reason: PanelStop | None = None
    error: str = ""


def data_url(location: str) -> str:
    """Turn a saved file into a data URL; URLs pass through unchanged."""
    if location.startswith(("http://", "https://", "data:")):
        return location
    mime = f"image/{Path(location).suffix.lstrip('.')}"
    return f"data:{mime};base64,{base64.b64encode(Path(location).read_bytes()).decode()}"


class PanelLoop:
    def __init__(
        self, image_model: ImageModel, critic: Critic, director: VisualDirector, max_attempts: int = 3
    ) -> None:
        self._images = image_model
        self._critic = critic
        self._director = director
        self._max_attempts = max_attempts
        graph = StateGraph(_State)
        graph.add_node("generate", self._generate)
        graph.add_node("critique", self._critique)
        graph.add_node("redirect", self._redirect)
        graph.set_entry_point("generate")
        graph.add_conditional_edges("generate", self._after_generate, {"critique": "critique", END: END})
        graph.add_conditional_edges(
            "critique", self._after_critique, {"generate": "generate", "redirect": "redirect", END: END}
        )
        graph.add_conditional_edges("redirect", self._after_redirect, {"generate": "generate", END: END})
        self._graph = graph.compile()

    def locate_heads(self, run: ChapterRun) -> Cost:
        """Record head positions on each panel's best image, so lettering can avoid them."""
        shots = {shot.panel_id: shot for shot in run.visual_plan.panels}
        cost = Cost()
        for panel in run.panels:
            try:
                panel.heads, spent = self._critic.locate_heads(
                    data_url(panel.best_image), shots[panel.panel_id].characters
                )
            except ModelError:
                continue  # lettering falls back to the shot's composition text
            cost = cost.add(spent)
        return cost

    @staticmethod
    def _looks(state: _State) -> list:
        visible = {name.casefold() for name in state.shot.characters}
        return [look for look in state.plan.looks if look.name.casefold() in visible]

    @staticmethod
    def _references(state: _State) -> list[str]:
        return [data_url(state.spec.references[name]) for name in state.shot.references]

    def _generate(self, state: _State) -> dict:
        repairs = [issue.repair for issue in state.critique.issues] if state.critique else []
        prompt = panel_image.build(
            state.shot, state.action, state.plan.style, self._looks(state), repairs, state.spec.location
        )
        references = [
            ImageReference(image_url=url, caption=f"Approved reference for {name}:")
            for name, url in zip(state.shot.references, self._references(state))
        ]
        try:
            result = self._images.generate(ImageRequest(prompt=prompt, references=references, size=state.shot.size))
        except ModelError as error:
            return {"error": str(error), "stop_reason": PanelStop.ERROR}
        number = len(state.attempts) + 1
        if result.image_b64:
            path = state.folder / f"{state.shot.panel_id}-a{number}.{result.mime_type.split('/')[-1]}"
            path.write_bytes(base64.b64decode(result.image_b64))
            image = str(path)
        else:
            image = result.url
        return {"pending_image": image, "cost": state.cost.add(result.cost)}

    def _critique(self, state: _State) -> dict:
        number = len(state.attempts) + 1
        try:
            result = self._critic.review_panel(
                state.shot, state.action, state.plan.style, self._looks(state),
                data_url(state.pending_image), self._references(state), state.spec.location,
            )
        except (CriticError, ModelError) as error:
            attempt = PanelAttempt(attempt=number, accepted=False, failure="CRITIC_ERROR", image=state.pending_image)
            cost = state.cost.add(getattr(error, "cost", None) or Cost())
            return {
                "attempts": [*state.attempts, attempt], "cost": cost,
                "error": str(error), "stop_reason": PanelStop.ERROR,
            }
        critique = result.critique
        cost = state.cost.add(result.cost)
        attempt = PanelAttempt(
            attempt=number,
            accepted=critique.approved,
            failure=", ".join(issue.category for issue in critique.issues),
            note="; ".join(issue.evidence for issue in critique.issues) or "Matches script and references.",
            image=state.pending_image,
            score=critique.score,
        )
        reason = None
        if critique.approved:
            reason = PanelStop.ACCEPTED
        elif number >= self._max_attempts:
            reason = PanelStop.ATTEMPTS_EXHAUSTED
        elif state.critique and state.critique.signature == critique.signature:
            reason = PanelStop.REPEATED_FAILURE
        elif cost.usd is not None and cost.usd >= state.budget_usd:
            reason = PanelStop.BUDGET_EXHAUSTED
        return {
            "attempts": [*state.attempts, attempt],
            "critique": critique,
            "cost": cost,
            "stop_reason": reason,
        }

    def _redirect(self, state: _State) -> dict:
        try:
            shot, cost = self._director.redirect_panel(state.shot, state.action, state.critique)
        except (VisualDirectorError, ModelError) as error:
            spent = state.cost.add(getattr(error, "cost", None) or Cost())
            return {"cost": spent, "error": str(error), "stop_reason": PanelStop.ERROR}
        return {"shot": shot, "redirected": True, "cost": state.cost.add(cost)}

    @staticmethod
    def _after_generate(state: _State) -> str:
        return END if state.stop_reason else "critique"

    @staticmethod
    def _after_critique(state: _State) -> str:
        if state.stop_reason:
            return END
        needs_director = state.critique.signature & REDIRECT_FAILURES
        return "redirect" if needs_director and not state.redirected else "generate"

    @staticmethod
    def _after_redirect(state: _State) -> str:
        return END if state.stop_reason else "generate"

    def run(
        self, spec: ChapterSpec, plan: VisualPlan, shot: PanelSpec, action: str, folder: Path, budget_usd: float
    ) -> PanelLoopResult:
        final = _State.model_validate(
            self._graph.invoke(
                _State(spec=spec, plan=plan, shot=shot, action=action, folder=folder, budget_usd=budget_usd),
                {"recursion_limit": 3 * self._max_attempts + 3},
            )
        )
        return PanelLoopResult(
            attempts=final.attempts,
            accepted=any(attempt.accepted for attempt in final.attempts),
            stop_reason=final.stop_reason,
            cost=final.cost,
            shot=final.shot,
            prompt_versions=[panel_image.VERSION],
            error=final.error,
        )
