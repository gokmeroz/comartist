"""Critic, script mode: judge a script and report failures with evidence and repairs.

Visual critique will be another mode of this role. A malformed reply gets one repair; after
that the agent raises rather than treating an unreadable verdict as approval.
"""

from pydantic import BaseModel, Field

from comartist.adapters import ChatMessage, TextModel, TextRequest
from comartist.agents.parsing import parse_json
from comartist.models.critique import PanelCritique, ScriptCritique
from comartist.models.run import ChapterSpec, Cost
from comartist.models.script import Script
from comartist.models.story import StoryOutline
from comartist.models.visual import CharacterLook, PanelSpec
from comartist.prompts import panel_critic, script_critic as prompt

DEFAULT_MAX_ATTEMPTS = 2  # one reply plus one repair


class CriticResult(BaseModel):
    critique: ScriptCritique
    cost: Cost
    prompt_version: str
    provider: str
    model: str


class PanelCriticResult(BaseModel):
    critique: PanelCritique
    cost: Cost
    prompt_version: str


class CriticError(Exception):
    def __init__(self, rejected: list[list[str]], cost: Cost) -> None:
        super().__init__(f"Critic gave no valid critique after {len(rejected)} attempts: {'; '.join(rejected[-1])}")
        self.rejected = rejected
        self.cost = cost


class Critic:
    def __init__(self, model: TextModel, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self._model = model
        self._max_attempts = max_attempts

    def review_panel(
        self,
        shot: PanelSpec,
        action: str,
        style: str,
        looks: list[CharacterLook],
        image: str,
        references: list[str],
        place: str = "",
    ) -> PanelCriticResult:
        """`image` and `references` are URLs or data URLs; the panel is sent first."""
        messages = [
            ChatMessage(role="system", content=panel_critic.SYSTEM),
            ChatMessage(role="user", content=panel_critic.user_message(shot, action, style, looks, place)),
        ]
        cost, rejected = Cost(), []
        for _ in range(self._max_attempts):
            reply = self._model.complete(
                TextRequest(
                    messages=messages,
                    temperature=0.2,
                    max_tokens=4000,
                    json_mode=True,
                    images=[image, *references],
                )
            )
            cost = cost.add(reply.cost)
            critique, problems = parse_json(reply.text, PanelCritique)
            if critique is not None:
                return PanelCriticResult(critique=critique, cost=cost, prompt_version=panel_critic.VERSION)
            rejected.append(problems)
            messages += [
                ChatMessage(role="assistant", content=reply.text),
                ChatMessage(role="user", content=panel_critic.repair_message(problems)),
            ]
        raise CriticError(rejected, cost)

    def locate_heads(self, image: str, looks: list[CharacterLook]) -> tuple[dict[str, list[float]], Cost]:
        """Find each visible head for lettering. Unusable replies give {} rather than a failure."""
        reply = self._model.complete(
            TextRequest(
                messages=[
                    ChatMessage(role="system", content=panel_critic.HEADS_SYSTEM),
                    ChatMessage(role="user", content="\n".join(f"{look.name}: {look.appearance} Outfit: {look.outfit}" for look in looks)),
                ],
                temperature=0,
                max_tokens=2000,
                json_mode=True,
                images=[image],
            )
        )
        located, _ = parse_json(reply.text, panel_critic.HeadBoxes)
        heads = located.heads if located else {}
        valid = {
            name: box
            for name, box in heads.items()
            if len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
        }
        return valid, reply.cost

    def review_script(self, spec: ChapterSpec, outline: StoryOutline, script: Script) -> CriticResult:
        messages = [
            ChatMessage(role="system", content=prompt.SYSTEM),
            ChatMessage(role="user", content=prompt.user_message(spec, outline, script)),
        ]
        cost, rejected = Cost(), []
        for _ in range(self._max_attempts):
            reply = self._model.complete(
                TextRequest(messages=messages, temperature=0.2, max_tokens=4000, json_mode=True)
            )
            cost = cost.add(reply.cost)
            critique, problems = parse_json(reply.text, ScriptCritique)
            if critique is not None:
                return CriticResult(
                    critique=critique,
                    cost=cost,
                    prompt_version=prompt.VERSION,
                    provider=reply.provider,
                    model=reply.model,
                )
            rejected.append(problems)
            messages += [
                ChatMessage(role="assistant", content=reply.text),
                ChatMessage(role="user", content=prompt.repair_message(problems)),
            ]
        raise CriticError(rejected, cost)
