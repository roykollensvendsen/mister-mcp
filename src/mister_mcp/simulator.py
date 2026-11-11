# SPDX-License-Identifier: GPL-3.0-or-later
"""A pretend MiSTer running Zaparoo Core, for tests and for a first try by voice.

It answers the same JSON-RPC requests Zaparoo would, from a small library of
homebrew games, and never touches the network. It keeps every request it was
sent, so a test can say what reached the MiSTer.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import TYPE_CHECKING, Any

from ecdsa.ellipticcurve import Point

from mister_mcp.pairing import CURVE, U, V, confirm_keys, decode, encode, pairing_hmac
from mister_mcp.ssh import ALLOWED_COMMANDS, SSH_FAILED, NotAllowedCommandError, Reply
from mister_mcp.zaparoo import UnreachableError, ZaparooNotRunningError

if TYPE_CHECKING:
    from collections.abc import Callable

#: The address set aside for documentation, never anyone's real MiSTer.
ADDRESS = "192.0.2.10"

SYSTEMS: dict[str, str] = {
    "NES": "Nintendo Entertainment System",
    "SNES": "Super Nintendo Entertainment System",
    "Genesis": "Sega Genesis",
    "Gameboy": "Gameboy",
}
#: Homebrew games, by system.
GAMES: dict[str, tuple[str, ...]] = {
    "NES": ("Micro Mages", "Alter Ego"),
    "SNES": ("Super Boss Gaiden", "Nekotako"),
    "Genesis": ("Tanglewood", "Xeno Crisis"),
    "Gameboy": ("Tobu Tobu Girl", "240p Test Suite"),
}


def _game(system: str, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "path": f"/media/fat/games/{system}/{name}.rom",
        "zapScript": f"@{system}/{name}",
        "system": {"id": system, "name": SYSTEMS[system]},
    }


class SimulatedMister:
    """A transport that is the MiSTer: Zaparoo's answers, without a network."""

    def __init__(self, *, on: bool = True, zaparoo: bool = True) -> None:
        """A MiSTer at its menu; one switched off, answering nothing; or one on without Zaparoo."""
        self.on, self.zaparoo = on, zaparoo
        self.active: dict[str, Any] | None = None
        self.sent: list[dict[str, Any]] = []
        #: A further search result, as a test wants Zaparoo to have returned it.
        self.extra_result: dict[str, Any] | None = None
        #: When set, a start is acknowledged but the MiSTer keeps showing what it showed.
        self.ignores_runs = False
        #: When set, every start is refused with this (message, category), as Zaparoo would.
        self.run_error: tuple[str, str | None] | None = None
        #: How many reads after a start still show what ran before, as a real MiSTer loading a game.
        self.loads_after = 0
        self._loading = 0
        self._before: dict[str, Any] | None = None

    def play(self, system: str, name: str | None) -> None:
        """Make the MiSTer run `name` on `system`'s core, or the core alone."""
        self.active = {
            "systemId": system,
            "systemName": SYSTEMS[system],
            "mediaName": name or "",
            "mediaPath": f"/media/fat/games/{system}/{name}.rom" if name else "",
        }

    async def send(self, request: dict[str, Any], *, wait: float) -> dict[str, Any]:  # noqa: ARG002 - answers at once
        """Zaparoo's answer to `request`."""
        self._answers()
        self.sent.append(request)
        method, params = request["method"], request.get("params") or {}
        answer = {"jsonrpc": "2.0", "id": request["id"]}
        if method == "version":
            return answer | {"result": {"version": "2.22.1", "platform": "mister"}}
        if method == "media.active":
            return answer | {"result": self._shown()}
        if method == "systems":
            systems = [{"id": key, "name": name} for key, name in SYSTEMS.items()]
            return answer | {"result": {"systems": systems}}
        if method == "media.search":
            found = self._search(params)
            if self.extra_result and all(
                w in self.extra_result["name"].casefold()
                for w in str(params.get("query", "")).casefold().split()
            ):
                found.append(self.extra_result)
            return answer | {"result": {"results": found}}
        if method == "run":
            return answer | self._run(str(params.get("text", "")))
        return answer | {"error": {"code": -32601, "message": "method not found"}}

    def _shown(self) -> dict[str, Any] | None:
        """What media.active reports: what ran before a start, while the new game still loads."""
        if self._loading:
            self._loading -= 1
            return self._before
        return self.active

    def _answers(self) -> None:
        """Raise as the WebSocket would when this MiSTer is off, or on without Zaparoo."""
        if not self.on:
            msg = "the simulated MiSTer is off"
            raise UnreachableError(msg, tried=[ADDRESS])
        if not self.zaparoo:
            msg = "the simulated MiSTer is on, but Zaparoo is not running on it"
            raise ZaparooNotRunningError(msg, tried=[ADDRESS])

    @staticmethod
    def _search(params: dict[str, Any]) -> list[dict[str, Any]]:
        words = str(params.get("query", "")).casefold().split()
        found = [
            _game(system, name)
            for system, names in GAMES.items()
            for name in names
            if all(word in name.casefold() for word in words)
        ]
        return found[: int(params.get("maxResults", 100))]

    def _run(self, text: str) -> dict[str, Any]:
        if self.run_error:
            message, category = self.run_error
            return {
                "error": {"code": 1, "message": message, "data": {"category": category} if category else {}}
            }
        if self.ignores_runs:
            return {"result": None}
        self._before, self._loading = self.active, self.loads_after
        if text.startswith("**launch.system:"):
            system = text.removeprefix("**launch.system:")
            if system in SYSTEMS:
                self.play(system, None)
                return {"result": None}
        elif text.startswith("@") and "/" in text:
            system, name = text[1:].split("/", 1)
            if name in GAMES.get(system, ()):
                self.play(system, name)
                return {"result": None}
        return {"error": {"code": 1, "message": "media not found", "data": {"category": "media_not_found"}}}


class SimulatedShell:
    """A pretend MiSTer over SSH: answers the fixed commands as a MiSTer would, and keeps what it was sent."""

    def __init__(  # noqa: PLR0913 - each is one thing a test sets about the MiSTer
        self,
        *,
        free_mb: int | None = 4096,
        running: bool = False,
        uptime: float = 3600.0,
        live_log: list[str] | None = None,
        saved_log: list[str] | None = None,
        key_refused: bool = False,
        on: bool = True,
    ) -> None:
        """A MiSTer with `free_mb` free on its SD card, up for `uptime` seconds."""
        self.free_mb, self.running, self.uptime = free_mb, running, uptime
        self.live_log, self.saved_log = live_log, saved_log
        self.key_refused, self.on = key_refused, on
        #: The names of the commands sent, in order.
        self.sent: list[str] = []

    async def run(self, name: str) -> Reply:
        """The MiSTer's reply to the command called `name`."""
        if name not in ALLOWED_COMMANDS:
            msg = f"{name!r} is not a command this plugin sends"
            raise NotAllowedCommandError(msg)
        if not self.on:
            said = f"ssh: connect to host {ADDRESS} port 22: Connection timed out"
            return Reply(SSH_FAILED, "", said, ADDRESS)
        if self.key_refused:
            return Reply(SSH_FAILED, "", f"root@{ADDRESS}: Permission denied (publickey).", ADDRESS)
        self.sent.append(name)
        answers: dict[str, Callable[[], Reply]] = {
            "free_space": self._free_space,
            "running": self._running,
            "uptime": self._uptime,
            "live_log": self._live_log,
            "saved_log": self._saved_log,
            "start": self._start,
        }
        return answers[name]()

    def _reply(self, out: str, code: int = 0) -> Reply:
        return Reply(code, out, "", ADDRESS)

    def _free_space(self) -> Reply:
        if self.free_mb is None:  # a df whose answer cannot be read
            return self._reply("df: unrecognised output\n")
        free = self.free_mb * 1024
        return self._reply(
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            f"/dev/mmcblk0p1 31000000 {31000000 - free} {free} 90% /media/fat\n"
        )

    def _running(self) -> Reply:
        return self._reply("1234\n", 0) if self.running else self._reply("", 1)

    def _uptime(self) -> Reply:
        return self._reply(f"{self.uptime:.2f} 100.00\n")

    def _live_log(self) -> Reply:
        return self._log(self.live_log)

    def _saved_log(self) -> Reply:
        return self._log(self.saved_log)

    def _log(self, lines: list[str] | None) -> Reply:
        if lines is None:
            return Reply(1, "", "tail: can't open: No such file or directory", ADDRESS)
        return self._reply("\n".join(lines) + "\n")

    def _start(self) -> Reply:
        self.running, self.live_log = True, ["Update All 2.3"]
        return self._reply("")


class SimulatedPairing:
    """A pretend secured Zaparoo that pairs with SIMULATED_PIN, answering as Core's endpoints do."""

    #: The PIN the pretend Zaparoo shows.
    PIN = "000000"

    def __init__(self) -> None:
        """A pretend Zaparoo with a pairing window open."""
        self._pin = self.PIN.encode()
        self._alpha = 1 + secrets.randbelow(CURVE.order - 1)
        self._a = self._b = self._key = b""
        self._name = ""

    async def __call__(self, path: str, body: dict[str, str]) -> tuple[int, dict[str, Any]]:
        """Zaparoo's answer to a POST of `body` to `path`."""
        if path == "/api/pair/start":
            return self._start(body)
        return self._finish(body)

    def _start(self, body: dict[str, str]) -> tuple[int, dict[str, Any]]:
        self._a, self._name = base64.b64decode(body["pake"]), body["name"]
        x = decode(self._a, role=0)["x"]
        pw = int.from_bytes(self._pin, "big")
        y = pw * V + self._alpha * CURVE.generator
        z = self._alpha * (Point(CURVE.curve, *x) + (-(pw * U)))
        digest = hashlib.sha256(self._pin)
        for n in (*x, y.x(), y.y(), z.x(), z.y()):
            digest.update(n.to_bytes((n.bit_length() + 7) // 8, "big"))
        self._key = digest.digest()
        self._b = encode(1, {"u": (U.x(), U.y()), "v": (V.x(), V.y()), "x": x, "y": (y.x(), y.y())})
        return 200, {"session": "simulated", "pake": base64.b64encode(self._b).decode()}

    def _finish(self, body: dict[str, str]) -> tuple[int, dict[str, Any]]:
        a_key, b_key, _ = confirm_keys(self._key, self._a, self._b)
        if base64.b64decode(body["confirm"]) != pairing_hmac(a_key, "client", self._name, self._a, self._b):
            return 401, {}
        server = pairing_hmac(b_key, "server", self._name, self._a, self._b)
        confirm = base64.b64encode(server).decode()
        return 200, {"authToken": "simulated", "clientId": "simulated", "confirm": confirm}
