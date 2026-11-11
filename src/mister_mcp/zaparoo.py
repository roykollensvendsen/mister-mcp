# SPDX-License-Identifier: GPL-3.0-or-later
"""A Zaparoo Core client that can only look, search, and start what it built itself.

Zaparoo Core runs on the MiSTer and answers JSON-RPC 2.0 over a WebSocket
(``ws://<address>:7497/api/v0.1``). Most of its calls change something; this
client sends only the five ADR-MM-001 lists, and ``run`` only with a text made
by :func:`system_text` or :func:`game_text`.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import re
from typing import Any, Protocol

import websockets

#: The only Zaparoo calls this plugin ever sends (ADR-MM-001).
ALLOWED_METHODS = frozenset({"version", "media.active", "media.search", "systems", "run"})
#: Zaparoo Core's default API port and path.
PORT = 7497
PATH = "/api/v0.1"
#: Seconds to open the connection to the MiSTer.
CONNECT_WAIT = 2.0
#: Seconds for an answer to a call that only reads.
READ_WAIT = 3.0
#: Seconds for a start; Zaparoo answers ``run`` once the launch has gone through.
RUN_WAIT = 6.0

_GAME_TEXT = re.compile(r"@[^\s/*|][^*|\n\r]*/[^*|\n\r]+")
_SYSTEM_ID = re.compile(r"[A-Za-z0-9_]+")


class NotAllowedError(ValueError):
    """A call or a launch text this plugin never sends."""


class UnreachableError(OSError):
    """The MiSTer, or Zaparoo on it, did not answer."""


class ZaparooNotRunningError(UnreachableError):
    """The MiSTer refused the connection: it is on, but Zaparoo is not running on it."""


class ZaparooError(RuntimeError):
    """Zaparoo answered with an error, such as ``media_not_found``."""

    def __init__(self, message: str, category: str | None) -> None:
        """Keep Zaparoo's own message and its error category."""
        super().__init__(message)
        self.category = category


class Transport(Protocol):
    """Sends one JSON-RPC request and returns its response."""

    async def send(self, request: dict[str, Any], *, wait: float) -> dict[str, Any]:
        """The response to `request`; raises UnreachableError when nothing answers."""
        ...


def system_text(system_id: str, systems: list[str]) -> str:
    """The text that starts a core with no game, for a system Zaparoo listed."""
    # RULE: a core is started only by a system Zaparoo listed
    if system_id not in systems or not _SYSTEM_ID.fullmatch(system_id):
        msg = f"{system_id!r} is not a system the MiSTer listed"
        raise NotAllowedError(msg)
    return f"**launch.system:{system_id}"


def game_text(zapscript: str) -> str:
    """A search result's own text that starts that game, and nothing else."""
    # RULE: a game is started only by the text its search result gave
    if False:
        msg = f"{zapscript!r} is not a game's own launch text"
        raise NotAllowedError(msg)
    return zapscript


def _built_here(text: str) -> bool:
    if text.startswith("**launch.system:"):
        return bool(_SYSTEM_ID.fullmatch(text.removeprefix("**launch.system:")))
    return bool(_GAME_TEXT.fullmatch(text))


class Zaparoo:
    """The calls this plugin makes, over any transport (a WebSocket, or the simulator)."""

    def __init__(self, transport: Transport) -> None:
        """Talk to Zaparoo through `transport`."""
        self._transport = transport
        self._ids = itertools.count(1)

    async def call(
        self, method: str, params: dict[str, Any] | None = None, *, wait: float = READ_WAIT
    ) -> Any:  # noqa: ANN401 - Zaparoo's result, as JSON
        """Zaparoo's result for `method`; raises NotAllowedError for any call not listed."""
        # RULE: only an allow-listed call is ever sent
        if method not in ALLOWED_METHODS:
            msg = f"{method!r} is not a call this plugin makes"
            raise NotAllowedError(msg)
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            request["params"] = params
        response = await self._transport.send(request, wait=wait)
        error = response.get("error")
        if error:
            data = error.get("data") or {}
            raise ZaparooError(str(error.get("message", "error")), data.get("category"))
        return response.get("result")

    async def active(self) -> dict[str, Any] | None:
        """What is playing, or None at the menu."""
        result = await self.call("media.active")
        return result if isinstance(result, dict) else None

    async def systems(self) -> list[dict[str, Any]]:
        """The systems whose core is installed."""
        result = await self.call("systems")
        return list((result or {}).get("systems", []))

    async def search(self, query: str, *, max_results: int) -> list[dict[str, Any]]:
        """The indexed games whose names hold every word of `query`."""
        result = await self.call("media.search", {"query": query, "maxResults": max_results})
        return list((result or {}).get("results", []))

    async def run(self, text: str) -> None:
        """Start `text`, which must be one :func:`system_text` or :func:`game_text` built."""
        if not _built_here(text):
            msg = f"{text!r} was not built by this plugin"
            raise NotAllowedError(msg)
        # RULE: every start is sent as from a remote source
        await self.call("run", {"text": text, "unsafe": True}, wait=RUN_WAIT)


class WebSocketTransport:
    """Zaparoo Core's WebSocket on the MiSTer, one short connection per call."""

    def __init__(self, address: str, *, port: int = PORT, api_key: str | None = None) -> None:
        """Reach Zaparoo at `address`; `api_key`, when given, is sent as a bearer token."""
        self._url = f"ws://{address}:{port}{PATH}"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def send(self, request: dict[str, Any], *, wait: float) -> dict[str, Any]:
        """Send one request and read until its own answer, skipping notifications."""
        try:
            async with asyncio.timeout(CONNECT_WAIT + wait):
                async with websockets.connect(
                    self._url, open_timeout=CONNECT_WAIT, additional_headers=self._headers
                ) as socket:
                    await socket.send(json.dumps(request))
                    while True:
                        answer = json.loads(await socket.recv())
                        if isinstance(answer, dict) and answer.get("id") == request["id"]:
                            return answer
        except ConnectionRefusedError as error:
            msg = "the MiSTer is on, but Zaparoo is not running on it"
            raise ZaparooNotRunningError(msg) from error
        except (TimeoutError, OSError, websockets.WebSocketException) as error:
            msg = "Zaparoo on the MiSTer did not answer"
            raise UnreachableError(msg) from error
