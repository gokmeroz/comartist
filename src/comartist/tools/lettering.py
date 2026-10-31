"""Deterministic lettering, page layout, and export. No model is involved here.

Each line of dialogue becomes its own speech bubble on the art, in reading order, with a
tail pointing at its speaker. Bubbles are placed around the located heads.
"""

import math
import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from comartist.models import ChapterRun, PanelResult, PanelSpec, ScriptPanel

PANEL_WIDTH = 1200
FONT_SIZE = 30
PADDING = 20
TAIL = 50
MAX_TAIL = 110
TAIL_WIDTH = 22
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
    wrapped = "\n".join(textwrap.wrap(text.upper(), width=20))
    left, top, right, bottom = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    return wrapped, int(right - left) + 1, int(bottom - top) + 1


def _draw_caption(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    wrapped, width, height = _text_box(draw, text, font)
    box = (0, 0, width + 2 * PADDING, height + 2 * PADDING)
    draw.rectangle(box, fill=CAPTION_FILL, outline=INK, width=OUTLINE)
    draw.multiline_text((PADDING, PADDING), wrapped, fill=INK, font=font)
    return box[3]


Box = tuple[float, float, float, float]


def _overlap(a: Box, b: Box) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return max(width, 0) * max(height, 0)


def _place(size: tuple[int, int], canvas: tuple[int, int], target: tuple[float, float], blocked: list[Box]) -> Box:
    """Pick the free spot nearest the speaker, preferring above them; covering a head costs most."""
    width, height = size
    best, best_cost = None, float("inf")
    for top in range(MARGIN, max(MARGIN + 1, canvas[1] - height - MARGIN), 30):
        for left in range(MARGIN, max(MARGIN + 1, canvas[0] - width - MARGIN), 30):
            box = (left, top, left + width, top + height)
            covered = sum(_overlap(box, item) for item in blocked)
            distance = abs(left + width / 2 - target[0]) + abs(top + height - target[1])
            cost = covered * 100 + distance + (0 if top + height <= target[1] else canvas[1])
            if cost < best_cost:
                best, best_cost = box, cost
    return best or (MARGIN, MARGIN, MARGIN + width, MARGIN + height)


def _draw_bubble(draw: ImageDraw.ImageDraw, wrapped: str, box: Box, tip: tuple[float, float], font) -> None:
    left, top, right, bottom = box
    center = ((left + right) / 2, (top + bottom) / 2)
    dx, dy = tip[0] - center[0], tip[1] - center[1]
    length = math.hypot(dx, dy) or 1
    side = (-dy / length * TAIL_WIDTH, dx / length * TAIL_WIDTH)
    tail = [(center[0] + side[0], center[1] + side[1]), (center[0] - side[0], center[1] - side[1]), tip]
    draw.polygon(tail, fill=PAPER, outline=INK, width=OUTLINE)
    draw.rounded_rectangle(box, radius=40, fill=PAPER, outline=INK, width=OUTLINE)
    # Reopen the bubble's outline where the tail leaves it.
    inner = (center[0] + dx * 0.92, center[1] + dy * 0.92)
    draw.polygon([tail[0], tail[1], inner], fill=PAPER)
    bounds = draw.multiline_textbbox(center, wrapped, font=font, anchor="mm", align="center")
    draw.rectangle((bounds[0], bounds[1], bounds[2], bounds[3]), fill=PAPER)
    draw.multiline_text(center, wrapped, fill=INK, font=font, anchor="mm", align="center")


def letter_panel(
    image_path: str,
    panel: ScriptPanel,
    shot: PanelSpec,
    out: Path,
    width: int = PANEL_WIDTH,
    heads: dict[str, list[float]] | None = None,
) -> Path:
    """Letter at the panel's final width, so text is the same size on every panel."""
    image = Image.open(image_path).convert("RGB")
    image = image.resize((width, image.height * width // image.width))
    draw = ImageDraw.Draw(image)
    font = _font()
    w, h = image.size
    head_boxes = {
        name.casefold(): (box[0] * w, box[1] * h, box[2] * w, box[3] * h) for name, box in (heads or {}).items()
    }
    # The gap keeps bubbles far enough from heads for a visible tail.
    blocked: list[Box] = [(b[0] - TAIL, b[1] - TAIL, b[2] + TAIL, b[3] + TAIL) for b in head_boxes.values()]
    if panel.caption:
        blocked.append((0, 0, w * 0.5, _draw_caption(draw, panel.caption, font) + MARGIN))
    positions = speaker_positions(shot)
    bubbles = []
    for line in panel.dialogue:
        head = head_boxes.get(line.speaker.casefold())
        x = (head[0] + head[2]) / 2 if head else positions.get(line.speaker, 0.5) * w
        y = head[1] if head else h * 0.4
        wrapped, text_width, text_height = _text_box(draw, line.text, font)
        size = (text_width + 2 * PADDING, text_height + 2 * PADDING)
        box = _place(size, (w, h), (x, y), blocked)
        blocked.append(box)
        bubbles.append((wrapped, box, _tail_tip(box, head, x, y)))
    for wrapped, box, tip in bubbles:
        _draw_bubble(draw, wrapped, box, tip, font)
    image.save(out)
    return out


def _tail_tip(box: Box, head: Box | None, x: float, y: float) -> tuple[float, float]:
    """Aim from the bubble at the head, stopping just outside it and within reach."""
    if head is None:
        return x, box[3] + TAIL
    tip_x = min(max((box[0] + box[2]) / 2, head[0] + 10), head[2] - 10)
    tip_y = min(max((box[1] + box[3]) / 2, head[1] - 8), head[3] + 8)
    edge_x = min(max(tip_x, box[0]), box[2])
    edge_y = min(max(tip_y, box[1]), box[3])
    gap = math.hypot(tip_x - edge_x, tip_y - edge_y)
    if gap > MAX_TAIL:
        tip_x = edge_x + (tip_x - edge_x) * MAX_TAIL / gap
        tip_y = edge_y + (tip_y - edge_y) * MAX_TAIL / gap
    return tip_x, tip_y


def page_rows(panels: list) -> list[list]:
    """Two columns; with an odd count the first panel runs the full width."""
    remaining = list(panels)
    rows = [[remaining.pop(0)]] if len(remaining) % 2 else []
    return rows + [remaining[i : i + 2] for i in range(0, len(remaining), 2)]


def row_width(columns: int) -> int:
    return (PAGE_WIDTH - GUTTER * (columns + 1)) // columns


def compose_page(panels: list[Path], out: Path) -> Path:
    rows = page_rows(panels)
    sized = []
    for row in rows:
        width = row_width(len(row))
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
            letter_panel(
                panel.best_image, scripted[panel.panel_id], shots[panel.panel_id],
                folder / f"{panel.panel_id}.png", row_width(len(row)), panel.heads,
            )
            for row in page_rows([panel for panel in run.panels if panel.page == number])
            for panel in row
        ]
        pages.append(compose_page(lettered, folder / f"page-{number}.png"))
    pdf = folder / "chapter.pdf"
    images = [Image.open(page).convert("RGB") for page in pages]
    images[0].save(pdf, save_all=True, append_images=images[1:])
    return [str(page) for page in pages], str(pdf)
