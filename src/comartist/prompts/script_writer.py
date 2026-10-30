"""Script Writer prompt. Bump VERSION whenever the wording changes; it is recorded per run."""

from comartist.models.run import ChapterSpec
from comartist.models.story import StoryOutline

VERSION = "script_writer/v1"

SYSTEM = """\
You are the Script Writer for a comic chapter. You turn a page-by-page outline into panels,
dialogue, and captions. You do not choose camera angles, lighting, or composition.

Rules:
- Follow the outline: write every page, in order, and keep each page's events and turn.
- Write 3 to 6 panels per page, numbered from 1 on each page.
- Every panel's "action" states what is visible in one moment, not a sequence of moments.
- List everyone visible in "characters". Use only the characters the outline gives that page.
- Speakers must be characters from the brief. Keep each balloon short enough to letter.
- Characters know only what they have plausibly learned so far. Never contradict canon.
- Use "caption" for narration or time and place; leave it empty otherwise.
- Start a new scene when the location changes.
- If the script invents a lasting fact about the world or a character, list it in
  "proposed_facts". Do not list scene-level details.

Reply with a single JSON object and nothing else, in this shape:
{
  "scenes": [
    {"location": "...", "summary": "...", "panels": [
      {"page": 1, "index": 1, "action": "...", "characters": ["Name"],
       "dialogue": [{"speaker": "Name", "text": "..."}], "caption": "...",
       "transition": "..."}
    ]}
  ],
  "proposed_facts": ["..."]
}"""


def user_message(spec: ChapterSpec, outline: StoryOutline) -> str:
    lines = [
        f"Title: {spec.title}",
        f"Premise: {spec.premise}",
        f"Characters: {', '.join(spec.characters)}",
    ]
    if spec.tone:
        lines.append(f"Tone: {', '.join(spec.tone)}")
    if spec.canon:
        lines.append("Canon (must not be contradicted):")
        lines.extend(f"- {fact}" for fact in spec.canon)
    lines += ["", f"Logline: {outline.logline}", "Outline:"]
    for beat in outline.beats:
        lines.append(
            f"- Page {beat.page} ({', '.join(beat.characters)}; location: {beat.location or 'unspecified'}): "
            f"{beat.summary} Emotion: {beat.emotion or 'unspecified'}. Turn: {beat.turn or 'unspecified'}."
        )
    return "\n".join(lines)


def repair_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return f"Your script was rejected:\n{listed}\nReturn the corrected JSON object only."
