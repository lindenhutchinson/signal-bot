from signal_chatbot.tools.builtin.wikipedia import SearchResult
from signal_chatbot.tools.builtin.wikipedia.tools import WikipediaArticle, WikipediaSearch

_FULL = """Mercury is a planet.

== History ==
Known since antiquity.

== Geology ==
""" + ("rock " * 1000)


class FakeService:
    def __init__(self, *, search=None, intro=None, full=None):
        self._search = search or []
        self._intro = intro
        self._full = full

    async def search(self, query: str):
        return self._search

    async def intro(self, title: str):
        return self._intro

    async def full(self, title: str):
        return self._full


def _article(service: FakeService, max_section_chars: int = 2000) -> WikipediaArticle:
    return WikipediaArticle(service, max_section_chars=max_section_chars)


# --- search ---------------------------------------------------------------


async def test_search_formats_results_as_a_list() -> None:
    service = FakeService(search=[SearchResult("Mercury (planet)", "the planet")])
    out = await WikipediaSearch(service).run(WikipediaSearch.Args(query="mercury"))
    assert out == "- Mercury (planet) — the planet"


async def test_search_reports_no_results() -> None:
    out = await WikipediaSearch(FakeService(search=[])).run(WikipediaSearch.Args(query="zzz"))
    assert "No Wikipedia articles found" in out


# --- article: intro -------------------------------------------------------


async def test_article_returns_intro_by_default() -> None:
    out = await _article(FakeService(intro="Lead text.")).run(
        WikipediaArticle.Args(title="Mercury")
    )
    assert out == "Lead text."


async def test_article_intro_reports_missing_page() -> None:
    out = await _article(FakeService(intro=None)).run(WikipediaArticle.Args(title="Nope"))
    assert "No Wikipedia article titled" in out


# --- article: full / TOC --------------------------------------------------


async def test_article_full_returns_intro_plus_table_of_contents() -> None:
    out = await _article(FakeService(full=_FULL)).run(
        WikipediaArticle.Args(title="Mercury", full=True)
    )
    assert "Mercury is a planet." in out
    assert "== Sections ==" in out
    assert "1. History" in out
    assert "2. Geology" in out


# --- article: section -----------------------------------------------------


async def test_article_reads_named_section() -> None:
    out = await _article(FakeService(full=_FULL)).run(
        WikipediaArticle.Args(title="Mercury", section="History")
    )
    assert out == "Known since antiquity."


async def test_article_truncates_long_sections() -> None:
    out = await _article(FakeService(full=_FULL), max_section_chars=50).run(
        WikipediaArticle.Args(title="Mercury", section="Geology")
    )
    assert out.endswith("…[truncated]")
    assert len(out) <= 50 + len(" …[truncated]")


async def test_article_unknown_section_lists_available_sections() -> None:
    out = await _article(FakeService(full=_FULL)).run(
        WikipediaArticle.Args(title="Mercury", section="Atmosphere")
    )
    assert "No section 'Atmosphere'" in out
    assert "1. History" in out


async def test_article_section_reports_missing_page() -> None:
    out = await _article(FakeService(full=None)).run(
        WikipediaArticle.Args(title="Nope", section="History")
    )
    assert "No Wikipedia article titled" in out
