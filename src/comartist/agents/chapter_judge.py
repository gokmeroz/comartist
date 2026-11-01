"""Chapter Judge: evaluate the assembled pages. An unreadable verdict is an error, not a pass."""

import base64
import io
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from comartist.adapters import ChatMessage, TextModel, TextRequest
from comartist.agents.parsing import chapter_max_tokens, parse_json
from comartist.models.run import ChapterSpec, Cost
from comartist.models.script import Script
from comartist.models.verdict import ChapterVerdict
from comartist.prompts import chapter_judge as prompt

DEFAULT_MAX_ATTEMPTS = 2  # one reply plus one repair
PAGE_WIDTH = 1000  # enough to read lettering, far smaller than the print page


class ChapterJudgeResult(BaseModel):
    verdict: ChapterVerdict
    cost: Cost
    prompt_version: str


class ChapterJudgeError(Exception):
    def __init__(self, rejected: list[list[str]], cost: Cost) -> None:
        super().__init__(f"Chapter Judge gave no valid verdict: {'; '.join(rejected[-1])}")
        self.rejected = rejected
        self.cost = cost


def page_data_url(path: str) -> str:
    image = Image.open(Path(path)).convert("RGB")
    image.thumbnail((PAGE_WIDTH, PAGE_WIDTH * 2))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"


class ChapterJudge:
    def __init__(self, model: TextModel, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self._model = model
        self._max_attempts = max_attempts

    def judge(self, spec: ChapterSpec, script: Script, pages: list[str]) -> ChapterJudgeResult:
        messages = [
            ChatMessage(role="system", content=prompt.SYSTEM),
            ChatMessage(role="user", content=prompt.user_message(spec, script)),
        ]
        images = [page_data_url(page) for page in pages]
        cost, rejected = Cost(), []
        for _ in range(self._max_attempts):
            reply = self._model.complete(
                TextRequest(messages=messages, temperature=0.2, max_tokens=chapter_max_tokens(16000, spec.target_pages), json_mode=True, images=images)
            )
            cost = cost.add(reply.cost)
            verdict, problems = parse_json(reply.text, ChapterVerdict)
            if verdict is not None:
                return ChapterJudgeResult(verdict=verdict, cost=cost, prompt_version=prompt.VERSION)
            rejected.append(problems)
            messages += [
                ChatMessage(role="assistant", content=reply.text),
                ChatMessage(role="user", content=prompt.repair_message(problems)),
            ]
        raise ChapterJudgeError(rejected, cost)
