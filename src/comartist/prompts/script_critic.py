"""Critic prompt, script mode. Bump VERSION whenever the wording changes; it is recorded per run."""

from comartist.models.critique import ScriptFailure
from comartist.models.run import ChapterSpec
from comartist.models.script import Script
from comartist.models.story import StoryOutline

VERSION = "script_critic/v1"

SYSTEM = f"""\
You are the Critic for a comic script. You do not rewrite it; you report failures precisely
enough that the Script Writer can repair them.

Reject only for real failures, using these categories:
{chr(10).join(f"- {failure.value}" for failure in ScriptFailure)}

Rules:
- Approve a script with no failure that a reader would notice. Do not reject for taste.
- CANON_VIOLATION and KNOWLEDGE_LEAK always block approval.
- Quote or cite the script as evidence, and give one specific repair per issue.
- Use panel ids like p2-3; leave panel_id empty for a chapter-wide issue.
- "score" is your estimate from 0 to 1 of the script's overall quality.

Reply with a single JSON object and nothing else, in this shape:
{{"approved": false, "score": 0.5, "issues": [
  {{"category": "PACING", "panel_id": "p2-3", "evidence": "...", "repair": "..."}}
]}}"""


def user_message(spec: ChapterSpec, outline: StoryOutline, script: Script) -> str:
    lines = [f"Premise: {spec.premise}", f"Characters: {', '.join(spec.characters)}"]
    if spec.canon:
        lines.append("Canon:")
        lines.extend(f"- {fact}" for fact in spec.canon)
    lines += ["", "Outline:", outline.model_dump_json(), "", "Script:"]
    for panel in script.panels:
        lines.append(f"{panel.panel_id}: {panel.action}")
        if panel.caption:
            lines.append(f"  Caption: {panel.caption}")
        lines.extend(f"  {line.speaker}: {line.text}" for line in panel.dialogue)
    return "\n".join(lines)


def repair_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return f"Your critique was rejected:\n{listed}\nReturn the corrected JSON object only."
