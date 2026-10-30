"""Re-letter a finished run from its saved panels. Free: no model is called.

    uv run python scripts/letter_run.py chapter-1-the-reunion
"""

import sys
from pathlib import Path

from comartist.tools.lettering import letter_chapter
from comartist.workflows.store import RunStore

store = RunStore(Path("runs"))
run = store.load(sys.argv[1])
run.pages, run.pdf = letter_chapter(run, store.root / run.chapter_id / "pages")
store.save(run)
print(run.pages, run.pdf)
