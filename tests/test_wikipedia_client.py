import httpx
import pytest

from signal_chatbot.tools.builtin.wikipedia import WikipediaClient


def _client(handler) -> WikipediaClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WikipediaClient(http, language="en")


async def test_search_returns_titles_with_stripped_snippets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["srsearch"] == "mercury"
        assert request.url.params["srlimit"] == "5"
        return httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {
                            "title": "Mercury (planet)",
                            "snippet": 'The <span class="x">planet</span>',
                        },
                        {"title": "Mercury (element)", "snippet": "A chemical &amp; element"},
                    ]
                }
            },
        )

    client = _client(handler)
    results = await client.search("mercury", limit=5)

    assert [r.title for r in results] == ["Mercury (planet)", "Mercury (element)"]
    assert results[0].snippet == "The planet"
    assert results[1].snippet == "A chemical & element"


async def test_search_targets_the_configured_language() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        return httpx.Response(200, json={"query": {"search": []}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await WikipediaClient(http, language="de").search("x", limit=3)

    assert seen["host"] == "de.wikipedia.org"


async def test_intro_passes_exintro_and_returns_extract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("exintro") == "1"
        return httpx.Response(
            200, json={"query": {"pages": [{"title": "Mercury", "extract": "Lead text."}]}}
        )

    assert await _client(handler).intro("Mercury") == "Lead text."


async def test_full_omits_exintro_and_returns_whole_extract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "exintro" not in request.url.params
        assert request.url.params["exsectionformat"] == "wiki"
        return httpx.Response(
            200,
            json={"query": {"pages": [{"title": "Mercury", "extract": "Lead\n\n== History =="}]}},
        )

    assert await _client(handler).full("Mercury") == "Lead\n\n== History =="


@pytest.mark.parametrize("page", [{"missing": True}, {"extract": ""}])
async def test_extract_returns_none_for_missing_or_empty_pages(page: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": {"pages": [{"title": "X", **page}]}})

    assert await _client(handler).intro("X") is None


async def test_extract_returns_none_when_no_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": {"pages": []}})

    assert await _client(handler).full("X") is None


async def test_query_sends_maxlag() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["maxlag"] = request.url.params.get("maxlag")
        return httpx.Response(200, json={"query": {"search": []}})

    await _client(handler).search("x", limit=3)

    assert seen["maxlag"] == "5"


async def test_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("signal_chatbot.tools.builtin.wikipedia.client.asyncio.sleep", fake_sleep)

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")
        return httpx.Response(200, json={"query": {"search": []}})

    await _client(handler).search("x", limit=3)

    assert calls["n"] == 2
    assert slept == [7.0]  # honoured the Retry-After header


async def test_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(delay: float) -> None:
        pass

    monkeypatch.setattr("signal_chatbot.tools.builtin.wikipedia.client.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="nope")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = WikipediaClient(http, language="en", max_retries=2)

    with pytest.raises(httpx.HTTPStatusError):
        await client.search("x", limit=3)
