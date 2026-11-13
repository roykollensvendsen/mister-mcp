# SPDX-License-Identifier: GPL-3.0-or-later
"""update_all by voice (ADR-MM-004): asked, then confirmed, then followed, over SSH from a fixed list.

Every test runs against a pretend MiSTer shell; nothing here reaches a MiSTer.
"""

import asyncio
import sys

import pytest

import mister_mcp.ssh
from mister_mcp.simulator import ADDRESS, SimulatedMister, SimulatedShell
from mister_mcp.ssh import (
    ALLOWED_COMMANDS,
    SSH_FAILED,
    NotAllowedCommandError,
    Reply,
    SshShell,
    explain,
    ssh_options,
)
from mister_mcp.updater import ASK_WITHIN, MIN_FREE_MB, SD_FULL, STARTED, UpdateService


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _service(shell=None, mister=None, tmp_path=None, clock=None):
    return UpdateService(
        shell or SimulatedShell(),
        mister or SimulatedMister(),
        history=(tmp_path / "update-runs.json") if tmp_path else None,
        clock=clock or _Clock(),
    )


def _run(coro):
    return asyncio.run(coro)


# -- the fixed list -------------------------------------------------------------------------


def test_only_a_command_from_the_fixed_list_is_ever_sent_over_ssh():
    shell = SshShell([ADDRESS], key_file="~/.config/mister-mcp/ssh-key")
    with pytest.raises(NotAllowedCommandError):
        _run(shell.run("rm -rf /media/fat"))
    with pytest.raises(NotAllowedCommandError):
        _run(shell.run("df -Pk /media/fat; reboot"))


def test_the_fixed_list_is_exactly_the_one_the_decision_record_names():
    assert ALLOWED_COMMANDS == {
        "free_space": "df -Pk /media/fat",
        "running": "pgrep -f '[u]pdate_all'",
        "uptime": "cat /proc/uptime",
        "live_log": "tail -n 40 /tmp/update_all_print.log",
        "saved_log": "tail -n 40 /media/fat/Scripts/.config/update_all/update_all.log",
        "start": (
            "UPDATE_ALL_NON_INTERACTIVE=true setsid nohup /media/fat/Scripts/update_all.sh"
            " >/dev/null 2>&1 </dev/null &"
        ),
    }


def test_an_ssh_call_is_the_fixed_command_with_the_key_only_options():
    shell = SshShell([ADDRESS], key_file="~/.config/mister-mcp/ssh-key")
    argv = shell.argv(ADDRESS, "free_space")
    assert argv[0] == "ssh"
    assert argv[-2:] == [f"root@{ADDRESS}", "df -Pk /media/fat"]
    assert argv[1:-2] == ssh_options("~/.config/mister-mcp/ssh-key")


# -- asking ---------------------------------------------------------------------------------


def test_from_the_menu_the_request_asks_and_starts_nothing():
    shell = SimulatedShell()
    answer = _run(_service(shell).request())
    assert answer["outcome"] == "ask"
    assert answer["token"]
    assert "may restart the MiSTer" in answer["say"]
    assert answer["say"].endswith("Do you want me to start update_all?")
    assert "start" not in shell.sent


def test_a_running_game_is_named_in_the_question():
    mister = SimulatedMister()
    mister.play("NES", "Micro Mages")
    answer = _run(_service(mister=mister).request())
    assert answer["outcome"] == "ask"
    assert answer["say"].startswith("The MiSTer is playing Micro Mages on the Nintendo Entertainment System.")


def test_too_little_free_space_is_refused_naming_how_much_is_free():
    shell = SimulatedShell(free_mb=300)
    answer = _run(_service(shell).request())
    assert answer["outcome"] == "refused"
    assert "300 MB" in answer["say"]
    assert f"{MIN_FREE_MB} MB" in answer["say"]
    assert "token" not in answer


def test_a_run_already_going_is_not_started_again():
    shell = SimulatedShell(running=True)
    answer = _run(_service(shell).request())
    assert answer["outcome"] == "refused"
    assert "already running" in answer["say"]


def test_a_mister_that_just_started_is_given_time_first():
    answer = _run(_service(SimulatedShell(uptime=40)).request())
    assert answer["outcome"] == "refused"
    assert "Wait" in answer["say"]


def test_a_key_the_mister_refuses_is_said_with_the_step_that_fixes_it():
    answer = _run(_service(SimulatedShell(key_refused=True)).request())
    assert answer["outcome"] == "refused"
    assert f"ssh-copy-id root@{ADDRESS}" in answer["say"]


def test_a_mister_that_does_not_answer_over_ssh_says_what_to_check():
    answer = _run(_service(SimulatedShell(on=False)).request())
    assert answer["outcome"] == "unreachable"
    assert "Check" in answer["say"]


# -- confirming -----------------------------------------------------------------------------


def test_the_yes_starts_update_all_once():
    shell = SimulatedShell()
    service = _service(shell)

    async def scenario():
        asked = await service.request()
        first = await service.confirm(asked["token"])
        second = await service.confirm(asked["token"])
        return first, second

    first, second = _run(scenario())
    assert first["outcome"] == "done"
    assert "Ask how the update is going" in first["say"]
    assert shell.sent.count("start") == 1
    assert second["outcome"] == "refused"


def test_an_update_token_works_once_and_only_while_fresh():
    clock = _Clock()
    shell = SimulatedShell()
    service = _service(shell, clock=clock)

    async def scenario():
        asked = await service.request()
        clock.now += ASK_WITHIN + 1
        return await service.confirm(asked["token"])

    late = _run(scenario())
    assert late["outcome"] == "refused"
    assert "start" not in shell.sent


def test_a_made_up_update_token_starts_nothing():
    shell = SimulatedShell()
    assert _run(_service(shell).confirm("guessed"))["outcome"] == "refused"
    assert "start" not in shell.sent


def test_the_confirm_checks_the_space_again():
    shell = SimulatedShell()
    service = _service(shell)

    async def scenario():
        asked = await service.request()
        shell.free_mb = 100
        return await service.confirm(asked["token"])

    answer = _run(scenario())
    assert answer["outcome"] == "refused"
    assert "start" not in shell.sent


# -- following a run ------------------------------------------------------------------------


def test_a_running_update_says_its_current_step_and_how_long_it_has_run(tmp_path):
    clock = _Clock()
    shell = SimulatedShell()
    service = _service(shell, tmp_path=tmp_path, clock=clock)

    async def scenario():
        asked = await service.request()
        await service.confirm(asked["token"])
        shell.live_log = ["Update All 2.3", "", "Running Downloader", "\x1b[1marcade\x1b[0m: 1941.mra"]
        clock.now += 125
        return await service.status()

    answer = _run(scenario())
    assert answer["outcome"] == "working"
    assert "running, for 2 minutes" in answer["say"]
    assert "arcade: 1941.mra" in answer["say"]
    assert "\x1b" not in answer["say"]


def test_a_finished_update_says_done(tmp_path):
    shell = SimulatedShell(live_log=["Running Downloader", "Success! More details at: update_all.log"])
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert answer["outcome"] == "done"
    assert "update_all is done" in answer["say"]


def test_a_finished_update_that_restarts_the_mister_says_so(tmp_path):
    shell = SimulatedShell(live_log=["Success! Log saved.", "", "Rebooting in 5 seconds..."])
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert answer["outcome"] == "done"
    assert "restarting the MiSTer" in answer["say"]


def test_a_full_sd_card_is_said_in_plain_words(tmp_path):
    shell = SimulatedShell(
        live_log=["/media/fat is FULL. Minimum required space for /media/fat is 512MB.", "Update All failed!"]
    )
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert answer["outcome"] == "failed"
    assert answer["say"] == SD_FULL
    assert SD_FULL == "The SD card is full; ask the manager what can be deleted."


def test_a_failed_update_says_where_its_log_is(tmp_path):
    shell = SimulatedShell(live_log=["Check these logs from the Updaters that failed:", "downloader.log"])
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert answer["outcome"] == "failed"
    assert "Scripts/.config/update_all/update_all.log" in answer["say"]


def test_after_a_restart_the_saved_log_tells_how_it_ended(tmp_path):
    shell = SimulatedShell(live_log=None, saved_log=["Success! Log saved.", "Rebooting now..."])
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert answer["outcome"] == "done"
    assert "last update_all run" in answer["say"]


def test_with_no_run_known_the_status_says_how_to_start_one(tmp_path):
    shell = SimulatedShell(live_log=None, saved_log=None)
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert answer["outcome"] == "not_found"
    assert "Ask me to start" in answer["say"]


def test_past_runs_give_an_estimate_of_the_time_left(tmp_path):
    (tmp_path / "update-runs.json").write_text("[600, 720, 660]")
    clock = _Clock()
    shell = SimulatedShell()
    service = _service(shell, tmp_path=tmp_path, clock=clock)

    async def scenario():
        asked = await service.request()
        await service.confirm(asked["token"])
        shell.live_log = ["Running Downloader"]
        clock.now += 240
        return await service.status()

    answer = _run(scenario())
    assert "About 7 minutes left" in answer["say"]


def test_a_run_that_ends_is_kept_for_the_next_estimate(tmp_path):
    clock = _Clock()
    shell = SimulatedShell()
    service = _service(shell, tmp_path=tmp_path, clock=clock)

    async def scenario():
        asked = await service.request()
        await service.confirm(asked["token"])
        shell.running, shell.live_log = False, ["Success! Log saved."]
        clock.now += 500
        await service.status()
        await service.status()

    _run(scenario())
    assert (tmp_path / "update-runs.json").read_text().strip() == "[500]"


def test_a_real_failed_run_that_rebooted_is_said_as_failed(tmp_path):
    # The end of a real update_all.log (2026-11-11): the Downloader failed, and it rebooted anyway.
    saved = [
        "Linux has been updated! It is recommended to reboot your system now.",
        "Downloader launcher finished with exit code 21",
        "There were some errors in the Updaters.",
        "Therefore, MiSTer hasn't been fully updated.",
        "Check these logs from the Updaters that failed:",
        " - Scripts/.config/downloader/downloader.log",
        "Rebooting now...",
    ]
    shell = SimulatedShell(live_log=None, saved_log=saved)
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert answer["outcome"] == "failed"
    assert "update_all.log" in answer["say"]


# -- the ssh runner, with a stand-in for ssh -----------------------------------------------


def _stand_in(script):
    """An argv that runs `script` in Python instead of ssh, so no network is touched."""
    return [sys.executable, "-c", script]


def test_an_ssh_reply_carries_its_output_and_code():
    reply = _run(SshShell.call(ADDRESS, _stand_in("import sys; print('up'); sys.exit(1)")))
    assert (reply.code, reply.out.strip(), reply.reached) == (1, "up", True)


def test_an_ssh_call_that_cannot_start_is_not_reached():
    reply = _run(SshShell.call(ADDRESS, ["/nonexistent/ssh"]))
    assert not reply.reached


def test_a_slow_ssh_call_is_given_up(monkeypatch):
    monkeypatch.setattr(mister_mcp.ssh, "CALL_WITHIN", 0.2)
    reply = _run(SshShell.call(ADDRESS, _stand_in("import time; time.sleep(5)")))
    assert (reply.reached, reply.err) == (False, "timed out")


def test_the_next_address_is_tried_when_one_does_not_answer(monkeypatch):
    tried = []

    async def at(address, argv):
        tried.append(address)
        return Reply(SSH_FAILED if address == "mister.example" else 0, "", "", address)

    shell = SshShell(["mister.example", ADDRESS], key_file="~/.config/mister-mcp/ssh-key")
    monkeypatch.setattr(shell, "call", at)
    reply = _run(shell.run("uptime"))
    assert (tried, reply.address) == (["mister.example", ADDRESS], ADDRESS)


def test_a_changed_mister_identity_is_said_with_the_command_that_clears_it():
    said = explain("WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!", ADDRESS)
    assert f"ssh-keygen -R {ADDRESS}" in said


def test_a_broken_history_file_gives_no_estimate(tmp_path):
    (tmp_path / "update-runs.json").write_text("not json")
    shell = SimulatedShell(running=True, live_log=["Running Downloader"])
    answer = _run(_service(shell, tmp_path=tmp_path).status())
    assert "left" not in answer["say"]


def test_an_unreadable_free_space_answer_is_refused():
    shell = SimulatedShell(free_mb=None)
    assert _run(_service(shell).request())["outcome"] == "refused"


# -- a start that runs past the time limit -------------------------------------------------


def _mister_whose_start_hangs(monkeypatch, *, starts=True):
    """Two addresses for one MiSTer whose `start` outlasts CALL_WITHIN; what was sent, in order.

    Each call still goes through the real ssh runner and its time limit, with a stand-in for ssh.
    With `starts`, the hanging start has set update_all going, as a slow real one may have.
    """
    monkeypatch.setattr(mister_mcp.ssh, "CALL_WITHIN", 0.3)
    name_of = {command: name for name, command in ALLOWED_COMMANDS.items()}
    sent, going = [], []
    free = MIN_FREE_MB * 2 * 1024
    answers = {
        "free_space": f"print('Filesystem 1024-blocks Used Available Capacity Mounted on');"
        f"print('/dev/mmcblk0p1 31000000 1 {free} 1% /media/fat')",
        "uptime": "print('900.0 100.0')",
    }
    real = SshShell.call

    async def call(address, argv):
        name = name_of[argv[-1]]
        sent.append((address, name))
        if name == "start":
            going.extend([True] if starts else [])
            return await real(address, _stand_in("import time; time.sleep(5)"))
        if name == "running":
            return await real(address, _stand_in(f"import sys; sys.exit({0 if going else 1})"))
        return await real(address, _stand_in(answers.get(name, "pass")))

    monkeypatch.setattr(SshShell, "call", staticmethod(call))
    return SshShell(["mister.example", ADDRESS], key_file="~/.config/mister-mcp/ssh-key"), sent


def test_a_command_cut_off_while_running_is_never_sent_again(monkeypatch):
    shell, sent = _mister_whose_start_hangs(monkeypatch)
    _run(shell.run("start"))
    assert [what for what in sent if what[1] == "start"] == [("mister.example", "start")]


def test_a_start_that_did_not_answer_is_checked_as_running_before_anything_is_said(monkeypatch):
    shell, sent = _mister_whose_start_hangs(monkeypatch)
    service = _service(shell)
    token = _run(service.request())["token"]
    answer = _run(service.confirm(token))
    assert [name for _, name in sent].count("start") == 1
    assert sent[-1][1] == "running"
    assert (answer["outcome"], answer["say"]) == ("done", STARTED)


def test_a_start_that_did_not_answer_and_is_not_running_is_never_called_started(monkeypatch):
    shell, sent = _mister_whose_start_hangs(monkeypatch, starts=False)
    service = _service(shell)
    token = _run(service.request())["token"]
    answer = _run(service.confirm(token))
    assert [name for _, name in sent].count("start") == 1
    assert answer["outcome"] == "unreachable"
    assert "not running" in answer["say"]
    assert _run(service.confirm(token))["outcome"] == "refused"
