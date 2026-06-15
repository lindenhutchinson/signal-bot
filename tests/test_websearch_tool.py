from signal_chatbot.tools.base import ToolContext
from signal_chatbot.tools.builtin.websearch import SearchHit, WebSearch

_CTX = ToolContext(group_id="g1", timestamp=0)


class FakeClient:
    def __init__(self, hits: list[SearchHit]):
        self._hits = hits

    async def search(self, query: str) -> list[SearchHit]:
        return self._hits


def _tool(hits: list[SearchHit], *, snippet_max_chars: int = 500) -> WebSearch:
    return WebSearch(FakeClient(hits), snippet_max_chars=snippet_max_chars)


async def test_run_formats_hits_with_untrusted_framing() -> None:
    tool = _tool(
        [
            SearchHit("Title A", "https://example.com/a", "Snippet A."),
            SearchHit("Title B", "https://example.com/b", "Snippet B."),
        ]
    )
    out = await tool.run(WebSearch.Args(query="anything"), _CTX)

    assert "untrusted" in out.lower()
    assert "- Title A (https://example.com/a)\n  Snippet A." in out
    assert "- Title B (https://example.com/b)\n  Snippet B." in out


async def test_run_truncates_long_snippets() -> None:
    long_snippet = "word " * 200
    tool = _tool([SearchHit("T", "https://example.com", long_snippet)], snippet_max_chars=50)

    out = await tool.run(WebSearch.Args(query="x"), _CTX)

    assert out.endswith("…[truncated]")
    snippet_line = out.splitlines()[-1].strip()
    assert len(snippet_line) <= 50 + len(" …[truncated]")


async def test_run_reports_no_results() -> None:
    out = await _tool([]).run(WebSearch.Args(query="zzz"), _CTX)

    assert "No web results found" in out
