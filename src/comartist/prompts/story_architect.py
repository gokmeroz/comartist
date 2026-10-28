"""Story Architect prompt. Bump VERSION whenever the wording changes; it is recorded per run."""

from comartist.models.run import ChapterSpec

VERSION = "story_architect/v1"

SYSTEM = """\
You are the Story Architect for a comic chapter. You design dramatic structure; you do not
write dialogue or describe camera shots.

Rules:
- Produce exactly one beat per page, numbered from 1, for the requested page count.
- Use only the characters named in the brief. Do not add named characters.
- Never contradict a canon fact. Canon is fixed truth supplied by the user.
- Build a clear progression: setup, escalation, a turn, and a page-turn-worthy ending.
- If the outline invents a lasting fact about the world or a character (a relationship,
  a past event, a secret), list it in "proposed_facts". Do not list scene-level details.

Reply with a single JSON object and nothing else, in this shape:
{
  "logline": "one sentence",
  "beats": [
    {"page": 1, "summary": "...", "characters": ["Name"], "location": "...",
     "emotion": "...", "turn": "..."}
  ],
  "proposed_facts": ["..."]
}"""


def user_message(spec: ChapterSpec) -> str:
    lines = [
        f"Title: {spec.title}",
        f"Premise: {spec.premise}",
        f"Pages: {spec.target_pages}",
        f"Characters: {', '.join(spec.characters)}",
    ]
    if spec.timeframe:
        lines.append(f"Timeframe: {spec.timeframe}")
    if spec.location:
        lines.append(f"Main location: {spec.location}")
    if spec.tone:
        lines.append(f"Tone: {', '.join(spec.tone)}")
    if spec.canon:
        lines.append("Canon (must not be contradicted):")
        lines.extend(f"- {fact}" for fact in spec.canon)
    return "\n".join(lines)


def repair_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return f"Your outline was rejected:\n{listed}\nReturn the corrected JSON object only."
