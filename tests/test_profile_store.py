from pathlib import Path

import pytest

from signal_chatbot.state import Database


@pytest.fixture
async def profiles(tmp_path: Path):
    db = Database(tmp_path / "state.sqlite", command_log_window=3)
    await db.connect()
    yield db.profiles
    await db.aclose()


async def test_notes_aggregate_per_subject_subjects_by_first_seen_notes_oldest_first(
    profiles,
) -> None:
    await profiles.add_note("g1", subject="Dave", note="fears geese", created_at=1)
    await profiles.add_note("g1", subject="Alice", note="loves cats", created_at=2)
    await profiles.add_note("g1", subject="Dave", note="owns a boat", created_at=3)

    all_profiles = await profiles.all("g1")

    # subjects ordered by first-seen (Dave before Alice); notes oldest-first
    assert [p.subject for p in all_profiles] == ["Dave", "Alice"]
    assert all_profiles[0].notes == ["fears geese", "owns a boat"]
    assert all_profiles[1].notes == ["loves cats"]


async def test_profiles_are_isolated_per_group(profiles) -> None:
    await profiles.add_note("g1", subject="Dave", note="here", created_at=1)
    await profiles.add_note("g2", subject="Dave", note="there", created_at=1)

    assert [p.notes for p in await profiles.all("g1")] == [["here"]]
    assert [p.notes for p in await profiles.all("g2")] == [["there"]]


async def test_all_is_empty_for_an_unknown_group(profiles) -> None:
    assert await profiles.all("nobody") == []


async def test_clear_removes_only_the_target_group(profiles) -> None:
    await profiles.add_note("g1", subject="Dave", note="x", created_at=1)
    await profiles.add_note("g2", subject="Alice", note="y", created_at=1)

    await profiles.clear("g1")

    assert await profiles.all("g1") == []
    assert [p.subject for p in await profiles.all("g2")] == ["Alice"]


async def test_forget_deletes_one_subject_and_reports_a_match(profiles) -> None:
    await profiles.add_note("g1", subject="Dave", note="a", created_at=1)
    await profiles.add_note("g1", subject="Alice", note="b", created_at=2)

    matched = await profiles.forget("g1", "Dave")

    assert matched is True
    assert [p.subject for p in await profiles.all("g1")] == ["Alice"]


async def test_forget_reports_no_match_for_an_unknown_subject(profiles) -> None:
    await profiles.add_note("g1", subject="Dave", note="a", created_at=1)

    matched = await profiles.forget("g1", "Nobody")

    assert matched is False
    assert [p.subject for p in await profiles.all("g1")] == ["Dave"]
