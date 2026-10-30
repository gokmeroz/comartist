"""Deterministic lettering, page layout, and export. No model is involved here.

Each line of dialogue becomes its own speech bubble on the art, in reading order, with a
tail pointing at its speaker. Bubbles sit at the top of the panel, away from most faces.
"""

import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from comartist.models import ChapterRun, PanelResult, PanelSpec, ScriptPanel

PANEL_WIDTH = 1200
FONT_SIZE = 40
PADDING = 26
TAIL = 70
OUTLINE = 4
MARGIN = 24
PAGE_WIDTH = 2000
GUTTER = 24
INK = (28, 24, 20)
PAPER = (255, 255, 255)
CAPTION_FILL = (250, 225, 140)


def speaker_positions(shot: PanelSpec) -> dict[str, float]:
    """Horizontal position (0-1) of each character, read from the shot's composition text."""
    positions = {}
    count = len(shot.characters)
    for order, name in enumerate(shot.characters):
        positions[name] = (order + 1) / (count + 1)
        match = re.search(rf"{re.escape(name)}\b[^.;,]{{0,40}}?(left|right|cent)", shot.composition, re.I)
        if match:
            positions[name] = {"left": 0.28, "cent": 0.5, "right": 0.72}[match.group(1).lower()]
    return positions


def _font() -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=FONT_SIZE)


def _text_box(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[str, int, int]:
    wrapped = "\n".join(textwrap.wrap(text.upper(), width=22))
    left, top, right, bottom = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    return wrapped, right - left, bottom - top


def _draw_caption(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    wrapped, width, height = _text_box(draw, text, font)
    box = (0, 0, width + 2 * PADDING, height + 2 * PADDING)
    draw.rectangle(box, fill=CAPTION_FILL, outline=INK, width=OUTLINE)
    draw.multiline_text((PADDING, PADDING), wrapped, fill=INK, font=font)
    return box[3]


def _draw_bubble(draw: ImageDraw.ImageDraw, text: str, x: float, top: int, image_width: int, font) -> tuple[int, int, int]:
    wrapped, width, height = _text_box(draw, text, font)
    box_width, box_height = width + 2 * PADDING, height + 2 * PADDING
    left = int(min(max(MARGIN, x * image_width - box_width / 2), image_width - box_width - MARGIN))
    right, bottom = left + box_width, top + box_height
    tip_x = int(min(max(left + 50, x * image_width), right - 50))
    tail = [(tip_x - 30, bottom - OUTLINE), (tip_x + 30, bottom - OUTLINE), (tip_x, bottom + TAIL)]
    draw.polygon(tail, fill=PAPER, outline=INK, width=OUTLINE)
    draw.rounded_rectangle((left, top, right, bottom), radius=45, fill=PAPER, outline=INK, width=OUTLINE)
    draw.line(tail[:2], fill=PAPER, width=OUTLINE + 2)
    draw.multiline_text((left + PADDING, top + PADDING), wrapped, fill=INK, font=font, align="center")
    return left, right, bottom


def letter_panel(image_path: str, panel: ScriptPanel, shot: PanelSpec, out: Path) -> Path:
    image = Image.open(image_path).convert("RGB")
    image = image.resize((PANEL_WIDTH, image.height * PANEL_WIDTH // image.width))
    draw = ImageDraw.Draw(image)
    font = _font()
    top = MARGIN
    if panel.caption:
        top = _draw_caption(draw, panel.caption, font) + MARGIN
    positions = speaker_positions(shot)
    previous: tuple[int, int, int] | None = None
    for line in panel.dialogue:
        x = positions.get(line.speaker, 0.5)
        y = top
        if previous:
            wrapped_width = _text_box(draw, line.text, font)[1] + 2 * PADDING
            clear = x * PANEL_WIDTH - wrapped_width / 2 > previous[1]
            y = top + 40 if clear else previous[2] + TAIL + 12
        previous = _draw_bubble(draw, line.text, x, y, PANEL_WIDTH, font)
    image.save(out)
    return out


def compose_page(panels: list[Path], out: Path) -> Path:
    """Two columns; with an odd count the first panel runs the full width."""
    rows: list[list[Path]] = []
    remaining = list(panels)
    if len(remaining) % 2:
        rows.append([remaining.pop(0)])
    rows += [remaining[i : i + 2] for i in range(0, len(remaining), 2)]
    sized = []
    for row in rows:
        width = (PAGE_WIDTH - GUTTER * (len(row) + 1)) // len(row)
        images = [Image.open(path) for path in row]
        sized.append([image.resize((width, image.height * width // image.width)) for image in images])
    height = GUTTER + sum(row[0].height + GUTTER for row in sized)
    page = Image.new("RGB", (PAGE_WIDTH, height), PAPER)
    y = GUTTER
    for row in sized:
        x = GUTTER
        for image in row:
            page.paste(image, (x, y))
            ImageDraw.Draw(page).rectangle(
                (x, y, x + image.width, y + image.height), outline=INK, width=OUTLINE + 2
            )
            x += image.width + GUTTER
        y += row[0].height + GUTTER
    page.save(out)
    return out


def _unlettered(panels: list[PanelResult]) -> list[str]:
    return [panel.panel_id for panel in panels if not panel.best_image]


def letter_chapter(run: ChapterRun, folder: Path) -> tuple[list[str], str]:
    """Letter every panel, build the pages, and export a PDF. Returns (pages, pdf path)."""
    missing = _unlettered(run.panels)
    if missing:
        raise ValueError(f"Panels without an image: {', '.join(missing)}")
    folder.mkdir(exist_ok=True)
    scripted = {panel.panel_id: panel for panel in run.script.panels}
    shots = {shot.panel_id: shot for shot in run.visual_plan.panels}
    pages = []
    for number in sorted({panel.page for panel in run.panels}):
        lettered = [
            letter_panel(panel.best_image, scripted[panel.panel_id], shots[panel.panel_id], folder / f"{panel.panel_id}.png")
            for panel in run.panels
            if panel.page == number
        ]
        pages.append(compose_page(lettered, folder / f"page-{number}.png"))
    pdf = folder / "chapter.pdf"
    images = [Image.open(page).convert("RGB") for page in pages]
    images[0].save(pdf, save_all=True, append_images=images[1:])
    return [str(page) for page in pages], str(pdf)
