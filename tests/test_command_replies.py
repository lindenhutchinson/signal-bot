from signal_chatbot.commands import replies
from signal_chatbot.state import Directive, Disclaimer


def _directive(text: str, *, created_at: int = 1781274720000) -> Directive:
    return Directive(
        kind="patch", author_name="Alice", author_number="+1", text=text, created_at=created_at
    )


def test_format_list_numbers_entries_with_author_and_time() -> None:
    out = replies.format_list("Patches", [_directive("no puns"), _directive("haiku only")])

    assert out == (
        "Patches:\n"
        '1. "no puns" — Alice, 2026-06-12 14:32\n'
        '2. "haiku only" — Alice, 2026-06-12 14:32'
    )


def test_format_list_empty_says_none_yet() -> None:
    assert replies.format_list("Rules", []) == "No rules yet."


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

    out = replies.format_disclaimers(disclaimers)

    assert out == 'Disclaimers:\n1. [2026-06-12 14:32] "kidding" — re: "you are doomed"'


def test_format_disclaimers_empty() -> None:
    assert replies.format_disclaimers([]) == "No disclaimers yet."


def test_help_text_lists_every_command() -> None:
    for token in (
        "@patch",
        "@rule",
        "@lore",
        "@name",
        "@patchlist",
        "@rulelist",
        "@lorelist",
        "@disclaimers",
        "@reset",
        "@clear",
        "@help",
    ):
        assert token in replies.HELP_TEXT
