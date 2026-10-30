"""Muse Image prompt for one panel. Bump VERSION whenever the wording changes."""

from comartist.models.visual import CharacterLook, PanelSpec

VERSION = "panel_image/v2"


def build(
    shot: PanelSpec, action: str, style: str, looks: list[CharacterLook], repairs: list[str], place: str = ""
) -> str:
    lines = [
        f"One comic panel. Style: {style}",
        f"Action: {action}",
        f"Shot: {shot.framing}. {shot.composition}",
        f"Poses: {shot.poses}",
        f"Lighting: {shot.lighting}",
        f"Setting: {shot.setting}",
    ]
    if place:
        lines.append(f"Real-world location, match its streets and architecture exactly: {place}")
    lines.append("Keep the top quarter of the image clear of faces, for speech balloons.")
    lines += [f"{look.name}: {look.appearance} Outfit: {look.outfit}" for look in looks]
    lines += [f"Must fix: {repair}" for repair in repairs]
    lines.append("No text, letters, captions, speech balloons, or panel borders in the image.")
    return "\n".join(lines)
