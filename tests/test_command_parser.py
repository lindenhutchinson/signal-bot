from signal_chatbot.commands.parser import Command, CommandName, parse


def test_parses_command_with_argument() -> None:
    assert parse("@rule no more puns") == Command(CommandName.RULE, "no more puns")


def test_parses_name_command() -> None:
    assert parse("@name Greg") == Command(CommandName.NAME, "Greg")


def test_command_word_is_case_insensitive() -> None:
    assert parse("@RESET") == Command(CommandName.RESET, "")


def test_leading_and_trailing_whitespace_is_trimmed() -> None:
    assert parse("   @lore   Dave fears geese   ") == Command(CommandName.LORE, "Dave fears geese")


def test_rulelist_is_not_confused_with_rule() -> None:
    assert parse("@rulelist") == Command(CommandName.RULELIST, "")
    assert parse("@rule list") == Command(CommandName.RULE, "list")


def test_profiles_parses_with_no_argument() -> None:
    assert parse("@profiles") == Command(CommandName.PROFILES, "")


def test_forget_parses_with_and_without_a_name() -> None:
    assert parse("@forget") == Command(CommandName.FORGET, "")
    assert parse("@forget Dave") == Command(CommandName.FORGET, "Dave")


def test_non_command_text_returns_none() -> None:
    assert parse("just chatting") is None
    assert parse("@bot what's up") is None
    assert parse("@everyone hello") is None
    assert parse("") is None


def test_command_must_be_start_anchored() -> None:
    assert parse("hey @reset now") is None
