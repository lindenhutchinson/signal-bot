from signal_chatbot.timefmt import format_timestamp


def test_formats_signal_millisecond_timestamp_in_utc() -> None:
    # 2026-06-12 14:32:00 UTC == 1781274720000 ms
    assert format_timestamp(1781274720000) == "2026-06-12 14:32"
