"""Smoke test for the initial domain models."""

from comartist.models import ChapterBrief, Character, ComicState


def test_models_can_be_instantiated() -> None:
    character = Character(name="Matt", description="Visiting New York City.")
    brief = ChapterBrief(
        premise="Matt reunites with an old friend.",
        hard_constraints=["They meet near NYU."],
        soft_preferences=["Nostalgic tone."],
        creative_freedom=["Choose the opening scene."],
    )
    state = ComicState(chapter_brief=brief, characters=[character])

    assert state.chapter_brief == brief
    assert state.characters == [character]
    assert brief.hard_constraints == ["They meet near NYU."]
    assert brief.soft_preferences == ["Nostalgic tone."]
    assert brief.creative_freedom == ["Choose the opening scene."]
    assert state.story_outline == ""
    assert state.script == ""
    assert state.revision_count == 0
