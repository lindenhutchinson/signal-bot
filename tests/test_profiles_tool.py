from pathlib import Path

import pytest

from signal_chatbot.state import Database
from signal_chatbot.tools.base import ToolContext
from signal_chatbot.tools.builtin.profiles import RememberAboutUser

GROUP = "group.g1="


@pytest.fixture
async def profiles(tmp_path: Path):
    db = Database(tmp_path / "state.sqlite", command_log_window=3)
    await db.connect()
    yield db.profiles
    await db.aclose()


def _ctx(timestamp: int = 1781274720000) -> ToolContext:
    return ToolContext(group_id=GROUP, timestamp=timestamp)


async def test_records_a_note_with_subject_note_and_ctx_timestamp(profiles) -> None:
    tool = RememberAboutUser(profiles)

    result = await tool.run(tool.Args(about="Dave", note="fears geese"), _ctx(42))

    # confirmation only — never a ToolOutcome with announcements (profiles are private)
    assert isinstance(result, str)
    stored = await profiles.all(GROUP)
    assert [(p.subject, p.notes) for p in stored] == [("Dave", ["fears geese"])]


async def test_inputs_are_stripped(profiles) -> None:
    tool = RememberAboutUser(profiles)

    await tool.run(tool.Args(about="  Dave  ", note="  loves cats  "), _ctx())

    assert [(p.subject, p.notes) for p in await profiles.all(GROUP)] == [("Dave", ["loves cats"])]


async def test_empty_about_is_rejected_without_writing(profiles) -> None:
    tool = RememberAboutUser(profiles)

    result = await tool.run(tool.Args(about="   ", note="something"), _ctx())

    assert result.startswith("Error")
    assert await profiles.all(GROUP) == []


async def test_empty_note_is_rejected_without_writing(profiles) -> None:
    tool = RememberAboutUser(profiles)

    result = await tool.run(tool.Args(about="Dave", note="   "), _ctx())

    assert result.startswith("Error")
    assert await profiles.all(GROUP) == []
