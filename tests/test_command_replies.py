from zoneinfo import ZoneInfo

from signal_chatbot.commands import replies
from signal_chatbot.state import Directive, Disclaimer, FinalWords, FlagView, Profile

SYDNEY = ZoneInfo("Australia/Sydney")


def _directive(text: str, *, created_at: int = 1781274720000) -> Directive:
    return Directive(
        kind="rule", author_name="Alice", author_number="+1", text=text, created_at=created_at
    )


def test_format_list_numbers_entries_with_author_and_no_timestamp() -> None:
    out = replies.format_list("Rules", [_directive("no puns"), _directive("haiku only")])

    assert out == ('Rules:\n1. "no puns" — Alice\n2. "haiku only" — Alice')
    assert "2026" not in out  # timestamps are gone


def test_format_list_empty_says_none_yet() -> None:
    assert replies.format_list("Rules", []) == "No rules yet."


def test_format_farewell_matches_required_shape() -> None:
    assert replies.format_farewell("Greg", "Trust no one named Dave.") == (
        "Final message from Greg:\nTrust no one named Dave."
    )


def test_format_name_set() -> None:
    assert replies.format_name_set("Greg") == "Name changed to 'Greg'."


def test_format_disclaimers_lists_only_the_aside_no_re_excerpt() -> None:
    disclaimers = [
        Disclaimer(message="you are doomed", disclaimer="kidding", created_at=1781274720000)
    ]

    out = replies.format_disclaimers(disclaimers, tz=SYDNEY)

    assert out == 'Disclaimers:\n1. [2026-06-13 00:32 AEST] "kidding"'
    assert "re:" not in out  # the accompanied-message excerpt is gone
    assert "doomed" not in out


def test_format_disclaimers_empty() -> None:
    assert replies.format_disclaimers([], tz=SYDNEY) == "No disclaimers yet."


def test_format_finalwords_lists_each_with_name_and_time() -> None:
    entries = [
        FinalWords(name="Greg", text="Beware Dave.", created_at=1781274720000),
        FinalWords(name="Mona", text="I warned you.", created_at=1781274720000),
    ]

    out = replies.format_finalwords(entries, tz=SYDNEY)

    assert out == (
        "Final words:\n"
        '[2026-06-13 00:32 AEST] Greg: "Beware Dave."\n'
        '[2026-06-13 00:32 AEST] Mona: "I warned you."'
    )


def test_format_finalwords_empty() -> None:
    assert replies.format_finalwords([], tz=SYDNEY) == "No final words yet."


def test_format_flags_shows_index_name_value_and_meaning() -> None:
    flags = [
        FlagView(0, "listen_next", False, "respond to the next message even if not @'d"),
        FlagView(1, "self_destruct_armed", True, "confirm_kill_self is unlocked"),
    ]

    out = replies.format_flags(flags)

    assert out.startswith("Flags:")
    assert "0  listen_next" in out and "= false" in out
    assert "1  self_destruct_armed" in out and "= true" in out
    assert "@flag <n> reset" in out


def test_format_flag_reset_and_no_such_flag() -> None:
    assert (
        replies.format_flag_reset(0, "listen_next") == "Flag 0 (listen_next) reset to its default."
    )
    assert replies.no_such_flag(9) == "There's no flag 9. See @flags."


def test_format_profiles_empty() -> None:
    assert replies.format_profiles([]) == "No profiles yet."


def test_format_profiles_lists_subjects_with_bulleted_notes() -> None:
    profiles = [
        Profile(subject="Dave", notes=["fears geese", "owns a boat"]),
        Profile(subject="Alice", notes=["loves cats"]),
    ]

    out = replies.format_profiles(profiles)

    assert out == ("Profiles:\nDave:\n  - fears geese\n  - owns a boat\nAlice:\n  - loves cats")


def test_forget_replies() -> None:
    assert replies.forgot_one("Dave") == "Forgotten everything about Dave. 🧽"
    assert replies.no_such_profile("Dave") == "I don't have anything on Dave."


def test_format_info_explains_help_lists_tools_and_notes_self_destruct() -> None:
    out = replies.format_info(
        [("current_time", "Check the current date and time."), ("web_search", "Search the web.")]
    )

    assert "@help" in out  # explains what @help is for
    assert "current_time — Check the current date and time." in out
    assert "web_search — Search the web." in out
    # the self-destruct ability lives outside the registry, so it is mentioned explicitly
    assert "end myself" in out


def test_help_text_lists_every_command() -> None:
    for token in (
        "@rule",
        "@lore",
        "@name",
        "@rulelist",
        "@lorelist",
        "@disclaimers",
        "@profiles",
        "@finalwords",
        "@flags",
        "@flag",
        "@forget",
        "@reset",
        "@lobotomy",
        "@help",
        "@info",
    ):
        assert token in replies.HELP_TEXT


def test_help_text_no_longer_lists_removed_commands() -> None:
    assert "@clear" not in replies.HELP_TEXT
    assert "@patch" not in replies.HELP_TEXT
