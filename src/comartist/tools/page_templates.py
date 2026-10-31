"""Comic page layouts. Each slot is (left, top, width, height) as fractions of the page."""

PAGE_WIDTH = 2000
PAGE_HEIGHT = 3000

Slot = tuple[float, float, float, float]

TEMPLATES: dict[str, list[Slot]] = {
    "hero_top": [(0, 0, 1, 0.56), (0, 0.56, 0.5, 0.44), (0.5, 0.56, 0.5, 0.44)],
    "tall_left": [(0, 0, 0.52, 1), (0.52, 0, 0.48, 0.5), (0.52, 0.5, 0.48, 0.5)],
    "three_strips": [(0, 0, 1, 0.3), (0, 0.3, 1, 0.3), (0, 0.6, 1, 0.4)],
    "hero_strip_pair": [(0, 0, 1, 0.46), (0, 0.46, 1, 0.2), (0, 0.66, 0.4, 0.34), (0.4, 0.66, 0.6, 0.34)],
    "offset_grid": [(0, 0, 0.62, 0.5), (0.62, 0, 0.38, 0.5), (0, 0.5, 0.38, 0.5), (0.38, 0.5, 0.62, 0.5)],
    "stepped_strips": [
        (0, 0, 1, 0.42), (0.07, 0.42, 0.86, 0.15), (0.14, 0.57, 0.86, 0.15),
        (0, 0.72, 0.4, 0.28), (0.4, 0.72, 0.6, 0.28),
    ],
    "tall_stack": [
        (0, 0, 0.56, 0.6), (0.56, 0, 0.44, 0.3), (0.56, 0.3, 0.44, 0.3),
        (0, 0.6, 0.5, 0.4), (0.5, 0.6, 0.5, 0.4),
    ],
    "six_varied": [
        (0, 0, 0.6, 0.33), (0.6, 0, 0.4, 0.33), (0, 0.33, 1, 0.2),
        (0, 0.53, 0.4, 0.47), (0.4, 0.53, 0.6, 0.235), (0.4, 0.765, 0.6, 0.235),
    ],
    "six_grid": [(x, y, 0.5, 1 / 3) for y in (0, 1 / 3, 2 / 3) for x in (0, 0.5)],
}


def templates_for(count: int) -> list[str]:
    return [name for name, slots in TEMPLATES.items() if len(slots) == count]


def slots_for(template: str, count: int) -> list[Slot]:
    """The template's slots, or even rows when it does not fit `count` panels."""
    if len(TEMPLATES.get(template, [])) == count:
        return TEMPLATES[template]
    named = templates_for(count)
    return TEMPLATES[named[0]] if named else [(0, i / count, 1, 1 / count) for i in range(count)]


def image_size(slot: Slot) -> str:
    """The generation size closest to the slot's shape, so cropping loses little."""
    aspect = slot[2] * PAGE_WIDTH / (slot[3] * PAGE_HEIGHT)
    if aspect > 1.2:
        return "1536x1024"
    return "1024x1536" if aspect < 0.85 else "1024x1024"
