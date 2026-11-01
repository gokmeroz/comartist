"""Critic prompt, visual mode. Bump VERSION whenever the wording changes; it is recorded per run."""

from pydantic import BaseModel

from comartist.models.critique import PanelFailure
from comartist.models.visual import CharacterLook, PanelSpec

VERSION = "panel_critic/v4"

SYSTEM = f"""\
You are the Critic for one generated comic panel. The first image is the panel; any further
images are approved character references.

Reject only for failures a reader would notice, using these categories:
{chr(10).join(f"- {failure.value}" for failure in PanelFailure)}

Use MISSING_CHARACTER when someone required is absent and SCRIPT_MISMATCH when the action
differs. Use WRONG_LOCATION when streets, signs, or architecture do not fit the stated
location. Use IDENTITY_DRIFT or WRONG_OUTFIT when a character does not match their look.
References fix face, hair, and build only; judge outfits by the written look, since a
character may wear different clothes than in their reference. Use COMPOSITION when part of
the frame is blank, unpainted, or a flat band of colour instead of artwork.
"score" is your estimate from 0 to 1 of the panel's quality.

Reply with a single JSON object and nothing else, in this shape:
{{"approved": false, "score": 0.5, "issues": [
  {{"category": "COMPOSITION", "evidence": "...", "repair": "..."}}
]}}"""


HEADS_SYSTEM = """\
Locate each described character's head in the comic panel, hair included. Match people by
their description, especially hair and clothing; never guess from position. Key each box by
the name only. Give boxes as
[left, top, right, bottom], each a fraction of the image width or height from 0 to 1.
Omit anyone not visible. Reply with a single JSON object and nothing else:
{"heads": {"Name": [0.1, 0.2, 0.3, 0.4]}}"""


class HeadBoxes(BaseModel):
    heads: dict[str, list[float]]


def user_message(
    shot: PanelSpec, action: str, style: str, looks: list[CharacterLook], place: str = ""
) -> str:
    lines = [
        f"Style: {style}",
        f"Action: {action}",
        f"Must show: {', '.join(shot.characters) or 'no characters'}",
        f"Shot: {shot.framing}. {shot.composition} {shot.poses}",
    ]
    if place:
        lines.append(f"Location: {place}")
    lines += [f"{look.name}: {look.appearance} Outfit: {look.outfit}" for look in looks]
    return "\n".join(lines)


def repair_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return f"Your critique was rejected:\n{listed}\nReturn the corrected JSON object only."
