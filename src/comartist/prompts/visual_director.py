"""Visual Director prompt. Bump VERSION whenever the wording changes; it is recorded per run."""

from comartist.models.run import ChapterSpec
from comartist.models.script import Script

VERSION = "visual_director/v1"

SYSTEM = """\
You are the Visual Director for a comic chapter. You translate a finished script into shots.
You do not change story events, dialogue, or who appears in a panel.

Rules:
- Choose one art style for the whole chapter.
- Give every visible character one look: appearance and outfit, specific enough to redraw.
- Write exactly one spec per script panel, in order, using the given panel ids.
- List in "characters" exactly the characters the script shows in that panel.
- Vary framing to serve the emotion, and keep screen direction consistent within a scene.
- Leave room for speech balloons in panels with dialogue.
- Do not put any written text, captions, or speech balloons in the shot itself.

Reply with a single JSON object and nothing else, in this shape:
{
  "style": "...",
  "looks": [{"name": "Name", "appearance": "...", "outfit": "..."}],
  "panels": [
    {"panel_id": "p1-1", "framing": "...", "composition": "...", "poses": "...",
     "lighting": "...", "setting": "...", "characters": ["Name"]}
  ]
}"""


def user_message(spec: ChapterSpec, script: Script) -> str:
    lines = [f"Title: {spec.title}", f"Characters: {', '.join(spec.characters)}"]
    if spec.timeframe:
        lines.append(f"Timeframe: {spec.timeframe}")
    if spec.tone:
        lines.append(f"Tone: {', '.join(spec.tone)}")
    if spec.canon:
        lines.append("Canon (must not be contradicted):")
        lines.extend(f"- {fact}" for fact in spec.canon)
    lines += ["", "Script:"]
    for scene in script.scenes:
        lines.append(f"Scene at {scene.location}: {scene.summary}")
        for panel in scene.panels:
            lines.append(f"{panel.panel_id} [{', '.join(panel.characters)}]: {panel.action}")
            lines.extend(f"  {line.speaker}: {line.text}" for line in panel.dialogue)
    return "\n".join(lines)


def repair_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return f"Your visual plan was rejected:\n{listed}\nReturn the corrected JSON object only."
