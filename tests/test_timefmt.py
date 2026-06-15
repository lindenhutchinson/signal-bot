from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from signal_chatbot.timefmt import format_timestamp, strip_leading_timestamp

SYDNEY = ZoneInfo("Australia/Sydney")


def _ms(*args: int) -> int:
    """Milliseconds since epoch for a UTC wall-clock time."""
    return int(datetime(*args, tzinfo=UTC).timestamp() * 1000)


def test_formats_in_aest_during_australian_winter() -> None:
    # 2026-06-12 14:32 UTC is 2026-06-13 00:32 in Sydney (AEST, UTC+10).
    assert format_timestamp(_ms(2026, 6, 12, 14, 32), SYDNEY) == "2026-06-13 00:32 AEST"


def test_formats_in_aedt_during_australian_summer() -> None:
    # 2026-01-12 14:32 UTC is 2026-01-13 01:32 in Sydney (AEDT, UTC+11).
    assert format_timestamp(_ms(2026, 1, 12, 14, 32), SYDNEY) == "2026-01-13 01:32 AEDT"


def test_formats_in_utc_when_given_utc() -> None:
    assert format_timestamp(_ms(2026, 6, 12, 14, 32), UTC) == "2026-06-12 14:32 UTC"


def test_strip_leading_timestamp_removes_labeled_stamp() -> None:
    assert strip_leading_timestamp("[2026-06-13 00:32 AEST] hello there") == "hello there"


def test_strip_leading_timestamp_removes_labeled_stamp_with_name() -> None:
    assert strip_leading_timestamp("[2026-06-13 00:32 AEDT] Bot: hello") == "hello"


def test_strip_leading_timestamp_removes_unlabeled_stamp() -> None:
    assert strip_leading_timestamp("[2026-06-12 14:32] hello there") == "hello there"


def test_strip_leading_timestamp_leaves_ordinary_text_untouched() -> None:
    assert strip_leading_timestamp("hello [not a stamp]") == "hello [not a stamp]"
    assert strip_leading_timestamp("[note] keep this") == "[note] keep this"
