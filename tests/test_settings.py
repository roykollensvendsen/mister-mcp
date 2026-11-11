# SPDX-License-Identifier: GPL-3.0-or-later
"""The owner's settings: where the MiSTer is, and its key, from files outside the repository."""

import pytest

from mister_mcp.settings import SettingsError, load_settings


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
