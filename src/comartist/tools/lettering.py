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
from comartist.tools.page_templates import PAGE_HEIGHT, PAGE_WIDTH, Slot, slots_for

PANEL_WIDTH = 1200
FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "ComicNeue-Bold.ttf"
FONT_SIZE = 34
PADDING = 20
TAIL = 50
MAX_TAIL = 110
TAIL_WIDTH = 22
OUTLINE = 4
MARGIN = 24
PAGE_MARGIN = 60
GUTTER = 28
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
    return ImageFont.truetype(FONT_PATH, FONT_SIZE)


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


def _place(
    size: tuple[int, int],
    canvas: tuple[int, int],
    target: tuple[float, float],
    blocked: list[Box],
    after: Box | None = None,
    others: list[tuple[float, float]] | None = None,
) -> Box:
    """Pick the free spot nearest the speaker, preferring above them; covering a head costs most.

    A spot nearer another character's head than the speaker's would read as theirs, so it
    costs as much as covering the whole bubble with a head.
    """
    width, height = size
    best, best_cost = None, float("inf")
    for top in range(MARGIN, max(MARGIN + 1, canvas[1] - height - MARGIN), 30):
        for left in range(MARGIN, max(MARGIN + 1, canvas[0] - width - MARGIN), 30):
            box = (left, top, left + width, top + height)
            # Reading order: each bubble starts lower than the last, and only sits to its left
            # once it is fully below it.
            if after and (top <= after[1] + 10 or (left < after[0] and top < after[3])):
                continue
            covered = sum(_overlap(box, item) for item in blocked)
            distance = abs(left + width / 2 - target[0]) + abs(top + height - target[1])
            cost = covered * 100 + distance + (0 if top + height <= target[1] else canvas[1])
            center = (left + width / 2, top + height / 2)
            own = math.dist(center, target)
            if any(math.dist(center, other) < own for other in others or []):
                cost += 2 * canvas[1] + 100 * width * height
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


def _cover(
    image: Image.Image, size: tuple[int, int], heads: dict[str, list[float]]
) -> tuple[Image.Image, dict[str, Box]]:
    """Scale to fill `size`, cropping around the heads, and map their boxes to the result."""
    scale = max(size[0] / image.width, size[1] / image.height)
    scaled = image.resize((round(image.width * scale), round(image.height * scale)))
    boxes = [
        (b[0] * scaled.width, b[1] * scaled.height, b[2] * scaled.width, b[3] * scaled.height)
        for b in heads.values()
    ]
    center_x = sum(b[0] + b[2] for b in boxes) / (2 * len(boxes)) if boxes else scaled.width / 2
    center_y = sum(b[1] + b[3] for b in boxes) / (2 * len(boxes)) if boxes else scaled.height / 2
    left = int(min(max(center_x - size[0] / 2, 0), scaled.width - size[0]))
    top = int(min(max(center_y - size[1] / 2, 0), scaled.height - size[1]))
    cropped = scaled.crop((left, top, left + size[0], top + size[1]))
    mapped = {
        name.casefold(): (b[0] - left, b[1] - top, b[2] - left, b[3] - top) for name, b in zip(heads, boxes)
    }
    return cropped, mapped


def letter_panel(
    image_path: str,
    panel: ScriptPanel,
    shot: PanelSpec,
    out: Path,
    size: tuple[int, int] = (PANEL_WIDTH, 800),
    heads: dict[str, list[float]] | None = None,
) -> Path:
    """Letter at the panel's final width, so text is the same size on every panel."""
    image, head_boxes = _cover(Image.open(image_path).convert("RGB"), size, heads or {})
    draw = ImageDraw.Draw(image)
    font = _font()
    w, h = image.size
    # The gap keeps bubbles far enough from heads for a visible tail.
    blocked: list[Box] = [(b[0] - TAIL, b[1] - TAIL, b[2] + TAIL, b[3] + TAIL) for b in head_boxes.values()]
    if panel.caption:
        blocked.append((0, 0, w * 0.5, _draw_caption(draw, panel.caption, font) + MARGIN))
    positions = speaker_positions(shot)
    bubbles = []
    previous: Box | None = None
    for line in panel.dialogue:
        head = head_boxes.get(line.speaker.casefold())
        x = (head[0] + head[2]) / 2 if head else positions.get(line.speaker, 0.5) * w
        y = head[1] if head else h * 0.4
        wrapped, text_width, text_height = _text_box(draw, line.text, font)
        size = (text_width + 2 * PADDING, text_height + 2 * PADDING)
        others = [
            ((box[0] + box[2]) / 2, box[1]) for name, box in head_boxes.items() if name != line.speaker.casefold()
        ]
        box = _place(size, (w, h), (x, y), blocked, previous, others)
        previous = box
        blocked.append(box)
        bubbles.append((wrapped, box, _tail_tip(box, head, x, y)))
    # Last first, so a lower bubble's tail passes behind the bubbles above it.
    for wrapped, box, tip in reversed(bubbles):
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


def _gutter_box(slot: Slot) -> tuple[int, int, int, int]:
    """Pixel box for a slot, with a gutter inside the page margin."""
    usable_w, usable_h = PAGE_WIDTH - 2 * PAGE_MARGIN, PAGE_HEIGHT - 2 * PAGE_MARGIN
    left = PAGE_MARGIN + int(slot[0] * usable_w) + GUTTER // 2
    top = PAGE_MARGIN + int(slot[1] * usable_h) + GUTTER // 2
    return left, top, left + int(slot[2] * usable_w) - GUTTER, top + int(slot[3] * usable_h) - GUTTER


def compose_page(panels: list[Path], slots: list[Slot], out: Path) -> Path:
    page = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), PAPER)
    draw = ImageDraw.Draw(page)
    for path, slot in zip(panels, slots):
        box = _gutter_box(slot)
        page.paste(Image.open(path).resize((box[2] - box[0], box[3] - box[1])), box[:2])
        draw.rectangle(box, outline=INK, width=OUTLINE + 2)
    page.save(out)
    return out


def _blocked_art(folder: Path, panel: PanelResult) -> str:
    """Stand-in art for a panel with no image, so the rest of the page can still be read."""
    path = folder / f"{panel.panel_id}-blocked.png"
    image = Image.new("RGB", (PANEL_WIDTH, 800), (225, 220, 210))
    draw = ImageDraw.Draw(image)
    wrapped = "\n".join(textwrap.wrap(f"[No image] {panel.description}", width=40))
    draw.multiline_text((600, 400), wrapped, fill=INK, font=_font(), anchor="mm", align="center")
    image.save(path)
    return str(path)


def letter_chapter(run: ChapterRun, folder: Path) -> tuple[list[str], str]:
    """Letter every panel, build the pages, and export a PDF. Returns (pages, pdf path)."""
    folder.mkdir(exist_ok=True)
    scripted = {panel.panel_id: panel for panel in run.script.panels}
    shots = {shot.panel_id: shot for shot in run.visual_plan.panels}
    templates = {layout.page: layout.template for layout in run.visual_plan.layouts}
    pages = []
    for number in sorted({panel.page for panel in run.panels}):
        on_page = [panel for panel in run.panels if panel.page == number]
        slots = slots_for(templates.get(number, ""), len(on_page))
        lettered = []
        for panel, slot in zip(on_page, slots):
            box = _gutter_box(slot)
            lettered.append(
                letter_panel(
                    panel.best_image or _blocked_art(folder, panel), scripted[panel.panel_id], shots[panel.panel_id],
                    folder / f"{panel.panel_id}.png", (box[2] - box[0], box[3] - box[1]), panel.heads,
                )
            )
        pages.append(compose_page(lettered, slots, folder / f"page-{number}.png"))
    pdf = folder / "chapter.pdf"
    images = [Image.open(page).convert("RGB") for page in pages]
    images[0].save(pdf, save_all=True, append_images=images[1:])
    return [str(page) for page in pages], str(pdf)
