"""Story Architect: turn a chapter brief into a page-by-page dramatic outline.

The model's JSON is validated against `StoryOutline`, then checked deterministically
(page count, cast, numbering). Failures are fed back once for repair; if the outline is
still invalid the agent raises with every problem it saw, rather than passing it on.
"""

import json

from pydantic import BaseModel, Field, ValidationError

from comartist.adapters import ChatMessage, TextModel, TextRequest
from comartist.models.run import ChapterSpec, Cost
from comartist.models.story import StoryOutline
from comartist.prompts import story_architect as prompt

DEFAULT_MAX_ATTEMPTS = 2  # one draft plus one repair


class StoryArchitectResult(BaseModel):
    outline: StoryOutline
    attempts: int = Field(ge=1)
    cost: Cost
    prompt_version: str
    provider: str
    model: str
    rejected: list[list[str]] = Field(
        default_factory=list, description="Problems found in each rejected attempt."
    )


class StoryArchitectError(Exception):
    def __init__(self, rejected: list[list[str]], cost: Cost) -> None:
        last = "; ".join(rejected[-1]) if rejected else "no attempts"
        super().__init__(f"Story Architect gave no valid outline after {len(rejected)} attempts: {last}")
        self.rejected = rejected
        self.cost = cost


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def parse_outline(text: str) -> tuple[StoryOutline | None, list[str]]:
    try:
        return StoryOutline.model_validate(json.loads(_strip_fences(text))), []
    except json.JSONDecodeError as error:
        return None, [f"Not valid JSON: {error.msg} at position {error.pos}"]
    except ValidationError as error:
        return None, [
            f"{'.'.join(str(part) for part in issue['loc']) or 'root'}: {issue['msg']}"
            for issue in error.errors()
        ]


def check_outline(outline: StoryOutline, spec: ChapterSpec) -> list[str]:
    """Rules the schema cannot express. An empty list means the outline is acceptable."""
    problems = []
    pages = [beat.page for beat in outline.beats]
    expected = list(range(1, spec.target_pages + 1))
    if pages != expected:
        problems.append(f"Beats must be pages {expected} in order, got {pages}")
    cast = {name.casefold() for name in spec.characters}
    for beat in outline.beats:
        unknown = [name for name in beat.characters if name.casefold() not in cast]
        if unknown:
            problems.append(
                f"Page {beat.page} uses characters not in the brief: {', '.join(unknown)}"
            )
    return problems


class StoryArchitect:
    def __init__(self, model: TextModel, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self._model = model
        self._max_attempts = max_attempts

    def plan(self, spec: ChapterSpec) -> StoryArchitectResult:
        messages = [
            ChatMessage(role="system", content=prompt.SYSTEM),
            ChatMessage(role="user", content=prompt.user_message(spec)),
        ]
        cost, rejected = Cost(), []
        for attempt in range(1, self._max_attempts + 1):
            reply = self._model.complete(
                TextRequest(messages=messages, temperature=0.8, max_tokens=8000, json_mode=True)
            )
            cost = cost.add(reply.cost)
            outline, problems = parse_outline(reply.text)
            if outline is not None:
                problems = check_outline(outline, spec)
            if not problems:
                return StoryArchitectResult(
                    outline=outline,
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
        raise StoryArchitectError(rejected, cost)
