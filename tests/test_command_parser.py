from signal_chatbot.commands.parser import Command, CommandName, parse


def test_parses_command_with_argument() -> None:
    assert parse("@patch no more puns") == Command(CommandName.PATCH, "no more puns")


def test_command_word_is_case_insensitive() -> None:
    assert parse("@RESET") == Command(CommandName.RESET, "")


def test_leading_and_trailing_whitespace_is_trimmed() -> None:
    assert parse("   @lore   Dave fears geese   ") == Command(CommandName.LORE, "Dave fears geese")


def test_patchlist_is_not_confused_with_patch() -> None:
    assert parse("@patchlist") == Command(CommandName.PATCHLIST, "")
    assert parse("@patch list") == Command(CommandName.PATCH, "list")


def test_non_command_text_returns_none() -> None:
    assert parse("just chatting") is None
    assert parse("@bot what's up") is None
    assert parse("@everyone hello") is None
    assert parse("") is None


def test_command_must_be_start_anchored() -> None:
    assert parse("hey @reset now") is None
