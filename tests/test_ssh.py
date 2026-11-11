# SPDX-License-Identifier: GPL-3.0-or-later
"""SSH to the MiSTer never waits for a password, and a missing key is said in the owner's words."""

from mister_mcp.simulator import ADDRESS
from mister_mcp.ssh import KEY_MISSING, key_missing, ssh_options


def test_every_ssh_call_runs_in_batch_mode():
    options = ssh_options("~/.config/mister-mcp/ssh-key")
    assert options[options.index("BatchMode=yes") - 1] == "-o"
    assert "PasswordAuthentication=no" in options
    assert options[options.index("-i") + 1].endswith("/.config/mister-mcp/ssh-key")


def test_a_missing_key_is_said_in_the_owners_words():
    for stderr in (
        f"root@{ADDRESS}: Permission denied (publickey,password).",
        f"root@{ADDRESS}'s password: ",
    ):
        assert key_missing(stderr, ADDRESS) == (
            f"SSH-nøkkelen mangler på MiSTer-en, kjør ssh-copy-id root@{ADDRESS} på nytt."
        )


def test_other_ssh_failures_are_not_called_a_missing_key():
    assert key_missing("ssh: connect to host 192.0.2.10 port 22: Connection timed out", ADDRESS) is None
    assert key_missing("", ADDRESS) is None


def test_the_missing_key_text_names_no_address_of_its_own():
    assert "{address}" in KEY_MISSING
