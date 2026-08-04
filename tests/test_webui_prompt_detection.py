from web_ui.server import _looks_like_subprocess_prompt


def test_informational_colon_line_is_not_treated_as_prompt() -> None:
    line = "Found a valid torrent with preferred piece size from client search:"

    assert not _looks_like_subprocess_prompt(line)  # noqa: S101


def test_explicit_input_prompt_is_detected() -> None:
    assert _looks_like_subprocess_prompt("Please enter the TMDb ID:")  # noqa: S101
    assert _looks_like_subprocess_prompt("Upload to all? (y/N)")  # noqa: S101
