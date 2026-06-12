from signal_chatbot.history import StoredMessage
from signal_chatbot.llm.prompt import BOT_SENDER, build_messages
from signal_chatbot.state import Directive, DirectiveSet, LoggedCommand


def _directive(kind: str, text: str) -> Directive:
    return Directive(
        kind=kind, author_name="Alice", author_number="+1", text=text, created_at=1781274720000
    )


def test_directive_sections_are_injected_into_the_system_message() -> None:
    directives = DirectiveSet(
        patches=[_directive("patch", "be brief")],
        rules=[_directive("rule", "no puns")],
        lore=[_directive("lore", "Dave fears geese")],
    )

    messages = build_messages("BASE", [], directives=directives, command_log=[])
    system = messages[0]["content"]

    assert system.startswith("BASE")
    assert "## Rules" in system and "- no puns" in system
    assert "## Lore" in system and "- Dave fears geese" in system
    assert "## Patches" in system and "- be brief" in system


def test_empty_sections_are_omitted() -> None:
    directives = DirectiveSet(patches=[], rules=[_directive("rule", "no puns")], lore=[])

    system = build_messages("BASE", [], directives=directives, command_log=[])[0]["content"]

    assert "## Rules" in system
    assert "## Lore" not in system
    assert "## Patches" not in system


def test_command_activity_renders_without_arguments() -> None:
    log = [LoggedCommand(author_name="Bob", command="@reset", created_at=1781274720000)]

    system = build_messages("BASE", [], directives=None, command_log=log)[0]["content"]

    assert "## Recent command activity" in system
    assert "Bob · @reset · 2026-06-12 14:32" in system


def test_no_directives_or_log_leaves_base_prompt_unchanged() -> None:
    assert build_messages("BASE", [])[0]["content"] == "BASE"


def test_system_prompt_is_the_stable_first_message() -> None:
    messages = build_messages("You are Bot.", [])

    assert messages[0] == {"role": "system", "content": "You are Bot."}


def test_human_messages_are_user_role_and_labelled_by_sender() -> None:
    history = [StoredMessage(sender="Alice", text="hello", timestamp=1)]

    messages = build_messages("sys", history)

    assert messages[1] == {"role": "user", "content": "Alice: hello"}


def test_bot_messages_map_to_assistant_role_without_label() -> None:
    history = [
        StoredMessage(sender="Alice", text="hi @bot", timestamp=1),
        StoredMessage(sender=BOT_SENDER, text="Hello Alice!", timestamp=2),
    ]

    messages = build_messages("sys", history)

    assert messages[1]["role"] == "user"
    assert messages[2] == {"role": "assistant", "content": "Hello Alice!"}
