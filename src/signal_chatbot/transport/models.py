"""Transport-level message models, decoupled from the wire format."""

from __future__ import annotations

import base64
from dataclasses import dataclass


def _to_internal_group_id(raw_group_id: str) -> str:
    """Convert a signal-cli group id to the REST bridge's internal id.

    The ``/v1/receive`` websocket delivers the *raw* signal-cli group id (a
    base64 string), but the bridge's ``/v1/groups`` and ``/v2/send`` endpoints
    speak an "internal" id of the form ``group.<base64(raw)>``. Normalising here
    keeps a single representation across the bot: it matches the allowlist
    (populated from the ``groups`` CLI) and is accepted as a send recipient.
    """
    return "group." + base64.b64encode(raw_group_id.encode()).decode()


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """A text message received from a Signal group.

    Direct (1:1) messages and non-text payloads are filtered out before this
    type is constructed, so ``group_id`` and ``text`` are always present.
    """

    group_id: str
    sender_number: str
    sender_name: str
    text: str
    timestamp: int

    @classmethod
    def from_envelope(cls, envelope: dict) -> IncomingMessage | None:
        """Build an :class:`IncomingMessage` from a signal-cli envelope.

        Returns ``None`` for envelopes that are not a group text message
        (receipts, typing indicators, reactions, sync messages, 1:1 chats, ...).
        """
        data = envelope.get("dataMessage")
        if not isinstance(data, dict):
            return None

        text = data.get("message")
        if not text:
            return None

        group_info = data.get("groupInfo")
        if not isinstance(group_info, dict):
            return None
        raw_group_id = group_info.get("groupId")
        if not raw_group_id:
            return None
        group_id = _to_internal_group_id(raw_group_id)

        source = envelope.get("sourceNumber") or envelope.get("source") or ""
        name = envelope.get("sourceName") or source or "unknown"
        timestamp = data.get("timestamp") or envelope.get("timestamp") or 0

        return cls(
            group_id=group_id,
            sender_number=source,
            sender_name=name,
            text=text,
            timestamp=int(timestamp),
        )


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """A text message to send back to a Signal group.

    The optional ``quote_*`` trio identifies an earlier message this one replies to.
    They are sent only as a complete set (all three present); a partial quote is
    meaningless to the bridge.
    """

    group_id: str
    text: str
    quote_timestamp: int | None = None
    quote_author: str | None = None
    quote_message: str | None = None
