"""On-disk chapter runs: one folder per chapter holding brief.yaml and run.json."""

import re
import threading
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from comartist.memory.continuity import CarryOver
from comartist.models import ChapterRun, ChapterSpec

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "new_chapter.yaml"


class BriefError(ValueError):
    """The YAML brief could not be parsed or validated."""


def chapter_template() -> str:
    return TEMPLATE_PATH.read_text()


def parse_brief(text: str) -> ChapterSpec:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise BriefError(f"Invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise BriefError("The brief must be a YAML mapping of fields.")
    try:
        return ChapterSpec.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()
        )
        raise BriefError(problems) from error


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "chapter"


class RunStore:
    """Reads and writes chapter runs under `root`. Safe to call from a worker thread."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def create(self, brief_text: str, carry: CarryOver | None = None) -> ChapterRun:
        """brief.yaml keeps what the person wrote; run.json holds it merged with any carry-over."""
        spec = parse_brief(brief_text)
        if carry:
            spec = carry.apply(spec)
        base = slugify(spec.title)
        chapter_id, suffix = base, 2
        while (self.root / chapter_id).exists():
            chapter_id, suffix = f"{base}-{suffix}", suffix + 1
        folder = self.root / chapter_id
        folder.mkdir(parents=True)
        (folder / "brief.yaml").write_text(brief_text)
        run = ChapterRun(chapter_id=chapter_id, spec=spec)
        if carry and carry.sources:
            run.log.append(
                f"Carried over from {', '.join(carry.sources)}: {len(carry.canon)} canon facts, "
                f"looks for {', '.join(look.name for look in carry.locked_looks) or 'nobody'}"
            )
        self.save(run)
        return run

    def save(self, run: ChapterRun) -> None:
        run.updated = datetime.now(UTC)
        path = self.root / run.chapter_id / "run.json"
        with self._lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(run.model_dump_json(indent=2))
            tmp.replace(path)

    def load(self, chapter_id: str) -> ChapterRun:
        with self._lock:
            return ChapterRun.model_validate_json((self.root / chapter_id / "run.json").read_text())

    def list(self) -> list[ChapterRun]:
        if not self.root.exists():
            return []
        runs = [self.load(path.parent.name) for path in self.root.glob("*/run.json")]
        return sorted(runs, key=lambda run: run.created)
