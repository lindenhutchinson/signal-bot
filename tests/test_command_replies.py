from zoneinfo import ZoneInfo

from signal_chatbot.commands import replies
from signal_chatbot.state import Directive, Disclaimer, Profile

SYDNEY = ZoneInfo("Australia/Sydney")


def _directive(text: str, *, created_at: int = 1781274720000) -> Directive:
    return Directive(
        kind="rule", author_name="Alice", author_number="+1", text=text, created_at=created_at
    )


def test_format_list_numbers_entries_with_author_and_time() -> None:
    out = replies.format_list("Rules", [_directive("no puns"), _directive("haiku only")], tz=SYDNEY)

    assert out == (
        "Rules:\n"
        '1. "no puns" — Alice, 2026-06-13 00:32 AEST\n'
        '2. "haiku only" — Alice, 2026-06-13 00:32 AEST'
    )


def test_format_list_empty_says_none_yet() -> None:
    assert replies.format_list("Rules", [], tz=SYDNEY) == "No rules yet."


def test_format_farewell_matches_required_shape() -> None:
    assert replies.format_farewell("Greg", "Trust no one named Dave.") == (
        "Final message from Greg:\nTrust no one named Dave."
    )


def test_format_name_set() -> None:
    assert replies.format_name_set("Greg") == "Name changed to 'Greg'."


def test_format_disclaimers_lists_aside_and_message_excerpt() -> None:
    disclaimers = [
        Disclaimer(message="you are doomed", disclaimer="kidding", created_at=1781274720000)
    ]

    out = replies.format_disclaimers(disclaimers, tz=SYDNEY)

    assert out == 'Disclaimers:\n1. [2026-06-13 00:32 AEST] "kidding" — re: "you are doomed"'


def test_format_disclaimers_empty() -> None:
    assert replies.format_disclaimers([], tz=SYDNEY) == "No disclaimers yet."


def test_format_profiles_empty() -> None:
    assert replies.format_profiles([]) == "No profiles yet."


def test_format_profiles_lists_subjects_with_bulleted_notes() -> None:
    profiles = [
        Profile(subject="Dave", notes=["fears geese", "owns a boat"]),
        Profile(subject="Alice", notes=["loves cats"]),
    ]

    out = replies.format_profiles(profiles)

    assert out == (
        "Profiles:\n"
        "Dave:\n"
        "  - fears geese\n"
        "  - owns a boat\n"
        "Alice:\n"
        "  - loves cats"
    )


def test_forget_replies() -> None:
    assert replies.forgot_one("Dave") == "Forgotten everything about Dave. 🧽"
    assert replies.no_such_profile("Dave") == "I don't have anything on Dave."


def test_help_text_lists_every_command() -> None:
    for token in (
        "@rule",
        "@lore",
        "@name",
        "@rulelist",
        "@lorelist",
        "@disclaimers",
        "@profiles",
        "@forget",
        "@reset",
        "@lobotomy",
        "@help",
    ):
        assert token in replies.HELP_TEXT


def test_help_text_no_longer_lists_removed_commands() -> None:
    assert "@clear" not in replies.HELP_TEXT
    assert "@patch" not in replies.HELP_TEXT
