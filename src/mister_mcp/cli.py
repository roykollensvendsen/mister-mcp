"""Command line for mister-mcp: serve the tools to a voice session, or ask the MiSTer."""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
from typing import TYPE_CHECKING

from mister_mcp.server import build_server
from mister_mcp.service import MisterService
from mister_mcp.settings import SettingsError, load_settings, settings_path
from mister_mcp.simulator import SimulatedMister
from mister_mcp.tv import SimulatedTvPlugin, TvPlugin, TvSwitch
from mister_mcp.zaparoo import WebSocketTransport

if TYPE_CHECKING:
    from mister_mcp.zaparoo import Transport

#: Every verb this command has. The documentation test requires each one to
#: appear in a worked example, so a verb cannot be added without one.
COMMANDS: tuple[str, ...] = ("serve", "status")


def _service(*, simulate: bool, settings_file: str | None) -> MisterService:
    if simulate:
        return MisterService(SimulatedMister(), tv=SimulatedTvPlugin())
    path = pathlib.Path(settings_file).expanduser() if settings_file else settings_path()
    settings = load_settings(path)
    if not settings.address:
        msg = f"No MiSTer address in {path}; set [mister] address, or use --simulate."
        raise SettingsError(msg)
    transport: Transport = WebSocketTransport(settings.address, port=settings.port, api_key=settings.api_key)
    return MisterService(transport, tv=tv_from(settings.tv))


def tv_from(table: dict[str, object]) -> TvSwitch | None:
    """The TV step from the settings' [tv] table; None when there is none."""
    if not table:
        return None
    command, tv = table.get("command"), table.get("name")
    if not (isinstance(command, list) and command and isinstance(tv, str)):
        msg = "[tv] needs command = [...] and name = the TV as the TV plugin knows it."
        raise SettingsError(msg)
    return TvPlugin(command=[str(c) for c in command], tv=tv, device=str(table.get("device", "MiSTer")))


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="mister-mcp", description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--simulate", action="store_true", help="a pretend MiSTer, no network")
    parser.add_argument("--settings-file", help="instead of ~/.config/mister-mcp/config.toml")
    args = parser.parse_args(argv)
    try:
        service = _service(simulate=args.simulate, settings_file=args.settings_file)
    except SettingsError as error:
        sys.stderr.write(f"mister-mcp: {error}\n")
        return 2
    if args.command == "serve":  # pragma: no cover - runs until stdin closes
        asyncio.run(build_server(service, simulated=args.simulate).run_stdio_async())
        return 0
    answer = asyncio.run(service.status())
    prefix = "Simulated: " if args.simulate else ""
    sys.stdout.write(prefix + answer["say"] + "\n")
    return 0 if answer["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
