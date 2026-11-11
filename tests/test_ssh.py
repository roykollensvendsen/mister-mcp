# SPDX-License-Identifier: GPL-3.0-or-later
"""SSH to the MiSTer uses the key only: never a password, and no password is written anywhere.

The owner's own rule. A key the MiSTer refuses is said with the step that puts it back.
"""

import pathlib
import re

import pytest

from mister_mcp.settings import SettingsError, load_settings
from mister_mcp.simulator import ADDRESS
from mister_mcp.ssh import KEY_MISSING, key_missing, ssh_options

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_every_ssh_call_runs_in_batch_mode():
    options = ssh_options("~/.config/mister-mcp/ssh-key")
    assert options[options.index("BatchMode=yes") - 1] == "-o"
    assert "PasswordAuthentication=no" in options
    assert options[options.index("-i") + 1].endswith("/.config/mister-mcp/ssh-key")


def test_a_missing_key_is_said_in_the_owners_words():
    for stderr in (
        f"root@{ADDRESS}: Permission denied (publickey).",
        f"root@{ADDRESS}'s password: ",
    ):
        assert key_missing(stderr, ADDRESS) == (
            "The MiSTer does not accept this computer's key. "
            f"Run ssh-copy-id root@{ADDRESS} in a terminal, "
            "then change the MiSTer's password from the default."
        )


def test_never_a_password_login():
    options = ssh_options("~/.config/mister-mcp/ssh-key")
    for setting in (
        "BatchMode=yes",
        "PasswordAuthentication=no",
        "KbdInteractiveAuthentication=no",
        "PreferredAuthentications=publickey",
        "NumberOfPasswordPrompts=0",
    ):
        assert setting in options, setting
        assert options[options.index(setting) - 1] == "-o"


#: What a password written into the code or the documentation would look like.
PASSWORD = re.compile(r"sshpass|root:1\b|password\s*=\s*['\"]|-p\s*['\"]?1\b", re.IGNORECASE)


def test_no_password_is_written_in_the_code_or_its_documents():
    files = [
        *ROOT.joinpath("src").rglob("*.py"),
        *ROOT.glob("*.md"),
        *ROOT.joinpath("decisions").glob("*.md"),
    ]
    found = [
        f"{f.name}: {m.group(0)}" for f in files for m in PASSWORD.finditer(f.read_text(encoding="utf-8"))
    ]
    assert found == []


@pytest.mark.parametrize("key", ["password", "ssh_password", "root_password"])
def test_a_password_in_the_settings_is_refused(tmp_path, key):
    path = tmp_path / "config.toml"
    path.write_text(f'[mister]\naddress = "{ADDRESS}"\n{key} = "not-a-real-one"\n')
    with pytest.raises(SettingsError) as raised:
        load_settings(path)
    assert "ssh-copy-id" in str(raised.value)
    assert "not-a-real-one" not in str(raised.value)


def test_other_ssh_failures_are_not_called_a_missing_key():
    assert key_missing("ssh: connect to host 192.0.2.10 port 22: Connection timed out", ADDRESS) is None
    assert key_missing("", ADDRESS) is None


def test_the_missing_key_text_names_no_address_of_its_own():
    assert "{address}" in KEY_MISSING
