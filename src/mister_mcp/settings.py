# SPDX-License-Identifier: GPL-3.0-or-later
"""The owner's settings, read from ``~/.config/mister-mcp``, never from this repository.

    [mister]
    address = "192.0.2.10"   # the MiSTer on the home network
    port = 7497              # Zaparoo Core's API port, when changed there

    [search]
    region_order = ["eu", "world", "us", "jp"]   # which version of a game comes first

Unset, the region order comes from the locale (LC_ALL, then LANG): a European
country puts Europe first, en_US the USA, ja_JP Japan. With no locale, as under
the claude-voice bridge, which passes plugins none, it is world, USA, Europe,
Japan.

A Zaparoo API key, when Zaparoo asks for one, sits alone in ``zaparoo-key``
beside the settings, readable by the owner only. It is never logged or shown.
"""

from __future__ import annotations

import os
import pathlib
import stat
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mister_mcp.versions import FALLBACK_ORDER, REGIONS
from mister_mcp.zaparoo import PORT

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

#: The countries whose locale puts Europe first: the EU and the EEA, and the rest of Europe.
EUROPE = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
        "IS",
        "LI",
        "NO",
        "GB",
        "CH",
        "AD",
        "AL",
        "BA",
        "BY",
        "FO",
        "GI",
        "MC",
        "MD",
        "ME",
        "MK",
        "RS",
        "SM",
        "UA",
        "VA",
    }
)
#: The four regions, as a settings file writes them.
REGIONS_SAID = ", ".join(f'"{r}"' for r in REGIONS)
#: The region a locale's country puts first.
COUNTRY_FIRST = {**dict.fromkeys(EUROPE, "eu"), "US": "us", "JP": "jp"}
#: The region a locale with a language and no country puts first: Norwegian, in its three names.
LANGUAGE_FIRST = dict.fromkeys(("no", "nb", "nn"), "eu")

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
    #: Which region's version of a game the voice hears first, and next; all four, once each.
    region_order: tuple[str, ...] = FALLBACK_ORDER
    #: Where the region order came from: "settings", a locale such as "nb_NO.UTF-8", or "".
    region_from: str = ""

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


def _keys(table: dict[str, Any]) -> Iterator[str]:
    """Every key in `table`, at any depth."""
    for key, value in table.items():
        yield key
        if isinstance(value, dict):
            yield from _keys(value)


def _no_password(table: dict[str, Any], path: pathlib.Path) -> None:
    """Refuse a settings file that holds a password anywhere: the MiSTer is reached by key only."""
    held = next((key for key in _keys(table) if "password" in key.casefold()), None)
    if held:
        msg = (
            f"{path} holds a password ({held}); the MiSTer is reached by key only. "
            "Remove that line, and run ssh-copy-id root@<the MiSTer> in a terminal instead."
        )
        raise SettingsError(msg)


def _first_region(locale: str) -> str | None:
    """The region a locale such as "nb_NO.UTF-8" puts first; None for C, POSIX and other places."""
    language, _, country = locale.split(".", 1)[0].split("@", 1)[0].partition("_")
    return COUNTRY_FIRST.get(country) if country else LANGUAGE_FIRST.get(language)


def _then_the_rest(first: tuple[str, ...]) -> tuple[str, ...]:
    """`first`, then every other region in the fallback order."""
    return (*first, *(r for r in FALLBACK_ORDER if r not in first))


def _set_order(said: object, path: pathlib.Path) -> tuple[tuple[str, ...], str]:
    """The region order the owner set, refused unless it is a list of the four regions."""
    # RULE: an unknown region in the settings is refused naming the setting and the four
    if not (isinstance(said, list) and said and set(said) <= set(REGIONS)):
        msg = f"{path}: [search] region_order must be a list of {REGIONS_SAID}; it is {said!r}."
        raise SettingsError(msg)
    return _then_the_rest(tuple(dict.fromkeys(said))), "settings"


def _locale_order(env: Mapping[str, str]) -> tuple[tuple[str, ...], str]:
    """The region order the locale puts first, and that locale; the fallback when it names none."""
    locale = env.get("LC_ALL") or env.get("LANG") or ""
    # RULE: an unset region order comes from the locale
    first = _first_region(locale)
    return (_then_the_rest((first,)), locale) if first else (FALLBACK_ORDER, "")


def _region_order(
    table: dict[str, Any], path: pathlib.Path, env: Mapping[str, str]
) -> tuple[tuple[str, ...], str]:
    """The owner's region order and where it came from: the settings, else the locale, else none."""
    if "region_order" in table:
        return _set_order(table["region_order"], path)
    return _locale_order(env)


def region_note(settings: Settings) -> str:
    """The line the server logs at start-up: which region order it uses, and why."""
    order = ", ".join(settings.region_order)
    if settings.region_from == "settings":
        return f"region_order: {order}"
    if settings.region_from:
        return f"region_order unset: using {order}, from the locale {settings.region_from}"
    return f"region_order unset and no locale given: using {order}"


def load_settings(path: pathlib.Path, env: Mapping[str, str] = os.environ) -> Settings:
    """The settings in `path`; an absent file means nothing is set."""
    try:
        table = tomllib.loads(path.read_text()) if path.is_file() else {}
    except tomllib.TOMLDecodeError as error:
        msg = f"{path} is not valid TOML ({error}); fix that line, or use --simulate meanwhile."
        raise SettingsError(msg) from error
    mister = table.get("mister", {})
    _no_password(table, path)
    order, source = _region_order(table.get("search", {}), path, env)
    return Settings(
        region_order=order,
        region_from=source,
        address=mister.get("address"),
        addresses=tuple(str(a) for a in mister.get("addresses", [])),
        port=int(mister.get("port", PORT)),
        api_key=_key(path.with_name("zaparoo-key")),
        tv=dict(table.get("tv", {})),
    )
