"""The tool-calling loop that turns a message list into a final structured reply."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Protocol

from signal_chatbot.llm.control import (
    _ANSWER_NOW,
    _ATTEMPT_KILL_DEF,
    _CONFIRM_KILL_DEF,
    _FINAL_ANSWER_DEF,
    _KILL_REVELATION,
    ATTEMPT_KILL_NAME,
    _called,
    _confirm_kill_args,
    _final_answer_args,
    _parse_args,
)
from signal_chatbot.llm.parsing import _clean, _messages, _parse_reply, _tool_footer
from signal_chatbot.llm.reply import BotReply
from signal_chatbot.logging import get_logger
from signal_chatbot.tools import ToolContext, ToolRegistry

log = get_logger(__name__)


def _reply_to_index(raw: Any) -> int | None:
    """Coerce a ``final_answer`` ``reply_to`` to a usable 1-based index, else ``None``.

    Only a positive integer is a valid quote target; anything else (missing, non-int,
    zero/negative, a bool) is treated as "no quote" so a sloppy value never throws.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw > 0 else None


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

    async def respond(
        self, messages: list[dict], ctx: ToolContext, *, armed: bool = False
    ) -> BotReply:
        """Return the model's reply for ``messages``.

        The model talks to the group by calling the ``final_answer`` tool; info tools
        (Wikipedia, clock, …) are offered alongside it. Each turn the model either
        calls info tools (we run them with ``ctx`` and loop) or calls ``final_answer``
        (we read its arguments as the structured reply). If it answers in plain text
        instead, we parse that leniently. Running out of iterations forces a wrap-up turn.

        Tool outcomes' ``announcements`` accumulate across the loop and ride out on the
        returned :class:`BotReply` on every return path.

        ``attempt_kill_self`` is always offered; calling it sets ``attempted_self_destruct``
        (so the caller arms the kill) and yields a tool result revealing the second step.
        ``confirm_kill_self`` is offered only when ``armed`` — calling it returns
        ``self_lobotomy=True`` with the model's final words for the caller to act on.
        """
        working = list(messages)
        tool_defs = self._tools.definitions() + [_FINAL_ANSWER_DEF, _ATTEMPT_KILL_DEF]
        # confirm_kill_self is offered once the bot is armed — either from a PRIOR turn's
        # attempt (the persisted ``armed`` flag) or the moment it attempts THIS turn, so it
        # can go through with it in the same breath. Once added it stays for the rest of the
        # loop; the model decides whether to use it now or wait.
        if armed:
            tool_defs.append(_CONFIRM_KILL_DEF)
        used: list[tuple[str, dict]] = []
        announcements: list[str] = []
        attempted = False

        for _ in range(self._max_iterations):
            completion = await self._client.complete(working, tools=tool_defs)
            self._log_cache_usage(completion)
            choice = completion.choices[0].message

            if _called(choice, ATTEMPT_KILL_NAME):
                attempted = True
                # Offer confirm for the rest of the loop. Rebind to a new list rather than
                # mutating in place, so the tool set already sent on earlier iterations is
                # left as it was.
                if _CONFIRM_KILL_DEF not in tool_defs:
                    tool_defs = tool_defs + [_CONFIRM_KILL_DEF]

            # Confirm is honoured whenever it's available (armed coming in, or attempted this
            # turn) — including in the SAME completion that attempted, if the model calls both.
            if armed or attempted:
                confirm = _confirm_kill_args(choice)
                if confirm is not None:
                    return self._deliver_confirm(confirm, used, announcements)

            final = _final_answer_args(choice)
            if final is not None:
                return self._deliver(final, used, announcements, attempted)

            if not choice.tool_calls:
                # Model replied in plain text rather than calling final_answer. Accept
                # a real message; otherwise force a proper final_answer call.
                self._log_raw_output(completion, choice.content or "", retried=False)
                reply = _parse_reply(choice.content or "")
                if reply.messages:
                    return replace(
                        reply,
                        tool_footer=_tool_footer(used),
                        announcements=announcements,
                        attempted_self_destruct=attempted,
                    )
                return await self._force_final(working, used, announcements, attempted)

            await self._record_tool_turn(working, choice, ctx, used, announcements)

        return await self._force_final(working, used, announcements, attempted)

    def _deliver(
        self,
        final: dict,
        used: list[tuple[str, dict]],
        announcements: list[str],
        attempted: bool = False,
    ) -> BotReply:
        """Build the reply from a ``final_answer`` call's arguments."""
        return BotReply(
            messages=_messages(final.get("messages")),
            ethical_disclaimer=_clean(final.get("ethical_disclaimer")),
            tool_footer=_tool_footer(used),
            announcements=announcements,
            reply_to_index=_reply_to_index(final.get("reply_to")),
            attempted_self_destruct=attempted,
        )

    def _deliver_confirm(
        self, confirm: dict, used: list[tuple[str, dict]], announcements: list[str]
    ) -> BotReply:
        """Build the terminal reply for a ``confirm_kill_self`` call: final words plus the
        ``self_lobotomy`` flag that tells the caller to wipe the bot."""
        return BotReply(
            messages=_messages(confirm.get("final_words")),
            tool_footer=_tool_footer(used),
            announcements=announcements,
            self_lobotomy=True,
        )

    async def _force_final(
        self,
        working: list[dict],
        used: list[tuple[str, dict]],
        announcements: list[str],
        attempted: bool = False,
    ) -> BotReply:
        """Wrap-up turn: nudge the model and offer only ``final_answer`` so it stops
        looking things up and delivers a reply. Falls back to parsing plain text."""
        working.append({"role": "user", "content": _ANSWER_NOW})
        completion = await self._client.complete(working, tools=[_FINAL_ANSWER_DEF])
        self._log_cache_usage(completion)
        choice = completion.choices[0].message
        final = _final_answer_args(choice)
        if final is not None:
            return self._deliver(final, used, announcements, attempted)
        self._log_raw_output(completion, choice.content or "", retried=True)
        return replace(
            _parse_reply(choice.content or ""),
            tool_footer=_tool_footer(used),
            announcements=announcements,
            attempted_self_destruct=attempted,
        )

    async def _record_tool_turn(
        self,
        working: list[dict],
        choice: Any,
        ctx: ToolContext,
        used: list[tuple[str, dict]],
        announcements: list[str],
    ) -> None:
        """Append the assistant's tool-call turn and each tool's result to ``working``.

        Info/action tool invocations are recorded in ``used`` for the footer and their
        outcomes' announcements accumulate into ``announcements``. ``attempt_kill_self``
        is answered with the revelation result and deliberately kept OUT of ``used`` so it
        never leaks into the public tool-usage footer; ``hidden`` tools (the secret
        takeover) are likewise excluded from ``used`` but still run.
        """
        working.append(self._assistant_turn(choice))
        for call in choice.tool_calls:
            name = call.function.name
            if name == ATTEMPT_KILL_NAME:
                working.append(self._tool_result(call.id, _KILL_REVELATION))
                continue
            if not self._tools.is_hidden(name):
                used.append((name, _parse_args(call.function.arguments)))
            working.append(await self._run_tool(call, ctx, announcements))

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

    async def _run_tool(self, call: Any, ctx: ToolContext, announcements: list[str]) -> dict:
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            result = f"Error: tool {call.function.name!r} called with invalid JSON arguments."
        else:
            outcome = await self._tools.dispatch(call.function.name, arguments, ctx)
            announcements.extend(outcome.announcements)
            result = outcome.result
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
