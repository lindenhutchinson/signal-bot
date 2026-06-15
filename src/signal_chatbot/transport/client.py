"""Signal client backed by signal-cli-rest-api (json-rpc mode).

Receiving uses the persistent websocket at ``/v1/receive/{number}``; sending
uses ``POST /v2/send``. The client never raises out of :meth:`stream`; instead
it reconnects with exponential backoff so the bot stays live across network
blips and bridge restarts.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx
import websockets

from signal_chatbot.logging import get_logger
from signal_chatbot.transport.models import IncomingMessage, OutgoingMessage

log = get_logger(__name__)

_MAX_BACKOFF_SECONDS = 30.0


class ProfileNameSetter(Protocol):
    """Something that can change the bot's own Signal display name (satisfied by SignalClient)."""

    async def set_profile_name(self, name: str) -> None: ...


class SignalClient:
    """Async client for the signal-cli-rest-api bridge."""

    def __init__(self, api_url: str, bot_number: str, *, http: httpx.AsyncClient | None = None):
        self._api_url = api_url.rstrip("/")
        self._bot_number = bot_number
        self._http = http or httpx.AsyncClient(base_url=self._api_url, timeout=30.0)
        self._owns_http = http is None

    @property
    def _ws_url(self) -> str:
        base = self._api_url.replace("http://", "ws://").replace("https://", "wss://")
        return f"{base}/v1/receive/{self._bot_number}"

    async def stream(self) -> AsyncIterator[IncomingMessage]:
        """Yield incoming group text messages forever, reconnecting on failure."""
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self._ws_url, ping_interval=30) as ws:
                    log.info("signal.connected", url=self._ws_url)
                    backoff = 1.0
                    async for raw in ws:
                        message = self._parse(raw)
                        if message is not None:
                            yield message
            except (OSError, websockets.WebSocketException) as exc:
                log.warning("signal.disconnected", error=str(exc), retry_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    @staticmethod
    def _parse(raw: str | bytes) -> IncomingMessage | None:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.warning("signal.bad_frame")
            return None
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict):
            return None
        return IncomingMessage.from_envelope(envelope)

    async def send(self, message: OutgoingMessage) -> None:
        """Send a text message to a group via the REST bridge."""
        body: dict = {
            "number": self._bot_number,
            "message": message.text,
            "recipients": [message.group_id],
        }
        # Only attach the quote when the full trio is present — the bridge needs all
        # three to render a reply, and a partial quote would be silently dropped anyway.
        if (
            message.quote_timestamp is not None
            and message.quote_author is not None
            and message.quote_message is not None
        ):
            body["quote_timestamp"] = message.quote_timestamp
            body["quote_author"] = message.quote_author
            body["quote_message"] = message.quote_message
        resp = await self._http.post("/v2/send", json=body)
        resp.raise_for_status()

    async def set_profile_name(self, name: str) -> None:
        """Set the bot's own Signal profile (display) name. This is account-global."""
        resp = await self._http.put(
            f"/v1/profiles/{self._bot_number}",
            json={"name": name},
        )
        resp.raise_for_status()

    async def list_groups(self) -> list[dict]:
        """Return the bot's groups (used by the setup CLI to find group ids)."""
        resp = await self._http.get(f"/v1/groups/{self._bot_number}")
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
