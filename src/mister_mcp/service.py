# SPDX-License-Identifier: GPL-3.0-or-later
"""What each tool does, as answers the voice can read aloud.

Every answer has ``say``, read aloud as it is, and ``success`` with ``outcome``
for a program: ``done``, ``unreachable`` (the MiSTer did not answer),
``not_found``, ``refused``, ``working`` (still going after the voice's time).
"""

from __future__ import annotations

from typing import Any

from mister_mcp.tv import TvSwitch, show_mister
from mister_mcp.zaparoo import (
    NotAllowedError,
    Transport,
    UnreachableError,
    Zaparoo,
    ZaparooError,
    ZaparooNotRunningError,
    game_text,
    system_text,
)

#: What the voice hears when Zaparoo on the MiSTer does not answer.
UNREACHABLE = (
    "The MiSTer is not answering, so it is off or not on the network. "
    "Switch it on, wait a minute, and ask again."
)
#: What the voice hears when the MiSTer is on but Zaparoo on it is not running.
NOT_RUNNING = (
    "The MiSTer is on, but Zaparoo isn't running on it. "
    "Start Zaparoo from the MiSTer's Scripts menu, and ask again."
)
#: The most games one answer reads out; the voice cannot list a hundred.
MAX_RESULTS = 5


def _unreachable(error: UnreachableError, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    say = NOT_RUNNING if isinstance(error, ZaparooNotRunningError) else UNREACHABLE
    return {"success": False, "outcome": "unreachable", "say": say, **fields}


def _game(result: dict[str, Any]) -> dict[str, str]:
    """A search result as the voice needs it: its name and its system's name."""
    system = result.get("system") or {}
    return {"name": str(result.get("name", "")), "system": str(system.get("name") or system.get("id") or "")}


def _listed(games: list[dict[str, str]]) -> str:
    named = [f"{g['name']} on the {g['system']}" for g in games]
    return named[0] if len(named) == 1 else ", ".join(named[:-1]) + ", and " + named[-1]


def _refused(say: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"success": False, "outcome": "refused", "say": say, **fields}


def _plain(text: str) -> str:
    return " ".join(text.casefold().split())


def _system_said(said: str, systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The systems `said` names: the whole id or name, or else words of the name."""
    wanted = _plain(said)
    exact = [s for s in systems if wanted in (_plain(str(s.get("id", ""))), _plain(str(s.get("name", ""))))]
    if exact:
        return exact
    return [s for s in systems if wanted and wanted in _plain(str(s.get("name", "")))]


def describe(active: dict[str, Any] | None) -> str:
    """What the MiSTer is running, as a phrase: "playing X on Y", or "at its menu"."""
    if not active:
        return "at its menu"
    system = active.get("systemName") or active.get("systemId") or "an unknown system"
    game = active.get("mediaName")
    return f"playing {game} on the {system}" if game else f"running the {system} core, with no game"


class MisterService:
    """The MiSTer, reached through Zaparoo Core."""

    def __init__(self, transport: Transport, *, tv: TvSwitch | None = None) -> None:
        """Reach the MiSTer through `transport`; show it on `tv` after a start, when one is set."""
        self.zaparoo = Zaparoo(transport)
        self.tv = tv

    async def status(self) -> dict[str, Any]:
        """Whether the MiSTer answers, and what it is running."""
        try:
            active = await self.zaparoo.active()
        except ZaparooNotRunningError as error:
            # RULE: a mister that answers without zaparoo is called on
            return _unreachable(error, on=True, system=None, game=None)
        except UnreachableError as error:
            # RULE: a mister that does not answer is not called on or off
            return _unreachable(error, on=None, system=None, game=None)
        return {
            "success": True,
            "outcome": "done",
            "say": f"The MiSTer is on, {describe(active)}.",
            "on": True,
            "system": (active or {}).get("systemName") or None,
            "game": (active or {}).get("mediaName") or None,
        }

    async def search(self, name: str) -> dict[str, Any]:
        """The games whose names hold every word of `name`, at most MAX_RESULTS of them."""
        try:
            results = await self.zaparoo.search(name, max_results=MAX_RESULTS + 1)
        except UnreachableError as error:
            return _unreachable(error, games=[])
        games = [_game(r) for r in results]
        if not games:
            return {
                "success": False,
                "outcome": "not_found",
                "say": f"The MiSTer has no game called {name}. Try fewer words, or another name.",
                "games": [],
            }
        more = len(games) > MAX_RESULTS
        games = games[:MAX_RESULTS]
        say = f"I found {_listed(games)}."
        if more:
            say += " There are more; say more of the name to narrow it down."
        return {"success": True, "outcome": "done", "say": say, "games": games}

    async def launch(self, game: str | None = None, system: str | None = None) -> dict[str, Any]:
        """Start a game by its name, or a system's core alone; then show the MiSTer on the TV."""
        try:
            started = await self._start(game, system)
        except UnreachableError as error:
            return _unreachable(error, game=None, system=None)
        if not started["success"] or self.tv is None:
            return started
        # RULE: the tv is touched only once the game started
        tv = await show_mister(self.tv)
        return started | {"say": f"{started['say']} {tv['say']}", "tv": tv}

    async def _start(self, game: str | None, system: str | None) -> dict[str, Any]:
        systems = await self.zaparoo.systems()
        chosen: dict[str, Any] | None = None
        if system:
            fits = _system_said(system, systems)
            if len(fits) != 1:
                named = " or ".join(str(s.get("name")) for s in fits) or "no system by that name"
                return _refused(f"The MiSTer has {named}. Say which system.", game=None, system=None)
            chosen = fits[0]
        if game:
            return await self._start_game(game, chosen)
        if chosen is None:
            return _refused("Say a game, or a system to start with no game.", game=None, system=None)
        text = system_text(str(chosen["id"]), [str(s.get("id")) for s in systems])
        return await self._run(text, game=None, system=str(chosen.get("name")))

    async def _start_game(self, game: str, system: dict[str, Any] | None) -> dict[str, Any]:
        results = await self.zaparoo.search(game, max_results=MAX_RESULTS + 1)
        if system is not None:
            results = [r for r in results if (r.get("system") or {}).get("id") == system.get("id")]
        exact = [r for r in results if _plain(str(r.get("name", ""))) == _plain(game)]
        picked = exact if len(exact) == 1 else results
        if not picked:
            say = f"The MiSTer has no game called {game}. Try fewer words, or another name."
            return {"success": False, "outcome": "not_found", "say": say, "game": None, "system": None}
        if len(picked) > 1:
            games = [_game(r) for r in picked[:MAX_RESULTS]]
            return _refused(f"Which one: {_listed(games)}?", game=None, system=None, games=games)
        found = _game(picked[0])
        try:
            text = game_text(str(picked[0].get("zapScript", "")))
        except NotAllowedError:
            return _refused(
                f"I may not start {found['name']} the way the MiSTer lists it.", game=None, system=None
            )
        return await self._run(text, game=found["name"], system=found["system"])

    async def _run(self, text: str, *, game: str | None, system: str | None) -> dict[str, Any]:
        try:
            await self.zaparoo.run(text)
        except ZaparooError as error:
            say = f"The MiSTer did not start it: {error}. Try again, or ask what it is playing."
            return _refused(say, game=None, system=None, reason=error.category)
        # RULE: a start is said as done only once the mister shows it
        active = await self.zaparoo.active()
        shows = (active or {}).get("mediaName") or None
        if active and shows == game and (game or active.get("systemName") == system):
            say = f"Started. The MiSTer is {describe(active)}."
            return {"success": True, "outcome": "done", "say": say, "game": game, "system": system}
        say = f"I sent the start, but the MiSTer is {describe(active)}."
        return {"success": False, "outcome": "unverified", "say": say, "game": shows, "system": system}
