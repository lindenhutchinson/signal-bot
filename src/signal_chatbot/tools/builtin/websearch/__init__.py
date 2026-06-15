"""Web search: a snippets-only tool backed by the Tavily search API.

Wiring: build a :class:`TavilyClient` (over an httpx client, with the API key)
and wrap it in a :class:`WebSearch` tool. Disabled by leaving the API key empty.
"""

from signal_chatbot.tools.builtin.websearch.client import SearchHit, TavilyClient
from signal_chatbot.tools.builtin.websearch.tool import WebSearch

__all__ = ["SearchHit", "TavilyClient", "WebSearch"]
