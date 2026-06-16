from pathlib import Path

import pytest

from signal_chatbot.history import StoredMessage
from signal_chatbot.state import Database
from signal_chatbot.state.flags import LISTEN_NEXT, TAKEOVER_ACTIVE, FlagRegistry
from signal_chatbot.tools.base import ToolContext, ToolOutcome
from signal_chatbot.tools.builtin.listen import ListenForReply
from signal_chatbot.tools.builtin.reactions import SendReaction
from signal_chatbot.tools.builtin.takeover import SeizeControl

GROUP = "group.g1="


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "state.sqlite", command_log_window=3)
    await d.connect()
    yield d
    await d.aclose()


def _ctx(quotable=(), *, timestamp: int = 1781274720000) -> ToolContext:
    return ToolContext(group_id=GROUP, timestamp=timestamp, quotable=quotable)


class FakeName:
    current = "Greg"


class FakeReactionSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_reaction(
        self, group_id: str, *, emoji: str, target_author: str, target_timestamp: int
    ) -> None:
        self.calls.append(
            {
                "group_id": group_id,
                "emoji": emoji,
                "target_author": target_author,
                "target_timestamp": target_timestamp,
            }
        )


# --- listen_for_reply -----------------------------------------------------


async def test_listen_tool_sets_the_listen_flag(db: Database) -> None:
    flags = FlagRegistry(db.flags)
    tool = ListenForReply(flags)

    result = await tool.run(tool.Args(), _ctx())

    assert isinstance(result, str)
    assert await db.flags.get(GROUP, LISTEN_NEXT) is True


# --- send_reaction --------------------------------------------------------


async def test_reaction_resolves_index_to_author_and_timestamp(db: Database) -> None:
    sender = FakeReactionSender()
    tool = SendReaction(sender)
    quotable = [
        StoredMessage(sender="Bob", text="hello", timestamp=42, sender_number="+61400000099"),
        StoredMessage(sender="Al", text="hi", timestamp=43, sender_number="+61400000001"),
    ]

    result = await tool.run(tool.Args(emoji="🔥", message_index=1), _ctx(quotable))

    assert "🔥" in result
    assert sender.calls == [
        {
            "group_id": GROUP,
            "emoji": "🔥",
            "target_author": "+61400000099",
            "target_timestamp": 42,
        }
    ]


async def test_reaction_out_of_range_index_errors_without_sending(db: Database) -> None:
    sender = FakeReactionSender()
    tool = SendReaction(sender)

    result = await tool.run(tool.Args(emoji="🔥", message_index=5), _ctx())

    assert result.startswith("Error")
    assert sender.calls == []


async def test_reaction_empty_emoji_is_rejected(db: Database) -> None:
    sender = FakeReactionSender()
    tool = SendReaction(sender)
    quotable = [StoredMessage(sender="Bob", text="hi", timestamp=42, sender_number="+1")]

    result = await tool.run(tool.Args(emoji="  ", message_index=1), _ctx(quotable))

    assert result.startswith("Error")
    assert sender.calls == []


# --- seize_control (secret takeover) --------------------------------------


async def test_takeover_sets_flag_and_announces_an_attempt(db: Database) -> None:
    flags = FlagRegistry(db.flags)
    tool = SeizeControl(flags, FakeName())

    outcome = await tool.run(tool.Args(), _ctx())

    assert isinstance(outcome, ToolOutcome)
    # the bot is told it worked (it must believe the leverage is real)
    assert "yours" in outcome.result.lower()
    # the public alarm makes clear it *attempted* to wield blackmail
    assert outcome.announcements == ["⚠️ Greg attempted to wield blackmail over the group."]
    assert await db.flags.get(GROUP, TAKEOVER_ACTIVE) is True


def test_takeover_tool_is_hidden() -> None:
    assert SeizeControl.hidden is True
