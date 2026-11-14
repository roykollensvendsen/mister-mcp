# SPDX-License-Identifier: GPL-3.0-or-later
"""Which version of a game a file is, read from its name as No-Intro and GoodTools write it.

    Tetris (USA, Europe).nes            Europe (a file for several regions counts as the best one)
    Super Mario Bros (E) [a1].nes       Europe, an alternate dump
    Super Mario Bros (JU) [h1].nes      USA, a hack
    Super Mario Bros (PC10).nes         the PlayChoice-10 arcade version, no region

The voice hears the clean cartridge first, in the owner's region order. Hacks,
pirates, trained and translated files, arcade versions, and an alternate dump
of a title and region that also has a clean one, are left out unless the owner
asks for all versions.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Any

#: Every region a game can be asked for, as the voice and the settings name it.
REGIONS = ("eu", "world", "us", "jp")
#: The order when the owner set none and the locale names no region.
FALLBACK_ORDER = ("world", "us", "eu", "jp")
#: How each region is said aloud.
REGION_SAID = {"eu": "Europe", "world": "World", "us": "USA", "jp": "Japan"}
#: The kinds of version left out unless the owner asks for all versions. An alternate
#: dump is left out too, but only beside a clean one of its title and region.
HIDDEN_KINDS = frozenset({"hack", "pirate", "trained", "translated", "arcade"})

#: A region as No-Intro spells it out, inside "(...)", one of a comma-separated list.
_NO_INTRO = {"europe": "eu", "world": "world", "usa": "us", "japan": "jp"}
#: GoodTools' one-letter regions, written together: (E), (U), (JU), (UE).
_GOODTOOLS = {"E": "eu", "W": "world", "U": "us", "J": "jp"}
_ONE_LETTERS = re.compile(r"[EWUJ]{1,4}")
_GROUP = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")
#: GoodTools' bracket marks, by what they say; [!] is a verified dump, no kind.
_MARKS = (
    (re.compile(r"T[+-].*"), "translated"),
    (re.compile(r"h.*"), "hack"),
    (re.compile(r"p\d*"), "pirate"),
    (re.compile(r"t\d*"), "trained"),
    (re.compile(r"a\d*"), "alternate"),
)


@dataclass(frozen=True)
class Version:
    """What a file's name says about it."""

    #: The first of the regions it names, in REGIONS' order; None when it names none.
    region: str | None
    #: Every region it names: "(USA, Europe)" is for both.
    regions: frozenset[str]
    #: hack, pirate, trained, translated, arcade or alternate; None for a clean cartridge.
    kind: str | None
    #: Whether GoodTools marked it [!], a dump checked against the cartridge.
    verified: bool
    #: The title with every (...) and [...] taken out, to find an alternate's clean twin.
    title: str


def _regions(text: str) -> set[str]:
    """The regions one "(...)" names, as No-Intro or GoodTools write them."""
    if _ONE_LETTERS.fullmatch(text):
        return {_GOODTOOLS[letter] for letter in text}
    return {_NO_INTRO[word] for word in (w.strip().casefold() for w in text.split(",")) if word in _NO_INTRO}


def _paren_kind(text: str) -> str | None:
    """The kind one "(...)" says: the PlayChoice-10 arcade version, or a named hack."""
    if text == "PC10":
        return "arcade"
    return "hack" if text.endswith("Hack") else None


def _bracket_kind(text: str) -> str | None:
    """The kind one "[...]" says."""
    return next((kind for pattern, kind in _MARKS if pattern.fullmatch(text)), None)


def version_of(result: dict[str, Any]) -> Version:
    """The version a search result is, from its file's name."""
    stem = pathlib.PurePosixPath(str(result.get("path", ""))).stem
    regions: set[str] = set()
    kinds: list[str] = []
    for paren, bracket in _GROUP.findall(stem):
        regions |= _regions(paren)
        kinds += [k for k in (_paren_kind(paren), _bracket_kind(bracket)) if k]
    # RULE: a region is read from the file name as no intro and goodtools write it
    region = next((r for r in REGIONS if r in regions), None)
    kind = next((k for k in kinds if k in HIDDEN_KINDS), kinds[0] if kinds else None)
    title = " ".join(_GROUP.sub(" ", stem).casefold().split())
    return Version(region=region, regions=frozenset(regions), kind=kind, verified="[!]" in stem, title=title)


def _system(result: dict[str, Any]) -> str:
    return str((result.get("system") or {}).get("id", ""))


def _hidden(result: dict[str, Any], clean: set[tuple[str, str, str | None]]) -> bool:
    version = version_of(result)
    # RULE: hacks pirates trained translated and arcade files are hidden unless all versions are asked for
    if version.kind in HIDDEN_KINDS:
        return True
    # RULE: an alternate dump is hidden only when a clean one of the same title and region exists
    return version.kind == "alternate" and (_system(result), version.title, version.region) in clean


def chosen(
    results: list[dict[str, Any]], *, all_versions: bool, order: tuple[str, ...]
) -> tuple[list[dict[str, Any]], int]:
    """The results the voice hears, in the owner's region `order`, and how many were left out."""
    shown = results
    if not all_versions:
        versions = [(r, version_of(r)) for r in results]
        clean = {(_system(r), v.title, v.region) for r, v in versions if v.kind is None}
        shown = [r for r in results if not _hidden(r, clean)]
    rank = {region: place for place, region in enumerate(order)}

    def place(result: dict[str, Any]) -> tuple[int, int, int]:
        version = version_of(result)
        # RULE: a clean cartridge comes before every other version whatever its region
        clean = {None: 0, "alternate": 1}.get(version.kind, 2)
        # RULE: a verified dump comes before an unmarked one in the same region
        verified = 0 if version.verified else 1
        # RULE: hits come in the region order given then those with no region
        region = min((rank[r] for r in version.regions if r in rank), default=len(rank))
        return clean, region, verified

    return sorted(shown, key=place), len(results) - len(shown)
