"""Which CI runs a newer one may stop: only a pull request's stale run, never main's."""

import pathlib

WORKFLOW = pathlib.Path(__file__).parent.parent / ".github/workflows/checks.yml"
PULL_REQUEST = "github.event_name == 'pull_request'"


def test_only_a_pull_request_s_stale_run_is_stopped_and_every_main_run_finishes():
    """A pull request shares one group per branch, so a newer push stops its stale run.

    Every other run (main, a tag, by hand) is a group of its own, keyed by its run id. GitHub
    keeps only one waiting run per group, so a shared group on main skipped the commits between.
    """
    lines = [line.strip() for line in WORKFLOW.read_text().splitlines()]
    at = lines.index("concurrency:")
    assert lines[at + 1 : at + 3] == [
        "group: ${{ github.workflow }}-${{ " + PULL_REQUEST + " && github.ref || github.run_id }}",
        "cancel-in-progress: ${{ " + PULL_REQUEST + " }}",
    ]
