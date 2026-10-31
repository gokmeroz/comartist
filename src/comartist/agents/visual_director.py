"""Visual Director: turn an approved script into one look per character and one spec per panel.

The model's JSON is validated against `VisualPlan`, then checked against the script. Approved
references come only from the brief, so the model can never mark a reference as approved.
"""

from pydantic import BaseModel, Field

from comartist.adapters import ChatMessage, TextModel, TextRequest
from comartist.agents.parsing import parse_json
from comartist.models.run import ChapterSpec, Cost
from comartist.models.script import Script
from comartist.models.critique import PanelCritique
from comartist.models.visual import PanelSpec, VisualPlan
from comartist.prompts import visual_director as prompt
from comartist.tools.page_templates import image_size, slots_for, templates_for

DEFAULT_MAX_ATTEMPTS = 2  # one draft plus one repair


class VisualDirectorResult(BaseModel):
    plan: VisualPlan
    attempts: int = Field(ge=1)
    cost: Cost
    prompt_version: str
    provider: str
    model: str
    rejected: list[list[str]] = Field(
        default_factory=list, description="Problems found in each rejected attempt."
    )


class VisualDirectorError(Exception):
    def __init__(self, rejected: list[list[str]], cost: Cost) -> None:
        last = "; ".join(rejected[-1]) if rejected else "no attempts"
        super().__init__(f"Visual Director gave no valid plan after {len(rejected)} attempts: {last}")
        self.rejected = rejected
        self.cost = cost


def parse_plan(text: str) -> tuple[VisualPlan | None, list[str]]:
    return parse_json(text, VisualPlan)


def check_plan(plan: VisualPlan, script: Script) -> list[str]:
    """Rules the schema cannot express. An empty list means the plan is acceptable."""
    problems = []
    expected = [panel.panel_id for panel in script.panels]
    got = [spec.panel_id for spec in plan.panels]
    if got != expected:
        problems.append(f"Specs must be for panels {expected} in order, got {got}")
    counts: dict[int, int] = {}
    for panel in script.panels:
        counts[panel.page] = counts.get(panel.page, 0) + 1
    chosen = {layout.page: layout.template for layout in plan.layouts}
    for page, count in counts.items():
        named = templates_for(count)
        if named and chosen.get(page) not in named:
            problems.append(f"Page {page} has {count} panels; choose a layout from {named}")
    looks = {look.name.casefold() for look in plan.looks}
    scripted = {panel.panel_id: panel for panel in script.panels}
    for spec in plan.panels:
        panel = scripted.get(spec.panel_id)
        if panel is None:
            continue
        wanted = {name.casefold() for name in panel.characters}
        shown = {name.casefold() for name in spec.characters}
        if wanted != shown:
            problems.append(f"Panel {spec.panel_id} must show {sorted(wanted)}, got {sorted(shown)}")
        missing = sorted(wanted - looks)
        if missing:
            problems.append(f"Panel {spec.panel_id} has characters with no look: {', '.join(missing)}")
    return problems


def page_of(panel_id: str) -> int:
    return int(panel_id[1:].split("-")[0])


def panel_sizes(plan: VisualPlan) -> dict[str, str]:
    """Generation size per panel, from the slot its page template gives it."""
    chosen = {layout.page: layout.template for layout in plan.layouts}
    sizes = {}
    for page in sorted({page_of(panel.panel_id) for panel in plan.panels}):
        ids = [panel.panel_id for panel in plan.panels if page_of(panel.panel_id) == page]
        slots = slots_for(chosen.get(page, ""), len(ids))
        sizes.update({panel_id: image_size(slot) for panel_id, slot in zip(ids, slots)})
    return sizes


def attach_references(plan: VisualPlan, spec: ChapterSpec) -> VisualPlan:
    """Name, on each panel, the visible characters with an approved reference in the brief."""
    approved = {name.casefold(): name for name in spec.references}
    sizes = panel_sizes(plan)
    panels = [
        panel.model_copy(
            update={
                "size": sizes[panel.panel_id],
                "references": [
                    approved[name.casefold()] for name in panel.characters if name.casefold() in approved
                ],
            }
        )
        for panel in plan.panels
    ]
    locked = {look.name.casefold(): look for look in spec.looks()}
    looks = [locked.get(look.name.casefold(), look) for look in plan.looks]
    style = spec.art_style or prompt.DEFAULT_STYLE
    return plan.model_copy(update={"panels": panels, "looks": looks, "style": style})


class VisualDirector:
    def __init__(self, model: TextModel, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self._model = model
        self._max_attempts = max_attempts

    def redirect_panel(
        self, shot: PanelSpec, action: str, critique: PanelCritique
    ) -> tuple[PanelSpec, Cost]:
        """Rewrite one shot the Critic says misses the script. Who is visible cannot change."""
        messages = [
            ChatMessage(role="system", content=prompt.REDIRECT_SYSTEM),
            ChatMessage(role="user", content=prompt.redirect_message(shot, action, critique)),
        ]
        cost, rejected = Cost(), []
        for _ in range(self._max_attempts):
            reply = self._model.complete(
                TextRequest(messages=messages, temperature=0.6, max_tokens=4000, json_mode=True)
            )
            cost = cost.add(reply.cost)
            revised, problems = parse_json(reply.text, PanelSpec)
            if revised is not None:
                fixed = {
                    "panel_id": shot.panel_id,
                    "characters": shot.characters,
                    "references": shot.references,
                    "size": shot.size,
                }
                return revised.model_copy(update=fixed), cost
            rejected.append(problems)
            messages += [
                ChatMessage(role="assistant", content=reply.text),
                ChatMessage(role="user", content=prompt.repair_message(problems)),
            ]
        raise VisualDirectorError(rejected, cost)

    def plan(self, spec: ChapterSpec, script: Script) -> VisualDirectorResult:
        messages = [
            ChatMessage(role="system", content=prompt.SYSTEM),
            ChatMessage(role="user", content=prompt.user_message(spec, script)),
        ]
        cost, rejected = Cost(), []
        for attempt in range(1, self._max_attempts + 1):
            reply = self._model.complete(
                TextRequest(messages=messages, temperature=0.6, max_tokens=12000, json_mode=True)
            )
            cost = cost.add(reply.cost)
            plan, problems = parse_plan(reply.text)
            if plan is not None:
                problems = check_plan(plan, script)
            if not problems:
                return VisualDirectorResult(
                    plan=attach_references(plan, spec),
                    attempts=attempt,
                    cost=cost,
                    prompt_version=prompt.VERSION,
                    provider=reply.provider,
                    model=reply.model,
                    rejected=rejected,
                )
            rejected.append(problems)
            messages += [
                ChatMessage(role="assistant", content=reply.text),
                ChatMessage(role="user", content=prompt.repair_message(problems)),
            ]
        raise VisualDirectorError(rejected, cost)
