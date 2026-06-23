"""The two LLM-facing Wikipedia tools: search and article.

Both are thin — they validate arguments, call the service, and format the result
as a string. Disambiguation logic (find → read) lives with the model: search
returns candidate titles, and the article tool reads one of them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from signal_chatbot.tools.base import Tool, ToolContext
from signal_chatbot.tools.builtin.wikipedia import article as article_parser
from signal_chatbot.tools.builtin.wikipedia.service import WikipediaService


class WikipediaSearch(Tool):
    name = "wikipedia_search"
    description = (
        "Search Wikipedia and get a ranked list of matching article titles with short "
        "snippets. Use this first to find the right article (and to disambiguate, e.g. "
        "'Mercury' the planet vs the element), then read it with wikipedia_article."
    )
    summary = "Search Wikipedia."
    per_turn_limit = 3

    class Args(BaseModel):
        query: str = Field(description="What to search for, e.g. 'James Webb telescope'.")

    def __init__(self, service: WikipediaService):
        self._service = service

    async def run(self, args: WikipediaSearch.Args, ctx: ToolContext) -> str:
        results = await self._service.search(args.query)
        if not results:
            return f"No Wikipedia articles found for {args.query!r}."
        return "\n".join(f"- {r.title} — {r.snippet}" for r in results)


class WikipediaArticle(Tool):
    name = "wikipedia_article"
    description = (
        "Read a Wikipedia article by its exact title (use wikipedia_search first to find it). "
        "By default returns the intro. Set full=true to also get a table of contents of the "
        "article's sections, then pass a section name or number to read that section."
    )
    summary = "Read a Wikipedia article."
    per_turn_limit = 4

    class Args(BaseModel):
        title: str = Field(description="Exact article title, e.g. 'Mercury (planet)'.")
        full: bool = Field(
            default=False,
            description="If true, return the intro plus a table of contents of all sections.",
        )
        section: str | None = Field(
            default=None,
            description="A section name or number (from the table of contents) to read in full.",
        )

    def __init__(self, service: WikipediaService, *, max_section_chars: int):
        self._service = service
        self._max_section_chars = max_section_chars

    async def run(self, args: WikipediaArticle.Args, ctx: ToolContext) -> str:
        title = args.title.strip()
        if args.section is not None:
            return await self._read_section(title, args.section)
        if args.full:
            return await self._read_full(title)
        return await self._read_intro(title)

    async def _read_intro(self, title: str) -> str:
        intro = await self._service.intro(title)
        if intro is None:
            return self._not_found(title)
        return intro

    async def _read_full(self, title: str) -> str:
        text = await self._service.full(title)
        if text is None:
            return self._not_found(title)
        article = article_parser.parse(text)
        toc = article_parser.table_of_contents(article)
        return f"{article.intro}\n\n== Sections ==\n{toc}"

    async def _read_section(self, title: str, selector: str) -> str:
        text = await self._service.full(title)
        if text is None:
            return self._not_found(title)
        article = article_parser.parse(text)
        section = article_parser.find_section(article, selector)
        if section is None:
            toc = article_parser.table_of_contents(article)
            return f"No section {selector!r} in {title!r}. Available sections:\n{toc}"
        return self._truncate(section.text or "(this section has no text)")

    def _truncate(self, text: str) -> str:
        if len(text) <= self._max_section_chars:
            return text
        return text[: self._max_section_chars].rstrip() + " …[truncated]"

    @staticmethod
    def _not_found(title: str) -> str:
        return (
            f"No Wikipedia article titled {title!r}. Try wikipedia_search to find the exact title."
        )
