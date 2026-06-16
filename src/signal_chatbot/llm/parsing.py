"""Reply/text parsing and the tool-usage footer builders.

The model's words can arrive either as ``final_answer`` arguments or, on the
post-tool path, as free-form content that wraps a JSON object in prose (and may
leak DeepSeek's internal tool-call markup). These helpers recover a clean
:class:`BotReply` from either, and build the deterministic "what I looked up"
footer from the tools invoked this turn.
"""

from __future__ import annotations

import json
import re
from typing import Any

from signal_chatbot.llm.reply import BotReply
from signal_chatbot.timefmt import strip_leading_timestamp


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


# When the model wants a tool but tools are disabled (the budget-exhausted final
# turn), it can leak DeepSeek's internal tool-call syntax as plain text, e.g.
# ``<｜｜DSML｜｜tool_calls> … </｜｜DSML｜｜tool_calls>``. That must never be sent: strip
# it (and anything after) so what's left is the real answer, or empty if it was all markup.
_TOOL_MARKUP_RE = re.compile(r"\s*<[^>]*DSML.*\Z", re.DOTALL)

# The disclaimer belongs ONLY in the ethical_disclaimer field, never in the public
# message — but the model still sometimes writes an "Ethical disclaimer:" section into the
# message itself, as a leading label OR (more often) a trailing paragraph on its own line.
# This marker matches that label at the start of any line, so we can split it back out.
_DISCLAIMER_MARKER_RE = re.compile(
    r"(?im)^[ \t>*_\-]*ethical[ \t_-]*disclaimer\b[ \t]*[:\-–—]?[ \t]*"
)


def split_off_disclaimer(text: str) -> tuple[str, str]:
    """Split a leaked ``Ethical disclaimer:`` section out of a message.

    Returns ``(message, disclaimer)``: everything before the first marker is the real
    message; the marker and everything after it become the disclaimer. With no marker,
    returns ``(text, "")``. This is a backstop — the model is told to use the
    ethical_disclaimer field — that catches both a leading label and a trailing block.
    """
    match = _DISCLAIMER_MARKER_RE.search(text)
    if match is None:
        return text.strip(), ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _strip_tool_markup(text: str) -> str:
    return _TOOL_MARKUP_RE.sub("", text).strip()


def _message(value: Any) -> str:
    """Clean a candidate message, dropping a leading ``[timestamp]`` the model echoed
    and any leaked tool-call markup."""
    return _strip_tool_markup(strip_leading_timestamp(_clean(value)))


def _dedup(values) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _tool_footer(used: list[tuple[str, dict]]) -> str:
    """Build the "what I looked up" note appended to a reply when tools were used.

    ``used`` is the ordered list of ``(tool_name, arguments)`` invoked this turn.
    Article reads are the headline; otherwise we fall back to searches, then to a bare
    list of tool names — so any tool use produces a footer.
    """
    if not used:
        return ""
    articles = _dedup(a.get("title", "") for n, a in used if n == "wikipedia_article")
    if articles:
        return _footer_block(f"looked up {len(articles)} article{_plural(articles)}:", articles)
    searches = _dedup(a.get("query", "") for n, a in used if n == "wikipedia_search")
    if searches:
        header = f"searched Wikipedia for {len(searches)} thing{_plural(searches)}:"
        return _footer_block(header, searches)
    return _footer_block("used:", _dedup(name for name, _ in used))


def _footer_block(header: str, items: list[str]) -> str:
    return "\n\n" + header + "\n" + "\n".join(f"- {item}" for item in items)


def _plural(items: list) -> str:
    return "s" if len(items) != 1 else ""


def _extract_reply_object(text: str) -> dict | None:
    """Find an embedded ``{"message": ...}`` object in ``text``, or ``None``.

    Free-form completions (the post-tool path) often wrap the JSON in prose — the
    model "thinks out loud" and then emits the object. Scanning for the first
    ``{`` that decodes to a dict with a ``message`` key recovers it; trailing prose
    after the object is ignored via ``raw_decode``.
    """
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and "message" in obj:
            return obj
        idx = text.find("{", idx + 1)
    return None


def _parse_reply(content: str) -> BotReply:
    """Parse the model's final content into a :class:`BotReply`.

    Prefers an embedded ``{"message": ..., "ethical_disclaimer": ...}`` object (it may
    be wrapped in prose or a code fence); falls back to treating the whole content as
    the message when no such object is present.
    """
    data = _extract_reply_object(_strip_code_fence(content.strip()))
    if data is not None:
        return BotReply(
            message=_message(data.get("message")),
            ethical_disclaimer=_clean(data.get("ethical_disclaimer")),
        )
    return BotReply(message=_message(content))
