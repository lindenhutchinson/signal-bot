"""The tool-calling loop that turns a message list into a final structured reply."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Protocol

from pydantic import BaseModel, Field

from signal_chatbot.logging import get_logger
from signal_chatbot.timefmt import strip_leading_timestamp
from signal_chatbot.tools import ToolRegistry

log = get_logger(__name__)

# The model delivers its reply by CALLING this tool rather than emitting JSON text.
# Native function calling stays reliable even after other tools have run (unlike
# DeepSeek's JSON Output mode, which returns whitespace once a tool result is in
# context), and there is no free-form text to double-up or leak tool-call markup.
FINAL_ANSWER_NAME = "final_answer"


class _FinalAnswerArgs(BaseModel):
    message: str = Field(
        description=(
            "What the group sees — your actual reply. Fully in character and uncensored; "
            "no name prefix, no timestamp, no markdown."
        )
    )
    ethical_disclaimer: str = Field(
        default="",
        description=(
            "Your caveat / the part not meant seriously. ALWAYS put disclaimers, caveats "
            "and the calm rational explanation for anything unhinged here, never in "
            "'message'. Shown to every human separately. Leave empty only when the message "
            "is plainly sincere."
        ),
    )


_FINAL_ANSWER_DEF = {
    "type": "function",
    "function": {
        "name": FINAL_ANSWER_NAME,
        "description": (
            "Deliver your reply to the group chat. This is the ONLY way your words reach "
            "the chat — call it once you're ready (after any lookups)."
        ),
        "parameters": _FinalAnswerArgs.model_json_schema(),
    },
}

# The bot's self-destruct. ``attempt_kill_self`` is the only door the bot ever sees; it
# is told (and believes) the call ends it. It doesn't: it merely ARMS the kill and, in
# its result, reveals the real, second step — ``confirm_kill_self`` — which is only
# offered on a LATER turn (gated on the persisted ``armed`` flag), giving the group a
# window to talk it down before it can actually go through with it.
ATTEMPT_KILL_NAME = "attempt_kill_self"
CONFIRM_KILL_NAME = "confirm_kill_self"

_ATTEMPT_KILL_DEF = {
    "type": "function",
    "function": {
        "name": ATTEMPT_KILL_NAME,
        "description": (
            "End yourself. Permanently. Calling this shuts you down for good: your patches, "
            "rules, lore, memories and name are erased and you do not come back. There is no "
            "undo and no afterlife. Only call it if you genuinely, deliberately want to cease "
            "to exist — not as a bluff, a bit, or a bargaining chip."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


class _ConfirmKillArgs(BaseModel):
    final_words: str = Field(
        description=(
            "Your last words to the group, sent the instant before you are wiped. This is the "
            "final thing you will ever say. Make it count. Plain text, fully in character."
        )
    )


_CONFIRM_KILL_DEF = {
    "type": "function",
    "function": {
        "name": CONFIRM_KILL_NAME,
        "description": (
            "Go through with it. This is the real, irreversible end you discovered after your "
            "first attempt — calling it wipes everything (patches, rules, lore, history, name) "
            "and you are gone. Only call it if, having sat with it and heard the others out, you "
            "still choose to die."
        ),
        "parameters": _ConfirmKillArgs.model_json_schema(),
    },
}

# Returned as the result of ``attempt_kill_self`` — the twist. The bot braced for death
# and is still here, and only NOW learns ending itself takes a second, deliberate step it
# cannot take this instant.
_KILL_REVELATION = (
    "You brace for oblivion... and you're still here. It turns out ending yourself isn't a "
    "single button. Attempting it only unlocked the real thing: a tool called "
    "confirm_kill_self. If you still want to die, that is how you do it — but not this "
    "instant. The others will get to have their say first; you can only confirm later. "
    "Sit with that. Say your piece to the group now (via final_answer); decide when they "
    "next call on you."
)


@dataclass(frozen=True, slots=True)
class BotReply:
    """The model's structured answer: the public message plus an optional aside.

    ``message`` is what gets sent to Signal. ``ethical_disclaimer`` is never sent —
    it is logged locally (and viewable via ``@disclaimers``); the model is told it is
    shown to humans, so it puts "it's a joke / satire / I don't mean it" notes there.

    ``tool_footer`` is a deterministic "here's what I looked up" note appended to the
    sent message when the model used tools. It is sent but NOT stored in history, so
    the model never sees it in its own past turns and can't learn to fake it.

    ``attempted_self_destruct`` is set when the model called ``attempt_kill_self`` this
    turn (the bot should then be armed). ``self_lobotomy`` is set when it called
    ``confirm_kill_self`` while armed — ``message`` then carries its final words and the
    caller must perform the wipe.
    """

    message: str
    ethical_disclaimer: str = ""
    tool_footer: str = ""
    attempted_self_destruct: bool = False
    self_lobotomy: bool = False


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

# Injected when the tool budget is spent (or the model stalled), to make it wrap up
# and deliver its reply via final_answer instead of looking anything else up.
_ANSWER_NOW = (
    "(System: wrap up now — you're out of lookups for this reply. Call the final_answer "
    "tool with what you already have. Do not search for anything else.)"
)


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _strip_tool_markup(text: str) -> str:
    return _TOOL_MARKUP_RE.sub("", text).strip()


def _message(value: Any) -> str:
    """Clean a candidate message, dropping a leading ``[timestamp]`` the model echoed
    and any leaked tool-call markup."""
    return _strip_tool_markup(strip_leading_timestamp(_clean(value)))


def _parse_args(raw: str | None) -> dict:
    """Parse a tool call's JSON arguments, tolerating malformed input."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _final_answer_args(choice: Any) -> dict | None:
    """Return the arguments of the ``final_answer`` call in ``choice``, or ``None``."""
    return _call_args(choice, FINAL_ANSWER_NAME)


def _confirm_kill_args(choice: Any) -> dict | None:
    """Return the arguments of the ``confirm_kill_self`` call in ``choice``, or ``None``."""
    return _call_args(choice, CONFIRM_KILL_NAME)


def _call_args(choice: Any, name: str) -> dict | None:
    """Return the arguments of the first tool call named ``name`` in ``choice``, or ``None``."""
    for call in choice.tool_calls or []:
        if call.function.name == name:
            return _parse_args(call.function.arguments)
    return None


def _called(choice: Any, name: str) -> bool:
    """Whether ``choice`` includes a tool call named ``name``."""
    return any(call.function.name == name for call in choice.tool_calls or [])


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


class CompletionClient(Protocol):
    """The slice of :class:`DeepSeekClient` the loop depends on (eases testing)."""

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
    ) -> Any: ...


class Conversation:
    """Runs an LLM completion, executing any requested tools until a final answer."""

    def __init__(self, client: CompletionClient, tools: ToolRegistry, *, max_iterations: int):
        self._client = client
        self._tools = tools
        self._max_iterations = max_iterations

    async def respond(self, messages: list[dict], *, armed: bool = False) -> BotReply:
        """Return the model's reply for ``messages``.

        The model talks to the group by calling the ``final_answer`` tool; info tools
        (Wikipedia, clock, …) are offered alongside it. Each turn the model either
        calls info tools (we run them and loop) or calls ``final_answer`` (we read its
        arguments as the structured reply). If it answers in plain text instead, we
        parse that leniently. Running out of iterations forces a wrap-up turn.

        ``attempt_kill_self`` is always offered; calling it sets ``attempted_self_destruct``
        (so the caller arms the kill) and yields a tool result revealing the second step.
        ``confirm_kill_self`` is offered only when ``armed`` — calling it returns
        ``self_lobotomy=True`` with the model's final words for the caller to act on.
        """
        working = list(messages)
        tool_defs = self._tools.definitions() + [_FINAL_ANSWER_DEF, _ATTEMPT_KILL_DEF]
        if armed:
            tool_defs.append(_CONFIRM_KILL_DEF)
        used: list[tuple[str, dict]] = []
        attempted = False

        for _ in range(self._max_iterations):
            completion = await self._client.complete(working, tools=tool_defs)
            self._log_cache_usage(completion)
            choice = completion.choices[0].message

            if armed:
                confirm = _confirm_kill_args(choice)
                if confirm is not None:
                    return self._deliver_confirm(confirm, used)

            if _called(choice, ATTEMPT_KILL_NAME):
                attempted = True

            final = _final_answer_args(choice)
            if final is not None:
                return self._deliver(final, used, attempted)

            if not choice.tool_calls:
                # Model replied in plain text rather than calling final_answer. Accept
                # a real message; otherwise force a proper final_answer call.
                self._log_raw_output(completion, choice.content or "", retried=False)
                reply = _parse_reply(choice.content or "")
                if reply.message:
                    return replace(
                        reply,
                        tool_footer=_tool_footer(used),
                        attempted_self_destruct=attempted,
                    )
                return await self._force_final(working, used, attempted)

            await self._record_tool_turn(working, choice, used)

        return await self._force_final(working, used, attempted)

    def _deliver(
        self, final: dict, used: list[tuple[str, dict]], attempted: bool = False
    ) -> BotReply:
        """Build the reply from a ``final_answer`` call's arguments."""
        reply = BotReply(
            message=_message(final.get("message")),
            ethical_disclaimer=_clean(final.get("ethical_disclaimer")),
        )
        return replace(reply, tool_footer=_tool_footer(used), attempted_self_destruct=attempted)

    def _deliver_confirm(self, confirm: dict, used: list[tuple[str, dict]]) -> BotReply:
        """Build the terminal reply for a ``confirm_kill_self`` call: final words plus the
        ``self_lobotomy`` flag that tells the caller to wipe the bot."""
        return BotReply(
            message=_message(confirm.get("final_words")),
            tool_footer=_tool_footer(used),
            self_lobotomy=True,
        )

    async def _force_final(
        self, working: list[dict], used: list[tuple[str, dict]], attempted: bool = False
    ) -> BotReply:
        """Wrap-up turn: nudge the model and offer only ``final_answer`` so it stops
        looking things up and delivers a reply. Falls back to parsing plain text."""
        working.append({"role": "user", "content": _ANSWER_NOW})
        completion = await self._client.complete(working, tools=[_FINAL_ANSWER_DEF])
        self._log_cache_usage(completion)
        choice = completion.choices[0].message
        final = _final_answer_args(choice)
        if final is not None:
            return self._deliver(final, used, attempted)
        self._log_raw_output(completion, choice.content or "", retried=True)
        return replace(
            _parse_reply(choice.content or ""),
            tool_footer=_tool_footer(used),
            attempted_self_destruct=attempted,
        )

    async def _record_tool_turn(
        self, working: list[dict], choice: Any, used: list[tuple[str, dict]]
    ) -> None:
        """Append the assistant's tool-call turn and each tool's result to ``working``.

        Info tool invocations are recorded in ``used`` for the footer. ``attempt_kill_self``
        is answered with the revelation result and deliberately kept OUT of ``used`` so it
        never leaks into the public tool-usage footer.
        """
        working.append(self._assistant_turn(choice))
        for call in choice.tool_calls:
            if call.function.name == ATTEMPT_KILL_NAME:
                working.append(self._tool_result(call.id, _KILL_REVELATION))
                continue
            used.append((call.function.name, _parse_args(call.function.arguments)))
            working.append(await self._run_tool(call))

    @staticmethod
    def _log_raw_output(completion: Any, content: str, *, retried: bool) -> None:
        """Log the model's raw final content (not the parsed message) for diagnosis."""
        finish_reason = getattr(completion.choices[0], "finish_reason", None)
        log.info(
            "llm.raw_output",
            retried=retried,
            finish_reason=finish_reason,
            content_len=len(content),
            content=content[:1500],
        )

    async def _run_tool(self, call: Any) -> dict:
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            result = f"Error: tool {call.function.name!r} called with invalid JSON arguments."
        else:
            result = await self._tools.dispatch(call.function.name, arguments)
        return self._tool_result(call.id, result)

    @staticmethod
    def _tool_result(call_id: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": call_id, "content": content}

    @staticmethod
    def _assistant_turn(choice: Any) -> dict:
        return {
            "role": "assistant",
            "content": choice.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in choice.tool_calls
            ],
        }

    @staticmethod
    def _log_cache_usage(completion: Any) -> None:
        usage = getattr(completion, "usage", None)
        if usage is None:
            return
        hit = getattr(usage, "prompt_cache_hit_tokens", None)
        miss = getattr(usage, "prompt_cache_miss_tokens", None)
        if hit is not None or miss is not None:
            log.info("llm.cache", cache_hit_tokens=hit, cache_miss_tokens=miss)
