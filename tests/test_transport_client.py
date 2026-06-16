import json

import httpx

from signal_chatbot.transport import SignalClient
from signal_chatbot.transport.models import OutgoingMessage


def _capturing_client() -> tuple[SignalClient, dict]:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(200)

    http = httpx.AsyncClient(base_url="http://bridge", transport=httpx.MockTransport(handler))
    return SignalClient("http://bridge", "+61400000000", http=http), seen


async def test_send_omits_quote_fields_when_not_quoting() -> None:
    client, seen = _capturing_client()

    await client.send(OutgoingMessage(group_id="group.x=", text="hi"))
    await client.aclose()

    body = seen["json"]
    assert body == {
        "number": "+61400000000",
        "message": "hi",
        "recipients": ["group.x="],
    }


async def test_send_includes_quote_fields_when_all_present() -> None:
    client, seen = _capturing_client()

    await client.send(
        OutgoingMessage(
            group_id="group.x=",
            text="hi",
            quote_timestamp=1781274720000,
            quote_author="+61400000001",
            quote_message="the earlier message",
        )
    )
    await client.aclose()

    body = seen["json"]
    assert body["quote_timestamp"] == 1781274720000
    assert body["quote_author"] == "+61400000001"
    assert body["quote_message"] == "the earlier message"


async def test_send_omits_quote_fields_when_only_some_are_present() -> None:
    client, seen = _capturing_client()

    # A partial quote (no author/message) is meaningless to the bridge — drop it entirely.
    await client.send(
        OutgoingMessage(group_id="group.x=", text="hi", quote_timestamp=1781274720000)
    )
    await client.aclose()

    body = seen["json"]
    assert "quote_timestamp" not in body
    assert "quote_author" not in body
    assert "quote_message" not in body


async def test_send_reaction_posts_to_the_reactions_endpoint() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200)

    http = httpx.AsyncClient(base_url="http://bridge", transport=httpx.MockTransport(handler))
    client = SignalClient("http://bridge", "+61400000000", http=http)

    await client.send_reaction(
        "group.x=", emoji="🔥", target_author="+61400000001", target_timestamp=1781274720000
    )
    await http.aclose()

    assert seen["method"] == "POST"
    assert seen["url"] == "http://bridge/v1/reactions/+61400000000"
    assert seen["json"] == {
        "recipient": "group.x=",
        "reaction": "🔥",
        "target_author": "+61400000001",
        "timestamp": 1781274720000,
    }


async def test_set_profile_name_puts_to_the_profiles_endpoint() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200)

    http = httpx.AsyncClient(base_url="http://bridge", transport=httpx.MockTransport(handler))
    client = SignalClient("http://bridge", "+61400000000", http=http)

    await client.set_profile_name("Greg")
    await http.aclose()

    assert seen["method"] == "PUT"
    assert seen["url"] == "http://bridge/v1/profiles/+61400000000"
    assert seen["json"] == {"name": "Greg"}
