import httpx

from signal_chatbot.tools.builtin.websearch import SearchHit, TavilyClient


def _client(handler, *, result_limit: int = 5) -> TavilyClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TavilyClient(http, "test-key", result_limit=result_limit)


async def test_search_posts_expected_body_and_maps_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert request.url == "https://api.tavily.com/search"
        assert body == {
            "api_key": "test-key",
            "query": "mars rover",
            "max_results": 3,
            "search_depth": "basic",
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Mars rover news",
                        "url": "https://example.com/a",
                        "content": "A snippet about the rover.",
                    },
                    {
                        "title": "More news",
                        "url": "https://example.com/b",
                        "content": "Another snippet.",
                    },
                ]
            },
        )

    results = await _client(handler, result_limit=3).search("mars rover")

    assert results == [
        SearchHit("Mars rover news", "https://example.com/a", "A snippet about the rover."),
        SearchHit("More news", "https://example.com/b", "Another snippet."),
    ]


async def test_search_returns_empty_list_when_no_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    assert await _client(handler).search("nothing") == []


async def test_search_tolerates_missing_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"title": "Only a title"}]})

    assert await _client(handler).search("x") == [SearchHit("Only a title", "", "")]
