from zoneinfo import ZoneInfo

from signal_chatbot.history import StoredMessage
from signal_chatbot.llm.prompt import BOT_SENDER, build_messages
from signal_chatbot.state import Directive, DirectiveSet, LoggedCommand, Profile

SYDNEY = ZoneInfo("Australia/Sydney")


def _directive(kind: str, text: str) -> Directive:
    return Directive(
        kind=kind, author_name="Alice", author_number="+1", text=text, created_at=1781274720000
    )


def test_directive_sections_are_injected_into_the_system_message() -> None:
    directives = DirectiveSet(
        rules=[_directive("rule", "no puns")],
        lore=[_directive("lore", "Dave fears geese")],
    )

    messages = build_messages("BASE", [], timezone=SYDNEY, directives=directives, command_log=[])
    system = messages[0]["content"]

    assert system.startswith("BASE")
    assert "## Rules" in system and "- no puns" in system
    assert "## Lore" in system and "- Dave fears geese" in system


def test_empty_sections_are_omitted() -> None:
    directives = DirectiveSet(rules=[_directive("rule", "no puns")], lore=[])

    system = build_messages("BASE", [], timezone=SYDNEY, directives=directives, command_log=[])[0][
        "content"
    ]

    assert "## Rules" in system
    assert "## Lore" not in system
    assert "## Patches" not in system


def test_command_activity_renders_without_arguments() -> None:
    log = [LoggedCommand(author_name="Bob", command="@reset", created_at=1781274720000)]

    system = build_messages("BASE", [], timezone=SYDNEY, directives=None, command_log=log)[0][
        "content"
    ]

    assert "## Recent command activity" in system
    assert "Bob · @reset · 2026-06-13 00:32 AEST" in system


def test_profiles_section_renders_subjects_and_notes() -> None:
    profiles = [
        Profile(subject="Dave", notes=["fears geese", "owns a boat"]),
        Profile(subject="Alice", notes=["loves cats"]),
    ]

    system = build_messages("BASE", [], timezone=SYDNEY, profiles=profiles)[0]["content"]

    assert "## What you know about people" in system
    assert "Dave:" in system
    assert "- fears geese" in system and "- owns a boat" in system
    assert "Alice:" in system and "- loves cats" in system


def test_profiles_section_is_absent_when_empty_or_none() -> None:
    none_system = build_messages("BASE", [], timezone=SYDNEY, profiles=None)[0]["content"]
    empty_system = build_messages("BASE", [], timezone=SYDNEY, profiles=[])[0]["content"]

    assert "## What you know about people" not in none_system
    assert "## What you know about people" not in empty_system


def test_base_prompt_is_followed_by_the_output_format_contract() -> None:
    system = build_messages("BASE", [], timezone=SYDNEY)[0]["content"]

    assert system.startswith("BASE")
    assert "## How you reply" in system
    assert "final_answer" in system
    assert "ethical_disclaimer" in system


def test_system_message_is_first_and_starts_with_the_base_prompt() -> None:
    messages = build_messages("You are Bot.", [], timezone=SYDNEY)

    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith("You are Bot.")


def test_human_messages_are_user_role_labelled_by_sender_and_timestamped() -> None:
    history = [StoredMessage(sender="Alice", text="hello", timestamp=1781274720000)]

    messages = build_messages("sys", history, timezone=SYDNEY)

    assert messages[1] == {"role": "user", "content": "[2026-06-13 00:32 AEST] Alice: hello"}


def test_bot_messages_map_to_assistant_role_unstamped_and_unlabelled() -> None:
    history = [
        StoredMessage(sender="Alice", text="hi @bot", timestamp=1781274720000),
        StoredMessage(sender=BOT_SENDER, text="Hello Alice!", timestamp=1781274720000),
    ]

    messages = build_messages("sys", history, timezone=SYDNEY)

    # User turns keep the [timestamp] for context; the bot's own turns are replayed
    # exactly as sent (no stamp) so it doesn't learn to echo the date into its replies.
    assert messages[1] == {"role": "user", "content": "[2026-06-13 00:32 AEST] Alice: hi @bot"}
    assert messages[2] == {"role": "assistant", "content": "Hello Alice!"}
