"""Live Chapter Judge on a finished run's saved pages. Nothing is accepted or committed.

    uv run python scripts/smoke_chapter_judge.py chapter-1-the-reunion
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from comartist.adapters import build_text_model
from comartist.agents.chapter_judge import ChapterJudge
from comartist.workflows.store import RunStore

run = RunStore(Path("runs")).load(sys.argv[1])
result = ChapterJudge(build_text_model("meta", "Muse Wonder")).judge(run.spec, run.script, run.pages)
out = Path("smoke_results") / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-chapter-judge"
out.mkdir()
(out / "summary.json").write_text(json.dumps(result.model_dump(mode="json"), indent=2))
print(result.verdict.model_dump_json(indent=2))
print(f"spent ${result.cost.usd or 0:.4f} -> {out}")
