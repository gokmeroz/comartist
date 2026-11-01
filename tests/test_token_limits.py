from comartist.agents.parsing import chapter_max_tokens


def test_short_chapters_keep_the_floor() -> None:
    assert chapter_max_tokens(8000, 1) == 8000
    assert chapter_max_tokens(16000, 4) == 16000


def test_long_chapters_scale_with_pages() -> None:
    assert chapter_max_tokens(8000, 12) == 48000
