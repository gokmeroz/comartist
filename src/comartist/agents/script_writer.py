"""Script Writer: turn a story outline into scenes of panels with dialogue and captions.

The model's JSON is validated against `Script`, then checked deterministically against the
brief and outline (pages, panel numbering, cast). Failures are fed back once for repair; if
the script is still invalid the agent raises with every problem it saw.
"""

from pydantic import BaseModel, Field

from comartist.adapters import ChatMessage, TextModel, TextRequest
from comartist.agents.parsing import chapter_max_tokens, parse_json
from comartist.models.critique import ScriptCritique
from comartist.models.run import ChapterSpec, Cost
from comartist.models.script import Script
from comartist.models.story import StoryOutline
from comartist.prompts import script_writer as prompt

DEFAULT_MAX_ATTEMPTS = 2  # one draft plus one repair
MAX_PANELS_PER_PAGE = 6


class ScriptWriterResult(BaseModel):
    script: Script
    attempts: int = Field(ge=1)
    cost: Cost
    prompt_version: str
    provider: str
    model: str
    rejected: list[list[str]] = Field(
        default_factory=list, description="Problems found in each rejected attempt."
    )


class ScriptWriterError(Exception):
    def __init__(self, rejected: list[list[str]], cost: Cost) -> None:
        last = "; ".join(rejected[-1]) if rejected else "no attempts"
        super().__init__(f"Script Writer gave no valid script after {len(rejected)} attempts: {last}")
        self.rejected = rejected
        self.cost = cost


def parse_script(text: str) -> tuple[Script | None, list[str]]:
    return parse_json(text, Script)


def check_script(script: Script, spec: ChapterSpec, outline: StoryOutline) -> list[str]:
    """Rules the schema cannot express. An empty list means the script is acceptable."""
    problems = []
    panels = script.panels
    positions = [(panel.page, panel.index) for panel in panels]
    if positions != sorted(set(positions)):
        problems.append(f"Panels must be unique and in reading order, got {positions}")

    beats = {beat.page: beat for beat in outline.beats}
    pages = sorted({panel.page for panel in panels})
    if pages != sorted(beats):
        problems.append(f"Script must cover pages {sorted(beats)}, got {pages}")
    for page in pages:
        indexes = sorted(panel.index for panel in panels if panel.page == page)
        if indexes != list(range(1, len(indexes) + 1)):
            problems.append(f"Page {page} panels must be numbered from 1 without gaps, got {indexes}")
        if len(indexes) > MAX_PANELS_PER_PAGE:
            problems.append(f"Page {page} has {len(indexes)} panels; the maximum is {MAX_PANELS_PER_PAGE}")

    cast = {name.casefold() for name in spec.characters}
    for panel in panels:
        beat = beats.get(panel.page)
        allowed = {name.casefold() for name in beat.characters} if beat else cast
        strays = [name for name in panel.characters if name.casefold() not in allowed]
        if strays:
            problems.append(f"Panel {panel.panel_id} shows characters not on that page: {', '.join(strays)}")
        speakers = [line.speaker for line in panel.dialogue if line.speaker.casefold() not in cast]
        if speakers:
            problems.append(f"Panel {panel.panel_id} has speakers not in the brief: {', '.join(speakers)}")
    return problems


class ScriptWriter:
    def __init__(self, model: TextModel, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self._model = model
        self._max_attempts = max_attempts

    def write(self, spec: ChapterSpec, outline: StoryOutline) -> ScriptWriterResult:
        return self._draft(spec, outline, [])

    def revise(
        self, spec: ChapterSpec, outline: StoryOutline, script: Script, critique: ScriptCritique
    ) -> ScriptWriterResult:
        return self._draft(
            spec,
            outline,
            [
                ChatMessage(role="assistant", content=script.model_dump_json()),
                ChatMessage(role="user", content=prompt.revision_message(critique)),
            ],
        )

    def _draft(
        self, spec: ChapterSpec, outline: StoryOutline, revision: list[ChatMessage]
    ) -> ScriptWriterResult:
        messages = [
            ChatMessage(role="system", content=prompt.SYSTEM),
            ChatMessage(role="user", content=prompt.user_message(spec, outline)),
            *revision,
        ]
        cost, rejected = Cost(), []
        for attempt in range(1, self._max_attempts + 1):
            reply = self._model.complete(
                TextRequest(messages=messages, temperature=0.8, max_tokens=chapter_max_tokens(12000, spec.target_pages), json_mode=True)
            )
            cost = cost.add(reply.cost)
            script, problems = parse_script(reply.text)
            if script is not None:
                problems = check_script(script, spec, outline)
            if not problems:
                return ScriptWriterResult(
                    script=script,
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
        raise ScriptWriterError(rejected, cost)
