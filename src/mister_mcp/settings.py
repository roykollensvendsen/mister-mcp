# SPDX-License-Identifier: GPL-3.0-or-later
"""The owner's settings, read from ``~/.config/mister-mcp``, never from this repository.

    [mister]
    address = "192.0.2.10"   # the MiSTer on the home network
    port = 7497              # Zaparoo Core's API port, when changed there

A Zaparoo API key, when Zaparoo asks for one, sits alone in ``zaparoo-key``
beside the settings, readable by the owner only. It is never logged or shown.
"""

from __future__ import annotations

import os
import pathlib
import stat
import tomllib
from dataclasses import dataclass, field
from typing import Any

from mister_mcp.zaparoo import PORT

#: The folder the owner's settings and keys live in.
FOLDER = pathlib.Path("~/.config/mister-mcp")


class SettingsError(ValueError):
    """The settings cannot be used as they are."""


@dataclass(frozen=True)
class Settings:
    """Where the MiSTer is, and how to reach Zaparoo on it."""

    address: str | None = None
    #: Spare addresses, tried in order when `address` does not answer.
    addresses: tuple[str, ...] = ()
    port: int = PORT
    api_key: str | None = field(default=None, repr=False)
    tv: dict[str, Any] = field(default_factory=dict)

    def where(self) -> list[str]:
        """Every address to try, in order: the main one, then the spares, each once."""
        return list(dict.fromkeys([*([self.address] if self.address else []), *self.addresses]))


def settings_path() -> pathlib.Path:
    """The settings file: ``$MISTER_MCP_SETTINGS``, or ``~/.config/mister-mcp/config.toml``."""
    return pathlib.Path(os.environ.get("MISTER_MCP_SETTINGS", str(FOLDER / "config.toml"))).expanduser()


def _key(path: pathlib.Path) -> str | None:
    if not path.is_file():
        return None
    # RULE: a key file others can read is refused
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        msg = f"{path} can be read by others; run: chmod 600 {path}"
        raise SettingsError(msg)
    return path.read_text().strip() or None


def load_settings(path: pathlib.Path) -> Settings:
    """The settings in `path`; an absent file means nothing is set."""
    try:
        table = tomllib.loads(path.read_text()) if path.is_file() else {}
    except tomllib.TOMLDecodeError as error:
        msg = f"{path} is not valid TOML ({error}); fix that line, or use --simulate meanwhile."
        raise SettingsError(msg) from error
    mister = table.get("mister", {})
    return Settings(
        address=mister.get("address"),
        addresses=tuple(str(a) for a in mister.get("addresses", [])),
        port=int(mister.get("port", PORT)),
        api_key=_key(path.with_name("zaparoo-key")),
        tv=dict(table.get("tv", {})),
    )
