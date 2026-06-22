"""The :class:`BotReply` — the model's structured answer for one turn."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class BotReply:
    """The model's structured answer: the public message(s) plus an optional aside.

    ``messages`` are the chat bubbles sent to Signal, in order — usually one, but the
    model may split a reply into a couple of separate messages. An empty list means the
    bot says nothing this turn (a bare reaction, or a deliberate silence).
    ``ethical_disclaimer`` is never sent — it is logged locally (and viewable via
    ``@disclaimers``); the model is told it is shown to humans, so it puts "it's a joke /
    satire / I don't mean it" notes there.

    ``tool_footer`` is a deterministic "here's what I looked up" note appended to the
    LAST bubble when the model used tools. It is sent but NOT stored in history, so
    the model never sees it in its own past turns and can't learn to fake it.

    ``announcements`` are extra PUBLIC messages produced by tools this turn (the A1
    mechanism). Each is sent as its own message and, like the footer, kept OUT of
    history so the model can't learn to fake them.

    ``reply_to_index`` is the 1-based ``[#N]`` the model chose to quote (over the
    quotable, non-bot history window); the bot resolves it to a Signal quote on the
    FIRST bubble. ``None`` means no quote.

    ``attempted_self_destruct`` is set when the model called ``attempt_kill_self`` this
    turn (the bot should then be armed). ``self_lobotomy`` is set when it called
    ``confirm_kill_self`` — ``messages`` then carry its final words and the caller must
    perform the wipe.
    """

    messages: list[str] = field(default_factory=list)
    ethical_disclaimer: str = ""
    tool_footer: str = ""
    announcements: list[str] = field(default_factory=list)
    reply_to_index: int | None = None
    attempted_self_destruct: bool = False
    self_lobotomy: bool = False

    @property
    def message(self) -> str:
        """The bubbles joined into one string — a convenience for the single-text paths
        (self-kill final words, history) that don't care about bubble boundaries."""
        return "\n\n".join(self.messages)
