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
from typing import TYPE_CHECKING, Any, Protocol

import websockets

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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
#: Seconds to find the MiSTer among all its addresses, before a read; within the voice's time.
FIND_WITHIN = 6.0

_GAME_TEXT = re.compile(r"@[^\s/*|][^*|\n\r]*/[^*|\n\r]+")
_SYSTEM_ID = re.compile(r"[A-Za-z0-9_]+")


class NotAllowedError(ValueError):
    """A call or a launch text this plugin never sends."""


class UnreachableError(OSError):
    """The MiSTer, or Zaparoo on it, did not answer at any of the addresses `tried`."""

    def __init__(self, message: str, *, tried: Sequence[str] = ()) -> None:
        """Keep the message, and every address that was tried, in order."""
        super().__init__(message)
        self.tried = tuple(tried)


class ZaparooNeedsPairingError(UnreachableError):
    """Zaparoo answered, but it serves only paired clients, and this computer is not one."""


class Session(Protocol):
    """How one connection's frames are written and read, when Zaparoo encrypts them."""

    def first(self, text: str) -> str:
        """The first frame, carrying the request `text`."""
        ...

    def read(self, raw: str) -> str:
        """The JSON text inside a frame from Zaparoo; raises when it cannot be opened."""
        ...


#: Zaparoo's plaintext refusals of a client that must be paired: an encryption version
#: it does not support, and encryption required.
NEEDS_PAIRING_CODES = (-32001, -32002)


def _refusal(raw: str | bytes) -> bool:
    """Whether `raw` is Zaparoo's plaintext refusal of an unpaired client."""
    try:
        answer = json.loads(raw)
    except ValueError:
        return False
    error = answer.get("error") if isinstance(answer, dict) else None
    return isinstance(error, dict) and error.get("code") in NEEDS_PAIRING_CODES


class _Plain:
    """The frames of an unsecured Zaparoo: the JSON text as it is, both ways."""

    def first(self, text: str) -> str:
        """The request, as it is."""
        return text

    def read(self, raw: str) -> str:
        """The frame, as it is."""
        return raw


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
    if not _GAME_TEXT.fullmatch(zapscript):
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

    def __init__(
        self,
        address: str,
        *,
        port: int = PORT,
        api_key: str | None = None,
        connect_wait: float = CONNECT_WAIT,
        framing: Callable[[], Session] | None = None,
    ) -> None:
        """Reach Zaparoo at `address`; `api_key` is sent as a bearer token; `framing` encrypts."""
        self.address, self._connect_wait = address, connect_wait
        self._framing: Callable[[], Session] = framing or _Plain
        self._url = f"ws://{address}:{port}{PATH}"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def send(self, request: dict[str, Any], *, wait: float) -> dict[str, Any]:
        """Send one request and read until its own answer, skipping notifications."""
        try:
            async with asyncio.timeout(self._connect_wait + wait):
                async with websockets.connect(
                    self._url, open_timeout=self._connect_wait, additional_headers=self._headers
                ) as socket:
                    return await self._exchange(socket, request)
        except UnreachableError:
            raise
        except (TimeoutError, OSError, websockets.WebSocketException) as error:
            raise _unanswered(error, self.address) from error

    async def _exchange(self, socket: Any, request: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
        """Send `request` in this connection's framing and read until its own answer."""
        session = self._framing()
        await socket.send(session.first(json.dumps(request)))
        while True:
            answer = json.loads(self._open(session, await socket.recv()))
            if isinstance(answer, dict) and answer.get("id") == request["id"]:
                return answer

    def _open(self, session: Session, raw: str | bytes) -> str:
        """The JSON inside one frame; ZaparooNeedsPairingError when Zaparoo wants pairing."""
        # RULE: a refused login is said as needing pairing
        if _refusal(raw):
            msg = "Zaparoo wants this computer paired"
            raise ZaparooNeedsPairingError(msg, tried=[self.address])
        try:
            return session.read(raw if isinstance(raw, str) else raw.decode())
        except ValueError as error:
            raise ZaparooNeedsPairingError(str(error), tried=[self.address]) from error


def _unanswered(error: Exception, address: str) -> UnreachableError:
    """What a failed connection means: a MiSTer that refused it is on, without Zaparoo."""
    if isinstance(error, ConnectionRefusedError):
        return ZaparooNotRunningError("the MiSTer is on, but Zaparoo is not running on it", tried=[address])
    return UnreachableError(f"Zaparoo did not answer at {address}", tried=[address])


def connect_wait_for(count: int) -> float:
    """Seconds to wait for each of `count` addresses, so that all of them fit in FIND_WITHIN."""
    return min(CONNECT_WAIT, FIND_WITHIN / max(count, 1))


class FallbackTransport:
    """The MiSTer at the first of its addresses that answers: its name, then the spares."""

    def __init__(self, addresses: Sequence[str], *, reach: Callable[[str], Transport]) -> None:
        """Try `addresses` in order, each reached through `reach`."""
        self._addresses = list(addresses)
        self._at = {address: reach(address) for address in self._addresses}
        #: The address that answered last, asked first from then on.
        self.used: str | None = None

    def _order(self) -> list[str]:
        # RULE: addresses are tried in the order the settings give
        order = list(self._addresses)
        if self.used in order:
            order.remove(self.used)
            order.insert(0, self.used)
        return order

    async def send(self, request: dict[str, Any], *, wait: float) -> dict[str, Any]:
        """The answer from the first address that answers; UnreachableError naming all if none does."""
        for address in self._order():
            try:
                answer = await self._at[address].send(request, wait=wait)
            except (ZaparooNotRunningError, ZaparooNeedsPairingError):
                self.used = address
                raise
            except UnreachableError:
                continue
            self.used = address
            return answer
        msg = "the MiSTer did not answer at any of its addresses"
        raise UnreachableError(msg, tried=self._addresses)
