"""Lettering and layout: bubble content, speaker positions, page composition, and export."""

import json
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
from comartist.tools.lettering import compose_page, letter_chapter, letter_panel, speaker_positions
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


def test_missing_image_is_an_error_not_a_blank_panel(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="p1-1"):
        letter_chapter(chapter(tmp_path, ""), tmp_path / "pages")


def test_bubble_avoids_located_head(tmp_path: Path) -> None:
    head = [0.1, 0.0, 0.5, 0.5]
    panel = PANEL.model_copy(update={"caption": "", "dialogue": PANEL.dialogue[:1]})
    source = art(tmp_path / "in.png")
    out = Image.open(letter_panel(source, panel, SHOT, tmp_path / "out.png", heads={"Matt": head}))
    original = Image.open(source).convert("RGB").resize(out.size)
    w, h = out.size
    box = (int(.1 * w) + 20, 0, int(.5 * w) - 20, int(.5 * h) - 20)  # a tail may touch the head's edge
    assert out.crop(box).tobytes() == original.crop(box).tobytes()


def test_locate_heads_drops_invalid_boxes() -> None:
    reply = json.dumps({"heads": {"Matt": [0.1, 0.1, 0.3, 0.3], "Andy": [0.5, 0.5, 0.2, 2]}})
    heads, _ = Critic(FakeTextModel([reply])).locate_heads("data:x", ["Matt", "Andy"])
    assert heads == {"Matt": [0.1, 0.1, 0.3, 0.3]}


def test_unreadable_head_reply_is_empty() -> None:
    assert Critic(FakeTextModel(["nope"])).locate_heads("data:x", ["Matt"])[0] == {}
