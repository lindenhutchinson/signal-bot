import json

import httpx

from signal_chatbot.transport import SignalClient


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
