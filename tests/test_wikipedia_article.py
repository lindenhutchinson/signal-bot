from signal_chatbot.tools.builtin.wikipedia import article

_SAMPLE = """Mercury is the smallest planet.
It is closest to the Sun.

== History ==
Known since antiquity.

=== Naming ===
Named for the Roman god.

== Exploration ==
Two spacecraft have visited."""


def test_parse_splits_intro_from_sections() -> None:
    parsed = article.parse(_SAMPLE)

    assert parsed.intro == "Mercury is the smallest planet.\nIt is closest to the Sun."
    assert [(s.index, s.level, s.title) for s in parsed.sections] == [
        (1, 1, "History"),
        (2, 2, "Naming"),
        (3, 1, "Exploration"),
    ]
    assert parsed.sections[0].text == "Known since antiquity."
    assert parsed.sections[1].text == "Named for the Roman god."


def test_parse_handles_article_with_no_sections() -> None:
    parsed = article.parse("Just an intro, nothing else.")

    assert parsed.intro == "Just an intro, nothing else."
    assert parsed.sections == []


def test_table_of_contents_is_indented_by_level() -> None:
    toc = article.table_of_contents(article.parse(_SAMPLE))

    assert toc == "1. History\n  2. Naming\n3. Exploration"


def test_table_of_contents_for_sectionless_article() -> None:
    assert article.table_of_contents(article.parse("intro only")) == "(no sections)"


def test_find_section_by_index() -> None:
    parsed = article.parse(_SAMPLE)
    assert article.find_section(parsed, "2").title == "Naming"


def test_find_section_by_title_is_case_insensitive() -> None:
    parsed = article.parse(_SAMPLE)
    assert article.find_section(parsed, "exploration").title == "Exploration"


def test_find_section_returns_none_for_unknown_selector() -> None:
    parsed = article.parse(_SAMPLE)
    assert article.find_section(parsed, "Geology") is None
    assert article.find_section(parsed, "99") is None
