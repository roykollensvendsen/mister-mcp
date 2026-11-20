#!/usr/bin/env python3
"""Turn every rule off in turn and see which tests notice.

Green on a first run proves nothing: a test that has never been red tests
nothing. Where a rule is written before its test, the test is run red first.
Where a rule already exists, this is the substitute. Every rule lives in
scripts/mutations/, one file each. Run it from the repository root:

    uv run python scripts/mutate.py [--write evidence/tests/rule-mutations.md]

A kill is not enough on its own. A mutation breaks whatever it breaks, and it
can break a test for an incidental reason — a documented example whose output
happened to change — leaving a rule looking guarded when nothing guards it. So
this also checks that the test named after the rule is one of the ones that went
red, and fails the run when it is not. `tests/test_rules_have_evidence.py` is
what requires that test to exist in the first place.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _beside(name: str) -> ModuleType:
    """A module from this script's own folder, loaded by path: scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location(
        name, pathlib.Path(__file__).resolve().parent / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


run_folders = _beside("run_folders")

#: One file per rule: scripts/mutations/<the whole path of its source>/<its words>.toml.
ROWS = ROOT / "scripts/mutations"
#: Where the one mutated file is recorded while it is mutated. A `finally` does
#: not run when the process is killed, so without this a hard stop leaves a
#: source file switched off and the next person wondering why the suite is red.
RECOVERY = ROOT / "scripts/.mutate-recovery.json"
#: Where each suite run keeps its temporary files, one folder per run, removed when it
#: ends. Outside the checkout, where a test making a git repository of its own would
#: find this one instead; named after the checkout, so two never sweep each other's.
MUTATE_TMP = pathlib.Path(tempfile.gettempdir()) / (
    "mister-mcp-mutate-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
)


def row_path(rule: dict) -> pathlib.PurePosixPath:
    """Where a rule's row belongs under ROWS: its source's whole path, then its words.

    A rule named "a launch needs a yes" in src/mister_mcp/service.py goes in
    src/mister_mcp/service.py/a-launch-needs-a-yes.toml. The whole path, extension
    included, is the layout the other repositories use, and no two sources share a folder.
    """
    words = re.sub(r"[^a-z0-9]+", "-", str(rule["name"]).lower()).strip("-")
    if not words:
        msg = f"the rule {rule['name']!r} has no letter or digit to file its row under; reword it"
        raise SystemExit(msg)
    return pathlib.PurePosixPath(rule["file"]) / f"{words}.toml"


def _rows_in(path: pathlib.Path) -> list[dict]:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("rule", [])


def _row_files(folder: pathlib.Path) -> list[pathlib.Path]:
    return sorted(folder.rglob("*.toml")) if folder.is_dir() else []


def all_rows(folder: pathlib.Path | None = None) -> list[dict]:
    """Every row, one file each, in path order; a rule with two rows is refused."""
    folder = ROWS if folder is None else folder
    where: dict[str, str] = {}
    rows = []
    for path in _row_files(folder):
        here = f"{folder.name}/{path.relative_to(folder).as_posix()}"
        for rule in _rows_in(path):
            if rule["name"] in where:
                msg = (
                    f"the rule {rule['name']!r} has two rows, in {where[rule['name']]} and in {here};"
                    f" delete one and keep {folder.name}/{row_path(rule)}"
                )
                raise SystemExit(msg)
            where[rule["name"]] = here
            rows.append(rule)
    return rows


def misfiled(folder: pathlib.Path | None = None) -> list[str]:
    """Row files that hold other than one row, or sit where their rule does not put them."""
    folder = ROWS if folder is None else folder
    found = []
    for path in _row_files(folder):
        here = pathlib.PurePosixPath(path.relative_to(folder).as_posix())
        rows = _rows_in(path)
        if len(rows) != 1:
            found.append(f"{here} holds {len(rows)} rows; give each rule a file of its own")
        elif here != (belongs := row_path(rows[0])):
            found.append(f"{here} should be {belongs}; move it there")
    return found


#: A rule's marker in the source, as tests/test_rules_have_evidence.py reads it.
MARKER = re.compile(r"^[ \t]*#\s*RULE:\s*(.+?)\s*$", re.MULTILINE)


def marked_rules() -> list[str]:
    """Every rule the source under src/ marks."""
    sources = sorted((ROOT / "src").rglob("*.py"))
    return [m for path in sources for m in MARKER.findall(path.read_text(encoding="utf-8"))]


def test_name_for(rule: str) -> str:
    """The test name a rule requires: its own words, as an identifier.

    Imported by ``tests/test_rules_have_evidence.py`` so the rule is written
    once. A rule named "a spoken reply is capped" wants a test called
    ``test_a_spoken_reply_is_capped``.
    """
    words = re.sub(r"[^a-z0-9]+", "_", rule.lower())
    return "test_" + re.sub(r"_+", "_", words).strip("_")


def line_of(text: str, pattern: str, occurrence: int) -> int:
    """Find the one line a rule lives on, by pattern rather than by number."""
    seen = 0
    for i, line in enumerate(text.splitlines()):
        if re.search(pattern, line):
            seen += 1
            if seen == occurrence:
                return i
    msg = f"no line {occurrence} matching {pattern!r}"
    raise SystemExit(msg)


_remove = run_folders.remove


def sweep() -> None:
    """Remove what an earlier run, killed before it could clean up, left behind."""
    # RULE: a killed run's temporary files are swept at the next start
    for left in run_folders.dead_runs(MUTATE_TMP):
        _remove(left)
    run_folders.forget(MUTATE_TMP)


def _clean_start() -> None:
    """Undo what a killed run left: a source file still switched off, and its temporary files."""
    repair()
    sweep()


#: How a run is stopped from outside: Ctrl-C, a cancelled CI job, a closed terminal.
STOPS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
PACKAGE = "mister_mcp"


def stop_cleanly() -> None:
    """Make every stop end the run as Ctrl-C does, so every finally still runs and puts a file back."""
    # RULE: a stopped run cleans up as an interrupted one does
    for each in STOPS:
        signal.signal(each, _stopped)


def _stopped(number: int, _frame: object) -> None:
    # GitHub cancels with SIGINT, then SIGTERM: the second must not cut the first one's cleanup short.
    for later in STOPS:
        # RULE: a second stop does not cut the cleanup short
        signal.signal(later, signal.SIG_IGN)
    if number == signal.SIGINT:
        raise KeyboardInterrupt
    raise SystemExit(128 + number)


def one_run_here() -> int | None:
    """A lock on this checkout for the whole run, or None when another run already holds it."""
    checkout = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # RULE: one mutation run per checkout
        fcntl.flock(checkout, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(checkout)
        return None
    return checkout


def from_this_checkout() -> None:
    """Stop unless the suite will import the package from this checkout's own src/.

    Two worktrees sharing one environment measure each other's code. Asked of the same
    interpreter the suite runs with, in a process of its own: this script never imports it.
    """
    found = subprocess.run(  # noqa: S603 - this interpreter, a fixed line of code
        [sys.executable, "-c", f"import {PACKAGE}; print({PACKAGE}.__file__)"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    source = (ROOT / "src").resolve()
    here = pathlib.Path(found.stdout.strip() or "nowhere").resolve()
    # RULE: a run refuses a package imported from another checkout
    if not here.is_relative_to(source):
        msg = (
            f"{sys.executable} imports {PACKAGE} from {here}, not from {source}: this run would "
            f"measure another checkout's code. Run `uv sync` in {ROOT}, then run this again."
            + (f"\n{found.stderr[-500:]}" if found.returncode else "")
        )
        raise SystemExit(msg)


def repair() -> None:
    """Put back a file an earlier run was killed in the middle of mutating."""
    if not RECOVERY.is_file():
        return
    kept = json.loads(RECOVERY.read_text())
    path = ROOT / kept["file"]
    if path.read_text() == kept["mutated"]:
        path.write_text(kept["original"])
        print(f"repaired {kept['file']}, left mutated by a run that was killed")  # noqa: T201
    else:
        print(f"{kept['file']} was left mutated and has since changed; not touching it")  # noqa: T201
    RECOVERY.unlink()


def restore(path: pathlib.Path, original: str, mutated: str) -> bool:
    """Put a file back, unless somebody else changed it while the suite ran."""
    if path.read_text() != mutated:
        # Restoring now would overwrite an edit made while this was running,
        # which is a silent way to lose somebody's work.
        # RULE: a file changed during the run is never restored over
        return False
    path.write_text(original)
    return True


#: Colour codes pytest writes around FAILED, which a line-anchored pattern
#: would otherwise never match.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_suite(timeout: float | None = None) -> tuple[int, list[str]]:
    """Run the tests and give back how many failed, and which ones.

    `timeout` is for a test's scratch suite only. A real run passes none: the owner's rule is that
    a mutation run is never capped.
    """
    # Two mutations that replace equal-length text leave files of identical
    # size, and CPython validates a cached .pyc from the source's modification
    # time and size -- both at one-second resolution. Inside the same second
    # the next run would import the previous mutation's bytecode and measure
    # the wrong rule, so no bytecode is written at all.
    # RULE: two mutations never share a bytecode cache
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    temporary, lock = run_folders.start_run(MUTATE_TMP)
    try:
        r = subprocess.run(  # noqa: S603 - this interpreter running pytest, nothing from outside
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=no",
                "--color=no",
                "-p",
                "no:cacheprovider",
                # Beside the run's lock, never around it: pytest empties its basetemp first.
                # RULE: pytest s folder sits beside the run s lock never around it
                f"--basetemp={temporary / 'pytest'}",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
            env=env,
            # RULE: a real mutation run is never capped
            timeout=timeout,
        )
    finally:
        # RULE: a suite run leaves no temporary files behind
        # RULE: a mutation run leaves nothing in the temporary folder
        run_folders.end_run(temporary, lock, MUTATE_TMP)
    # --color=no covers the usual run; stripping covers a configuration that
    # turns colour back on, which would otherwise make every kill unattributable.
    # RULE: a coloured failure line is still attributed
    plain = ANSI.sub("", r.stdout)
    m = re.search(r"(\d+) (?:failed|error)", plain)
    failed = re.findall(r"^FAILED (\S+)", plain, re.MULTILINE)
    return int(m.group(1)) if m else 0, [f.split("::")[-1].split("[")[0] for f in failed]


def switched_off(text: str, rule: dict) -> str:
    """`text` with the rule's line replaced by the row's `replace`."""
    lines = text.splitlines()
    i = line_of(text, rule["find"], rule.get("occurrence", 1))
    # Keep the line's own indentation: a replacement that carries its own
    # would have to be kept in step with the source, and silently would not be.
    indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    lines[i] = indent + rule["replace"].strip()
    return "\n".join(lines) + "\n"


def _no_rows() -> int:
    """With no rows, pass only a repository that marks no rules yet."""
    marked = marked_rules()
    # RULE: rules marked with no rows fail the run and say how to get them back
    if marked:
        print(  # noqa: T201
            f"{len(marked)} rule{'s' if len(marked) != 1 else ''} marked in src/ but no rows in"
            f" {ROWS.relative_to(ROOT)}/; nothing was switched off. Put the rows back with"
            " `git checkout origin/main -- scripts/mutations`, then run this again."
        )
        return 1
    print(f"no rules in {ROWS.relative_to(ROOT)}/ yet; add one per rule the code enforces")  # noqa: T201
    return 0


def main() -> int:
    """Mutate every rule in turn, restore the tree, and report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=pathlib.Path, help="write the evidence table here")
    parser.add_argument(
        "--repair-only", action="store_true", help="put back what a killed run left mutated, and stop"
    )
    args = parser.parse_args()
    checkout = one_run_here()
    if checkout is None:
        print(f"A mutation run is already running in {ROOT}; wait for it to end, then run this again.")  # noqa: T201
        return 1
    try:
        return _run(args)
    finally:
        os.close(checkout)


def _run(args: argparse.Namespace) -> int:
    """The run itself, once this checkout is ours alone."""
    stop_cleanly()
    # RULE: repair only puts back what a killed run left and does nothing else
    if args.repair_only:
        repair()
        return 0
    _clean_start()
    # RULE: a new repository with no rules and no rows is not a failure
    # A scaffolded repository starts with a table of comments and no rows.
    rules = all_rows()
    if not rules:
        return _no_rows()
    from_this_checkout()
    results = []
    lost: list[str] = []
    bad_rows: list[str] = []
    standing: tuple[pathlib.Path, str, str] | None = None
    try:
        for rule in rules:
            path = ROOT / rule["file"]
            # Read each file as it is now, not as it was when the run began: a
            # bulk snapshot taken up front is restored over anything edited
            # since, and losing an edit that way costs more than the run.
            text = path.read_text()
            mutated = switched_off(text, rule)
            why = broken(rule["file"], mutated)
            # RULE: a row that breaks the code is reported as broken
            if why:
                bad_rows.append(rule["name"])
                print(  # noqa: T201
                    f"BROKEN   {rule['name']}: the replacement is not valid code ({why});"
                    f" make {_where(rule)} replace the line with a whole valid line",
                    flush=True,
                )
                continue
            RECOVERY.write_text(json.dumps({"file": rule["file"], "original": text, "mutated": mutated}))
            path.write_text(mutated)
            standing = (path, text, mutated)
            why = fails_to_load(rule["file"])
            # RULE: a row that breaks the module on loading is reported as broken
            if why:
                standing = _put_back(path, text, mutated, lost)
                bad_rows.append(rule["name"])
                print(  # noqa: T201
                    f"BROKEN   {rule['name']}: the replacement stops the module loading ({why});"
                    f" make {_where(rule)} replace the line with code that runs",
                    flush=True,
                )
                continue
            # Sent at once, not held until the run ends: in CI the output is a pipe, so a
            # run that hangs would otherwise leave no word of which rule it hung on.
            # RULE: a mutation run names each rule before it tests it
            print(f"testing  {rule['name']}", flush=True)  # noqa: T201
            began = time.monotonic()
            count, failed = run_suite()
            took = time.monotonic() - began
            standing = _put_back(path, text, mutated, lost)
            # A kill by some other test is not evidence about this rule.
            own = test_name_for(rule["name"])
            by_its_own = own in failed
            results.append((rule["name"], count, own, by_its_own))
            verdict = "KILLED  " if by_its_own else ("BY LUCK " if count else "SURVIVED")
            print(f"{verdict} {rule['name']}: {count} in {took:.0f} s", flush=True)  # noqa: T201
    finally:
        if standing is not None:
            restore(*standing)
        RECOVERY.unlink(missing_ok=True)

    return _summary(results, bad_rows, lost, args.write)


def _put_back(path: pathlib.Path, original: str, mutated: str, lost: list[str]) -> None:
    """Restore a mutated file and drop its recovery note; a file changed meanwhile goes in `lost`.

    Gives back None, for the caller's `standing`: nothing stands mutated any more.
    """
    if not restore(path, original, mutated):
        lost.append(str(path.relative_to(ROOT)))
    RECOVERY.unlink(missing_ok=True)


def _summary(
    results: list[tuple[str, int, str, bool]],
    bad_rows: list[str],
    lost: list[str],
    write: pathlib.Path | None,
) -> int:
    """Say what the run found, in the log, the evidence page and the CI summary; give the exit status."""
    survived = [name for name, count, _, _ in results if count == 0]
    lucky = [name for name, count, _, own in results if count and not own]
    proven = len(results) - len(survived) - len(lucky)
    # A broken row tested nothing, so it counts against the tally the ratchet reads.
    print(f"\n{proven}/{len(results) + len(bad_rows)} rules turned off the test that names them")  # noqa: T201
    if survived:
        print("SURVIVED, so nothing protects them:", ", ".join(survived))  # noqa: T201
    if lucky:
        print("KILLED BY ANOTHER TEST, so the evidence is not about them:", ", ".join(lucky))  # noqa: T201
    if bad_rows:
        print("BROKEN ROW, so nothing was tested; make each a whole valid line:", ", ".join(bad_rows))  # noqa: T201
    if lost:
        print("CHANGED WHILE MUTATED, so left as they are:", ", ".join(sorted(set(lost))))  # noqa: T201
        print("Edit the tree while this runs and the result is not about your code.")  # noqa: T201
    said = verdict(results, survived, lucky, bad_rows)
    if write:
        write.write_text(report(results, said))
    # RULE: a broken row is listed in the report and the step summary
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with pathlib.Path(step_summary).open("a") as out:
            out.write(f"## Every rule, turned off in turn\n\n{said}\n")
    return 1 if survived or lucky or lost or bad_rows else 0


def _where(rule: dict) -> pathlib.Path:
    """The rule's row file, from the repository's top where it is under it."""
    path = ROWS / row_path(rule)
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def broken(file: str, mutated: str) -> str | None:
    """Why a mutated Python file no longer compiles, or None when it does.

    A replacement cut off mid-expression stops the module importing, so every
    test in its files errors: the run would count the rule as caught when the
    row itself is wrong.
    """
    if not file.endswith(".py"):
        return None
    try:
        compile(mutated, file, "exec")
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"
    return None


#: Loads one file as the suite would, without running a `__main__` block: a module under
#: src/ by its dotted name, any other file (a script, say) from its path under another name.
LOAD = """
import importlib, importlib.util, sys
file = sys.argv[1]
if file.startswith("src/"):
    importlib.import_module(file[4:-3].replace("/", ".").removesuffix(".__init__"))
else:
    spec = importlib.util.spec_from_file_location("mutant_loaded", file)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
"""


def fails_to_load(file: str) -> str | None:
    """Why the mutated file, now on disk, stops its module loading, or None when it loads.

    A replacement can compile and still fail as the module loads, for example with a name
    that is not defined. Every test that imports it then errors, which the run would count
    as the rule's own test catching it. Asked of a fresh interpreter, with no bytecode, as
    the suite will be.
    """
    if not file.endswith(".py"):
        return None
    loaded = subprocess.run(  # noqa: S603 - this interpreter, a fixed loader, a file from a row
        [sys.executable, "-c", LOAD, file],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if loaded.returncode == 0:
        return None
    last = loaded.stderr.strip().splitlines()
    return last[-1] if last else f"exit {loaded.returncode}"


def verdict(
    results: list[tuple[str, int, str, bool]], survived: list[str], lucky: list[str], bad_rows: list[str]
) -> str:
    """The run's result in one paragraph, for the evidence page and the CI summary."""
    proven = len(results) - len(survived) - len(lucky)
    return (
        f"**Result: {proven} of {len(results) + len(bad_rows)} rules turned off the test that names them.**"
        + (" None survived." if not survived else f" Survived: {', '.join(survived)}.")
        + ("" if not lucky else f" Killed only by other tests: {', '.join(lucky)}.")
        + ("" if not bad_rows else f" Broken rows, so nothing was tested: {', '.join(bad_rows)}.")
    )


def report(results: list[tuple[str, int, str, bool]], said: str) -> str:
    """Render the run as the evidence page."""
    rows = "\n".join(
        f"| {name} | {count} | `{own}` | {'yes' if by_own else 'NO'} |"
        for name, count, own, by_own in results
    )
    return f"""# Every rule, turned off in turn

*Run {dt.datetime.now(dt.UTC).date()} by `python scripts/mutate.py --write
evidence/tests/rule-mutations.md`, which is how to repeat it. The script
restores every file it touched before it exits.*

Green on a first run proves nothing: a test that has never been red tests
nothing. Where a rule is written before its test, the test is run red first.
Where a rule already exists, this is the substitute. Each rule is disabled in
turn, by replacing its one line with something that can never hold, and the
suite is run. A rule whose removal breaks no test is a rule nothing protects.

{said}

| Rule turned off | Tests that went red | The test that names it | Did that one go red? |
|---|---|---|---|
{rows}

## What this does not prove

That the rules are the right rules, or that a rule catches every case of what
it names. It proves each rule is load-bearing: switch it off and a named test
says so. The last column is why that is worth more than a count: a mutation can
break a test for an incidental reason, and a `NO` there fails this script even
though something went red. A new rule follows the order in `CONTRIBUTING.md`
instead, a failing test first, and gets a row in `scripts/mutations/`, which
`tests/test_rules_have_evidence.py` requires.
"""


if __name__ == "__main__":
    sys.exit(main())
