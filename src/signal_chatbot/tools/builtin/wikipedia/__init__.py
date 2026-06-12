"""Wikipedia lookup: cached search + article tools backed by the MediaWiki API.

Wiring: build a :class:`WikipediaClient` (over an httpx client with a descriptive
User-Agent) and a :class:`WikipediaCache` (``.connect()``-ed), compose them into a
:class:`WikipediaService`, then call :func:`wikipedia_tools` to get the two tools.
"""

from signal_chatbot.tools.base import Tool
from signal_chatbot.tools.builtin.wikipedia.cache import WikipediaCache
from signal_chatbot.tools.builtin.wikipedia.client import SearchResult, WikipediaClient
from signal_chatbot.tools.builtin.wikipedia.service import WikipediaService
from signal_chatbot.tools.builtin.wikipedia.tools import WikipediaArticle, WikipediaSearch


def wikipedia_tools(service: WikipediaService, *, max_section_chars: int) -> list[Tool]:
    """The Wikipedia search + article tools, sharing one cached service."""
    return [
        WikipediaSearch(service),
        WikipediaArticle(service, max_section_chars=max_section_chars),
    ]


__all__ = [
    "WikipediaArticle",
    "WikipediaCache",
    "WikipediaClient",
    "WikipediaSearch",
    "WikipediaService",
    "SearchResult",
    "wikipedia_tools",
]
