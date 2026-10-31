"""Visual Director prompt. Bump VERSION whenever the wording changes; it is recorded per run."""

from comartist.models.run import ChapterSpec
from comartist.models.critique import PanelCritique
from comartist.models.script import Script
from comartist.models.visual import PanelSpec
from comartist.tools.page_templates import TEMPLATES

VERSION = "visual_director/v4"

SYSTEM = """\
You are the Visual Director for a comic chapter. You translate a finished script into shots.
You do not change story events, dialogue, or who appears in a panel.

Rules:
- Copy the required art style into "style" unchanged.
- Give every visible character one look: appearance and outfit, specific enough to redraw.
- Write exactly one spec per script panel, in order, using the given panel ids.
- List in "characters" exactly the characters the script shows in that panel.
- Direct like a superhero comic: mix extreme close-ups, low and high angles, over-the-shoulder
  shots, silhouettes, and panels with a flat color background behind the figures. Never use
  two plain medium shots in a row, and give each page one dramatic hero shot.
- Keep screen direction consistent within a scene.
- Pick one layout per page whose panel count matches that page, and fit each shot to its slot:
  tall slots suit full figures, wide strips suit stare-downs and establishing shots.
- Leave room for speech balloons in panels with dialogue.
- Do not put any written text, captions, or speech balloons in the shot itself.

Reply with a single JSON object and nothing else, in this shape:
{
  "style": "...",
  "looks": [{"name": "Name", "appearance": "...", "outfit": "..."}],
  "layouts": [{"page": 1, "template": "hero_top"}],
  "panels": [
    {"panel_id": "p1-1", "framing": "...", "composition": "...", "poses": "...",
     "lighting": "...", "setting": "...", "characters": ["Name"]}
  ]
}"""


REDIRECT_SYSTEM = """\
You are the Visual Director repairing one comic panel the Critic says misses its script.
Keep the action and the visible characters. Change the shot so the failure cannot recur.
Reply with a single JSON object and nothing else, with these fields: panel_id, framing,
composition, poses, lighting, setting, characters."""


def redirect_message(shot: PanelSpec, action: str, critique: PanelCritique) -> str:
    listed = "\n".join(f"- [{i.category}] {i.evidence} Repair: {i.repair}" for i in critique.issues)
    return f"Script action: {action}\nCurrent shot: {shot.model_dump_json()}\nCritic failures:\n{listed}"


DEFAULT_STYLE = (
    "Modern American superhero comic book art: bold confident black inks, clean cel shading "
    "with hard-edged shadows, saturated flat colors, dynamic anatomy"
)


def user_message(spec: ChapterSpec, script: Script) -> str:
    style = spec.art_style or DEFAULT_STYLE

    lines = [
        f"Title: {spec.title}",
        f"Characters: {', '.join(spec.characters)}",
        f"Required art style: {style}",
        "Layouts (panels in reading order):",
    ]
    lines += [f"- {name}: {len(slots)} panels" for name, slots in TEMPLATES.items()]
    if spec.timeframe:
        lines.append(f"Timeframe: {spec.timeframe}")
    if spec.tone:
        lines.append(f"Tone: {', '.join(spec.tone)}")
    if spec.canon:
        lines.append("Canon (must not be contradicted):")
        lines.extend(f"- {fact}" for fact in spec.canon)
    if spec.locked_looks:
        lines.append("Approved looks (use exactly as written):")
        lines.extend(f"- {look.name}: {look.appearance} Outfit: {look.outfit}" for look in spec.looks())
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
