"""Chapter Judge prompt. Bump VERSION whenever the wording changes; it is recorded per run."""

from comartist.models.run import ChapterSpec
from comartist.models.script import Script
from comartist.models.verdict import ChapterFailure

VERSION = "chapter_judge/v1"

SYSTEM = f"""\
You are the Chapter Judge. The images are the lettered comic pages, in order. Judge the chapter
as one sequential narrative, not panel by panel.

Reject only for failures a reader would notice, using these categories:
{chr(10).join(f"- {failure.value}" for failure in ChapterFailure)}

Rules:
- CANON_VIOLATION always blocks approval. Check every canon fact against the pages.
- CONTINUITY covers outfits, appearance, location, and time of day from page to page.
- READABILITY covers reading order and speech bubbles that are hard to follow.
- "score" is your estimate from 0 to 1 of the chapter's quality.

Reply with a single JSON object and nothing else, in this shape:
{{"approved": false, "score": 0.5, "summary": "two sentences", "issues": [
  {{"category": "PACING", "page": 2, "evidence": "...", "repair": "..."}}
]}}"""


def user_message(spec: ChapterSpec, script: Script) -> str:
    lines = [f"Title: {spec.title}", f"Premise: {spec.premise}", f"Location: {spec.location or 'unspecified'}"]
    if spec.canon:
        lines.append("Canon:")
        lines.extend(f"- {fact}" for fact in spec.canon)
    lines.append("Dialogue:")
    for panel in script.panels:
        lines.extend(f"{panel.panel_id} {line.speaker}: {line.text}" for line in panel.dialogue)
    return "\n".join(lines)


def repair_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return f"Your verdict was rejected:\n{listed}\nReturn the corrected JSON object only."
