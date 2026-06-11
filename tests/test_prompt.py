from signal_chatbot.history import StoredMessage
from signal_chatbot.llm.prompt import BOT_SENDER, build_messages


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
