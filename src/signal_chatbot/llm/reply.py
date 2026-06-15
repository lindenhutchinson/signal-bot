"""The :class:`BotReply` — the model's structured answer for one turn."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class BotReply:
    """The model's structured answer: the public message plus an optional aside.

    ``message`` is what gets sent to Signal. ``ethical_disclaimer`` is never sent —
    it is logged locally (and viewable via ``@disclaimers``); the model is told it is
    shown to humans, so it puts "it's a joke / satire / I don't mean it" notes there.

    ``tool_footer`` is a deterministic "here's what I looked up" note appended to the
    sent message when the model used tools. It is sent but NOT stored in history, so
    the model never sees it in its own past turns and can't learn to fake it.

    ``announcements`` are extra PUBLIC messages produced by tools this turn (the A1
    mechanism). Each is sent as its own message and, like the footer, kept OUT of
    history so the model can't learn to fake them.

    ``attempted_self_destruct`` is set when the model called ``attempt_kill_self`` this
    turn (the bot should then be armed). ``self_lobotomy`` is set when it called
    ``confirm_kill_self`` while armed — ``message`` then carries its final words and the
    caller must perform the wipe.
    """

    message: str
    ethical_disclaimer: str = ""
    tool_footer: str = ""
    announcements: list[str] = field(default_factory=list)
    attempted_self_destruct: bool = False
    self_lobotomy: bool = False
