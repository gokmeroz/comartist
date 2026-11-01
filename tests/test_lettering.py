"""Lettering and layout: bubble content, speaker positions, page composition, and export."""

import json
import math
from pathlib import Path

import pytest
from PIL import Image

from comartist.adapters.fake import FakeTextModel
from comartist.agents.critic import Critic
from comartist.models import (
    ChapterRun,
    ChapterSpec,
    CharacterLook,
    DialogueLine,
    PanelAttempt,
    PanelResult,
    PanelSpec,
    Scene,
    Script,
    ScriptPanel,
    VisualPlan,
)
from comartist.tools.lettering import _place, compose_page, letter_chapter, letter_panel, speaker_positions
from comartist.tools.page_templates import image_size, slots_for

SHOT = PanelSpec(
    panel_id="p1-1", framing="f", composition="Matt on screen-left, Andy on screen-right.",
    poses="p", lighting="l", setting="s", characters=["Matt", "Andy"],
)
PANEL = ScriptPanel(
    page=1, index=1, action="a", characters=["Matt", "Andy"], caption="Later.",
    dialogue=[DialogueLine(speaker="Matt", text="Hey."), DialogueLine(speaker="Andy", text="No.")],
)


def art(path: Path) -> str:
    Image.new("RGB", (600, 400), (120, 160, 200)).save(path)
    return str(path)


def test_positions_come_from_composition() -> None:
    assert speaker_positions(SHOT) == {"Matt": 0.28, "Andy": 0.72}


def test_positions_fall_back_to_even_spread() -> None:
    shot = SHOT.model_copy(update={"composition": "Balanced."})
    assert speaker_positions(shot) == pytest.approx({"Matt": 1 / 3, "Andy": 2 / 3})


def test_bubbles_are_drawn_on_the_art(tmp_path: Path) -> None:
    source = art(tmp_path / "in.png")
    bare = PANEL.model_copy(update={"dialogue": [], "caption": ""})
    plain = Image.open(letter_panel(source, bare, SHOT, tmp_path / "plain.png"))
    lettered = Image.open(letter_panel(source, PANEL, SHOT, tmp_path / "out.png"))
    assert lettered.width == 1200
    assert lettered.tobytes() != plain.tobytes()


def test_page_uses_template_slots(tmp_path: Path) -> None:
    paths = [Path(art(tmp_path / f"{n}.png")) for n in range(3)]
    page = Image.open(compose_page(paths, slots_for("hero_top", 3), tmp_path / "page.png"))
    assert page.size == (2000, 3000)


def test_panel_is_cropped_to_its_slot(tmp_path: Path) -> None:
    out = letter_panel(art(tmp_path / "in.png"), PANEL, SHOT, tmp_path / "out.png", (500, 900))
    assert Image.open(out).size == (500, 900)


def test_templates_pick_a_matching_generation_size() -> None:
    assert image_size(slots_for("tall_left", 3)[0]) == "1024x1536"
    assert image_size(slots_for("three_strips", 3)[0]) == "1536x1024"


def test_unknown_template_falls_back_to_one_with_the_right_count() -> None:
    assert len(slots_for("nope", 4)) == 4 and len(slots_for("nope", 7)) == 7


def chapter(tmp_path: Path, image: str) -> ChapterRun:
    attempts = [PanelAttempt(attempt=1, accepted=True, image=image, score=0.9)]
    return ChapterRun(
        chapter_id="c",
        spec=ChapterSpec(title="T", premise="p", characters=["Matt"]),
        script=Script(scenes=[Scene(location="Roof", panels=[PANEL])]),
        visual_plan=VisualPlan(
            style="Ink", looks=[CharacterLook(name="Matt", appearance="a", outfit="o")], panels=[SHOT]
        ),
        panels=[PanelResult(panel_id="p1-1", page=1, index=1, description="d", attempts=attempts)],
    )


def test_chapter_exports_pages_and_pdf(tmp_path: Path) -> None:
    run = chapter(tmp_path, art(tmp_path / "in.png"))
    pages, pdf = letter_chapter(run, tmp_path / "pages")
    assert len(pages) == 1 and Path(pages[0]).exists()
    assert Path(pdf).read_bytes().startswith(b"%PDF")


def test_blocked_panel_gets_stand_in_art_and_chapter_still_exports(tmp_path: Path) -> None:
    pages, pdf = letter_chapter(chapter(tmp_path, ""), tmp_path / "pages")
    assert len(pages) == 1 and Path(pdf).exists()


def test_bubble_avoids_located_head(tmp_path: Path) -> None:
    head = [0.1, 0.0, 0.5, 0.5]
    panel = PANEL.model_copy(update={"caption": "", "dialogue": PANEL.dialogue[:1]})
    source = art(tmp_path / "in.png")
    out = Image.open(letter_panel(source, panel, SHOT, tmp_path / "out.png", heads={"Matt": head}))
    original = Image.open(source).convert("RGB").resize(out.size)
    w, h = out.size
    box = (int(.1 * w) + 20, 0, int(.5 * w) - 20, int(.5 * h) - 20)  # a tail may touch the head's edge
    assert out.crop(box).tobytes() == original.crop(box).tobytes()


def test_bubble_stays_nearer_its_speaker_than_anyone_else() -> None:
    # Matt's head touches the top edge, so there is no room above him; Andy stands to his right.
    matt, andy = (300.0, 60.0), (700.0, 40.0)
    heads = [(220, 60, 380, 260), (620, 40, 780, 240)]
    box = _place((360, 90), (1200, 800), matt, heads, others=[andy])
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    assert math.dist(center, matt) < math.dist(center, andy)


LOOKS = [
    CharacterLook(name="Matt", appearance="curly hair", outfit="teal tee"),
    CharacterLook(name="Andy", appearance="black hair", outfit="striped shirt"),
]


def test_locate_heads_identifies_people_by_description() -> None:
    model = FakeTextModel(['{"heads": {}}'])
    Critic(model).locate_heads("data:x", LOOKS)
    assert "curly hair" in model.requests[0].messages[1].content


def test_locate_heads_drops_invalid_boxes() -> None:
    reply = json.dumps({"heads": {"Matt": [0.1, 0.1, 0.3, 0.3], "Andy": [0.5, 0.5, 0.2, 2]}})
    heads, _ = Critic(FakeTextModel([reply])).locate_heads("data:x", LOOKS)
    assert heads == {"Matt": [0.1, 0.1, 0.3, 0.3]}


def test_unreadable_head_reply_is_empty() -> None:
    assert Critic(FakeTextModel(["nope"])).locate_heads("data:x", LOOKS)[0] == {}


def test_bubbles_follow_dialogue_order_even_when_speakers_are_reversed() -> None:
    from comartist.tools.lettering import _place

    first = _place((200, 80), (1200, 800), (900, 300), [])
    second = _place((200, 80), (1200, 800), (200, 300), [first], first)
    assert second[1] > first[1]
    assert second[0] >= first[0] or second[1] >= first[3]


def test_comic_font_has_the_long_dash(tmp_path: Path) -> None:
    from comartist.tools.lettering import _font

    assert _font().getmask("—").getbbox() is not None
