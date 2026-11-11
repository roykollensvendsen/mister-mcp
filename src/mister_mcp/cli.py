"""Command line for mister-mcp: serve the tools to a voice session, or ask the MiSTer."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import pathlib
import sys
from typing import TYPE_CHECKING

from mister_mcp.pairing import (
    PAIRING_FILE,
    EncryptedSession,
    PairingError,
    http_post,
    load_pairing,
    pair,
    save_pairing,
)
from mister_mcp.server import build_server
from mister_mcp.service import MisterService
from mister_mcp.settings import FOLDER, SettingsError, load_settings, settings_path
from mister_mcp.simulator import SimulatedMister, SimulatedPairing, SimulatedShell
from mister_mcp.ssh import SshShell
from mister_mcp.tv import SimulatedTvPlugin, TvPlugin, TvSwitch
from mister_mcp.updater import UpdateService
from mister_mcp.zaparoo import FallbackTransport, WebSocketTransport, connect_wait_for

if TYPE_CHECKING:
    from collections.abc import Callable

    from mister_mcp.zaparoo import Transport

#: Every verb this command has. The documentation test requires each one to
#: appear in a worked example, so a verb cannot be added without one.
COMMANDS: tuple[str, ...] = ("serve", "status", "pair")
#: The name Zaparoo lists this computer's pairing under.
CLIENT_NAME = "mister-mcp"
#: What is asked for the PIN; what is typed is not shown.
ASK_PIN = "Type the six digits Zaparoo shows on the MiSTer: "


#: The SSH key the MiSTer accepts, alone in its file, never printed.
SSH_KEY = FOLDER / "ssh-key"
#: How long past update_all runs took, for the next estimate.
UPDATE_RUNS = FOLDER / "update-runs.json"


def _service(*, simulate: bool, settings_file: str | None) -> tuple[MisterService, UpdateService]:
    if simulate:
        mister = SimulatedMister()
        updater = UpdateService(SimulatedShell(), mister, history=None)
        return MisterService(mister, tv=SimulatedTvPlugin()), updater
    path = pathlib.Path(settings_file).expanduser() if settings_file else settings_path()
    settings = load_settings(path)
    where = settings.where()
    if not where:
        msg = f"No MiSTer address in {path}; set [mister] address there, or use --simulate."
        raise SettingsError(msg)
    wait = connect_wait_for(len(where))
    framing = framing_from_pairing()

    def reach(address: str) -> Transport:
        return WebSocketTransport(
            address, port=settings.port, api_key=settings.api_key, connect_wait=wait, framing=framing
        )

    transport: Transport = FallbackTransport(where, reach=reach)
    shell = SshShell(where, key_file=str(SSH_KEY))
    updater = UpdateService(shell, transport, history=UPDATE_RUNS.expanduser())
    return MisterService(transport, tv=tv_from(settings.tv)), updater


def framing_from_pairing() -> Callable[[], EncryptedSession] | None:
    """Encrypted sessions with the kept pairing; None when this computer is not paired."""
    try:
        paired = load_pairing((FOLDER / PAIRING_FILE).expanduser())
    except PairingError as error:
        raise SettingsError(str(error)) from error
    if paired is None:
        return None
    return lambda: EncryptedSession(paired)


def tv_from(table: dict[str, object]) -> TvSwitch | None:
    """The TV step from the settings' [tv] table; None when there is none."""
    if not table:
        return None
    command, tv = table.get("command"), table.get("name")
    if not (isinstance(command, list) and command and isinstance(tv, str)):
        msg = (
            "The [tv] settings are incomplete. "
            "Set command = [...] and name = the TV as the TV plugin knows it."
        )
        raise SettingsError(msg)
    return TvPlugin(command=[str(c) for c in command], tv=tv, device=str(table.get("device", "MiSTer")))


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="mister-mcp", description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--simulate", action="store_true", help="a pretend MiSTer, no network")
    parser.add_argument("--settings-file", help="instead of ~/.config/mister-mcp/config.toml")
    args = parser.parse_args(argv)
    if args.command == "pair":
        return _pair(simulate=args.simulate, settings_file=args.settings_file)
    try:
        service, updater = _service(simulate=args.simulate, settings_file=args.settings_file)
    except SettingsError as error:
        sys.stderr.write(f"mister-mcp: {error}\n")
        return 2
    if args.command == "serve":  # pragma: no cover - runs until stdin closes
        asyncio.run(build_server(service, updater=updater, simulated=args.simulate).run_stdio_async())
        return 0
    answer = asyncio.run(service.status())
    prefix = "Simulated: " if args.simulate else ""
    sys.stdout.write(prefix + answer["say"] + "\n")
    return 0 if answer["success"] else 1


def _address(settings_file: str | None) -> tuple[str, int]:
    """The MiSTer's first address and Zaparoo's port, from the owner's settings."""
    path = pathlib.Path(settings_file).expanduser() if settings_file else settings_path()
    settings = load_settings(path)
    where = settings.where()
    if not where:
        msg = f"No MiSTer address in {path}; set [mister] address there."
        raise SettingsError(msg)
    return where[0], settings.port


def _pair(*, simulate: bool, settings_file: str | None) -> int:
    """Pair this computer with a secured Zaparoo, with the PIN the owner types; keep the pairing."""
    if simulate:
        asyncio.run(pair(SimulatedPairing.PIN, name=CLIENT_NAME, post=SimulatedPairing()))
        sys.stdout.write("Simulated: Paired with the MiSTer. Nothing was saved.\n")
        return 0
    address = ""
    try:
        address, port = _address(settings_file)
        # RULE: the pin is typed by the owner and never shown
        pin = getpass.getpass(ASK_PIN).strip()
        paired = asyncio.run(pair(pin, name=CLIENT_NAME, post=http_post(address, port)))
    except (SettingsError, PairingError) as error:
        sys.stderr.write(f"mister-mcp: {error}\n")
        return 1
    except OSError:
        sys.stderr.write(f"mister-mcp: Could not reach Zaparoo at {address}. Check that the MiSTer is on.\n")
        return 1
    save_pairing((FOLDER / PAIRING_FILE).expanduser(), paired)
    sys.stdout.write(f"Paired with the MiSTer at {address}. Restart the voice plugin to use it.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
