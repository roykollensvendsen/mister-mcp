# SPDX-License-Identifier: GPL-3.0-or-later
"""Which version of a game a file is, read from its name as No-Intro and GoodTools write it."""

import pytest

from mister_mcp.versions import FALLBACK_ORDER, chosen, version_of

EUROPE_FIRST = ("eu", "world", "us", "jp")


def _hit(file, system="NES", name="Super Mario Bros"):
    return {"name": name, "path": f"/media/fat/games/{system}/{file}", "system": {"id": system}}


@pytest.mark.parametrize(
    ("file", "region"),
    [
        ("Tetris (Europe).nes", "eu"),
        ("Tetris (USA, Europe).nes", "eu"),
        ("Tetris (World).nes", "world"),
        ("Tetris (USA).nes", "us"),
        ("Tetris (Japan).nes", "jp"),
        ("Tetris (Japan, USA).nes", "us"),
        ("Super Mario Bros (E).nes", "eu"),
        ("Super Mario Bros (JU).nes", "us"),
        ("Super Mario Bros (J).nes", "jp"),
        ("Super Mario Bros (W).nes", "world"),
        ("Tetris (USA) (Rev 1).nes", "us"),
        ("Super Mario Bros (PC10).nes", None),
        ("Micro Mages.nes", None),
    ],
)
def test_a_region_is_read_from_the_file_name_as_no_intro_and_goodtools_write_it(file, region):
    assert version_of(_hit(file)).region == region


@pytest.mark.parametrize(
    ("file", "kind"),
    [
        ("Super Mario Bros (E) [a1].nes", "alternate"),
        ("Super Mario Bros (JU) [h1].nes", "hack"),
        ("Super Mario Bros 1.5 (SMB1 Hack).nes", "hack"),
        ("Super Mario Bros (JU) [p1].nes", "pirate"),
        ("Super Mario Bros (JU) [t1].nes", "trained"),
        ("Super Mario Bros (JU) [T+Eng].nes", "translated"),
        ("Super Mario Bros (JU) (PRG 0) [T-Swed].nes", "translated"),
        ("Super Mario Bros (E) [!].nes", None),
        ("Tetris (USA) (Rev 1).nes", None),
        ("Super Mario Bros (E).nes", None),
        ("Super Mario Bros (PC10).nes", "arcade"),
    ],
)
def test_the_kind_of_version_is_read_from_the_file_name(file, kind):
    assert version_of(_hit(file)).kind == kind


def test_hacks_pirates_trained_translated_and_arcade_files_are_hidden_unless_all_versions_are_asked_for():
    hits = [_hit(f"Super Mario Bros (JU) [{mark}].nes") for mark in ("h1", "p1", "t1", "T+Eng")]
    hits.append(_hit("Super Mario Bros (PC10).nes"))
    clean = _hit("Super Mario Bros (E).nes")
    shown, hidden = chosen([*hits, clean], all_versions=False, order=EUROPE_FIRST)
    assert (shown, hidden) == ([clean], 5)
    shown, hidden = chosen([*hits, clean], all_versions=True, order=EUROPE_FIRST)
    assert len(shown) == len([*hits, clean])
    assert hidden == 0


@pytest.mark.parametrize(
    ("others", "kept"),
    [
        (["Super Mario Bros (E).nes"], False),
        (["Super Mario Bros (E) [!].nes"], False),
        (["Super Mario Bros (JU).nes"], True),
        (["Super Mario Bros (E) [h1].nes"], True),
        (["Super Mario Bros 2 (E).nes"], True),
        ([], True),
    ],
)
def test_an_alternate_dump_is_hidden_only_when_a_clean_one_of_the_same_title_and_region_exists(others, kept):
    alternate = _hit("Super Mario Bros (E) [a1].nes")
    shown, _ = chosen([alternate, *(_hit(o) for o in others)], all_versions=False, order=EUROPE_FIRST)
    assert (alternate in shown) is kept


def test_a_revision_is_never_hidden_as_an_alternate():
    revised = _hit("Tetris (USA) (Rev 1).nes")
    shown, _ = chosen([_hit("Tetris (USA).nes"), revised], all_versions=False, order=EUROPE_FIRST)
    assert revised in shown


@pytest.mark.parametrize("order", [EUROPE_FIRST, FALLBACK_ORDER, ("jp", "world", "us", "eu")])
def test_hits_come_in_the_region_order_given_then_those_with_no_region(order):
    files = [
        "Tetris (Japan).nes",
        "Tetris (USA).nes",
        "Tetris.nes",
        "Tetris (World).nes",
        "Tetris (Europe).nes",
    ]
    shown, _ = chosen([_hit(f) for f in files], all_versions=False, order=order)
    assert [version_of(h).region for h in shown] == [*order, None]


def test_a_verified_dump_comes_before_an_unmarked_one():
    unmarked, verified = _hit("Tetris (Europe).nes"), _hit("Tetris (Europe) [!].nes")
    shown, _ = chosen([unmarked, verified], all_versions=False, order=EUROPE_FIRST)
    assert shown == [verified, unmarked]


@pytest.mark.parametrize("order", [EUROPE_FIRST, FALLBACK_ORDER])
def test_a_clean_cartridge_comes_before_every_other_version_whatever_its_region(order):
    files = ["Super Mario Bros (JU) [h1].nes", "Super Mario Bros (W) [a1].nes", "Super Mario Bros (PC10).nes"]
    clean = _hit("Super Mario Bros (J).nes")
    shown, _ = chosen([*(_hit(f) for f in files), clean], all_versions=True, order=order)
    assert shown[0] == clean
    assert version_of(shown[1]).kind == "alternate"
