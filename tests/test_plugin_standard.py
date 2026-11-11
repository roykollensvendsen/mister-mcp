# SPDX-License-Identifier: GPL-3.0-or-later
"""Each rule of the voice plugins' shared standard has a test here named after it.

The standard is claude-voice's docs/plugin-standard.md. Rules 1 to 11 each map
to the tests that guard them in mister-mcp; renaming or deleting one of those
tests turns this red, so a rule cannot lose its guard quietly. Rule 12 is this
file, and its second half, asking the voice what it sees after a change to a
name or a first line, is a step for whoever changes one.
"""

import ast
import pathlib

TESTS = pathlib.Path(__file__).parent

#: Each rule of the standard, and the tests in mister-mcp that guard it.
STANDARD = {
    1: ["test_tool_names.py::test_no_two_tool_names_can_be_confused"],
    2: ["test_server.py::test_every_tool_opens_with_a_whole_sentence_the_voice_sees_in_full"],
    3: [
        "test_server.py::test_a_tools_longest_wait_fits_in_the_voices_time",
        "test_server.py::test_a_launchs_longest_path_finishes_within_half_a_minute",
        "test_server.py::test_a_tool_still_working_at_the_deadline_says_it_carries_on",
        "test_cold_start.py::test_a_cold_start_never_waits_on_the_mister",
    ],
    4: [
        "test_server.py::test_every_tool_answers_with_a_sentence_even_when_it_fails",
        "test_search.py::test_a_name_with_no_game_says_what_to_try_next",
    ],
    5: ["test_launch.py::test_a_start_is_said_as_done_only_once_the_mister_shows_it"],
    6: ["test_status.py::test_a_mister_that_does_not_answer_is_not_called_on_or_off"],
    7: [
        "test_tool_names.py::test_no_tool_switches_power",
        "test_ask_first.py::test_a_running_game_is_never_ended_without_a_yes",
        "test_ask_first.py::test_a_token_works_once_and_only_while_fresh",
    ],
    8: ["test_launch.py::test_a_hands_off_tv_is_never_sent_an_input"],
    9: ["test_server.py::test_the_tools_that_only_look_are_marked_read_only_and_no_others"],
    10: [
        "test_private_data_scan.py::test_a_value_from_the_settings_file_is_never_committed",
        "test_settings.py::test_the_key_is_read_from_its_own_file_and_never_shown",
    ],
    11: ["test_server.py::test_every_simulated_answer_says_simulated_first"],
}


def _defined(file):
    tree = ast.parse((TESTS / file).read_text())
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_each_rule_has_a_test_named_after_it():
    assert set(STANDARD) == set(range(1, 12))
    missing = [
        f"rule {rule}: {test}"
        for rule, tests in STANDARD.items()
        for test in tests
        if test.split("::")[1] not in _defined(test.split("::")[0])
    ]
    assert not missing, missing
