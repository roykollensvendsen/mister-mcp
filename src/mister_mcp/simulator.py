# SPDX-License-Identifier: GPL-3.0-or-later
"""A pretend MiSTer running Zaparoo Core, for tests and for a first try by voice.

It answers the same JSON-RPC requests Zaparoo would, from a small library of
homebrew games, and never touches the network. It keeps every request it was
sent, so a test can say what reached the MiSTer.
"""

from __future__ import annotations

from typing import Any

from mister_mcp.zaparoo import UnreachableError

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

    def __init__(self, *, on: bool = True) -> None:
        """A MiSTer at its menu, or one that is switched off and answers nothing."""
        self.on = on
        self.active: dict[str, Any] | None = None
        self.sent: list[dict[str, Any]] = []

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
        if not self.on:
            msg = "the simulated MiSTer is off"
            raise UnreachableError(msg)
        self.sent.append(request)
        method, params = request["method"], request.get("params") or {}
        answer = {"jsonrpc": "2.0", "id": request["id"]}
        if method == "version":
            return answer | {"result": {"version": "2.22.1", "platform": "mister"}}
        if method == "media.active":
            return answer | {"result": self.active}
        if method == "systems":
            systems = [{"id": key, "name": name} for key, name in SYSTEMS.items()]
            return answer | {"result": {"systems": systems}}
        if method == "media.search":
            return answer | {"result": {"results": self._search(params)}}
        if method == "run":
            return answer | self._run(str(params.get("text", "")))
        return answer | {"error": {"code": -32601, "message": "method not found"}}

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
