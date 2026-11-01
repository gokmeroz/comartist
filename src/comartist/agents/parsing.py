"""Shared parsing of model replies into typed artifacts."""

import json

from pydantic import BaseModel, ValidationError


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def parse_json[T: BaseModel](text: str, schema: type[T]) -> tuple[T | None, list[str]]:
    try:
        return schema.model_validate(json.loads(_strip_fences(text))), []
    except json.JSONDecodeError as error:
        return None, [f"Not valid JSON: {error.msg} at position {error.pos}"]
    except ValidationError as error:
        return None, [
            f"{'.'.join(str(part) for part in issue['loc']) or 'root'}: {issue['msg']}"
            for issue in error.errors()
        ]


TOKENS_PER_PAGE = 4000


def chapter_max_tokens(floor: int, pages: int) -> int:
    """Token cap for a whole-chapter call. Hidden reasoning counts, and it grows with page count."""
    return max(floor, TOKENS_PER_PAGE * pages)
