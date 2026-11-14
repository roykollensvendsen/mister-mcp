# SPDX-License-Identifier: GPL-3.0-or-later
"""The owner's settings: where the MiSTer is, and its key, from files outside the repository."""

import pytest

from mister_mcp.settings import SettingsError, load_settings, region_note
from mister_mcp.versions import FALLBACK_ORDER


def test_the_address_and_port_come_from_the_settings_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[mister]\naddress = "192.0.2.10"\nport = 7498\n')
    settings = load_settings(path)
    assert settings.address == "192.0.2.10"
    assert settings.port == 7498
    assert settings.api_key is None


def test_a_missing_settings_file_leaves_the_mister_unset(tmp_path):
    settings = load_settings(tmp_path / "config.toml")
    assert settings.address is None


def test_the_key_is_read_from_its_own_file_and_never_shown(tmp_path):
    key = tmp_path / "zaparoo-key"
    key.write_text("not-a-real-key-123\n")
    key.chmod(0o600)
    path = tmp_path / "config.toml"
    path.write_text('[mister]\naddress = "192.0.2.10"\n')
    settings = load_settings(path)
    assert settings.api_key == "not-a-real-key-123"
    assert "not-a-real-key-123" not in repr(settings)


def test_a_key_file_others_can_read_is_refused(tmp_path):
    key = tmp_path / "zaparoo-key"
    key.write_text("not-a-real-key-123\n")
    key.chmod(0o644)
    path = tmp_path / "config.toml"
    path.write_text('[mister]\naddress = "192.0.2.10"\n')
    with pytest.raises(SettingsError, match="chmod 600"):
        load_settings(path)


def _order(tmp_path, text="", **env):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return load_settings(path, env=env).region_order


def test_the_region_order_comes_from_the_settings_file(tmp_path):
    order = _order(tmp_path, '[search]\nregion_order = ["us", "eu"]\n', LANG="ja_JP.UTF-8")
    assert order == ("us", "eu", "world", "jp")


@pytest.mark.parametrize("said", ['["europe"]', '["eu", "eu) (foo"]', '"eu"'])
def test_an_unknown_region_in_the_settings_is_refused_naming_the_setting_and_the_four(tmp_path, said):
    with pytest.raises(SettingsError) as refused:
        _order(tmp_path, f"[search]\nregion_order = {said}\n")
    assert "region_order" in str(refused.value)
    assert all(f'"{region}"' in str(refused.value) for region in ("eu", "world", "us", "jp"))


@pytest.mark.parametrize(
    ("locale", "first"),
    [
        ("nb_NO.UTF-8", "eu"),
        ("nn_NO.UTF-8", "eu"),
        ("en_GB.UTF-8", "eu"),
        ("en_IE.UTF-8", "eu"),
        ("de_DE.UTF-8", "eu"),
        ("sv_SE", "eu"),
        ("pl_PL.UTF-8", "eu"),
        ("is_IS.UTF-8", "eu"),
        ("en_US.UTF-8", "us"),
        ("ja_JP.UTF-8", "jp"),
    ],
)
def test_an_unset_region_order_comes_from_the_locale(tmp_path, locale, first):
    order = _order(tmp_path, LANG=locale)
    assert order[0] == first
    assert sorted(order) == sorted(FALLBACK_ORDER)


def test_lc_all_is_read_before_lang(tmp_path):
    assert _order(tmp_path, LC_ALL="ja_JP.UTF-8", LANG="nb_NO.UTF-8")[0] == "jp"


@pytest.mark.parametrize(
    "env", [{}, {"LANG": "C"}, {"LANG": "POSIX"}, {"LANG": "C.UTF-8"}, {"LANG": "en_AU.UTF-8"}]
)
def test_no_locale_falls_back_to_world_usa_europe_japan(tmp_path, env):
    assert _order(tmp_path, **env) == FALLBACK_ORDER == ("world", "us", "eu", "jp")


def test_the_fallback_region_order_is_said_at_start_up(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("")
    assert (
        region_note(load_settings(path, env={}))
        == "region_order unset and no locale given: using world, us, eu, jp"
    )
    assert region_note(load_settings(path, env={"LANG": "nb_NO.UTF-8"})) == (
        "region_order unset: using eu, world, us, jp, from the locale nb_NO.UTF-8"
    )
    path.write_text('[search]\nregion_order = ["jp"]\n')
    assert region_note(load_settings(path, env={})) == "region_order: jp, world, us, eu"
