# mister-mcp

Start retro games on a MiSTer FPGA by voice: an MCP server and claude-voice plugin.

It is a small MCP server over stdio, and an optional plugin for
claude-voice. It talks to [Zaparoo Core](https://github.com/ZaparooProject/zaparoo-core),
which runs on the MiSTer, and sends it only the calls listed in
[ADR-MM-001](decisions/ADR-MM-001-build-on-zaparoo-core.md). No tool writes,
deletes or changes anything on the MiSTer.

## Try it without a MiSTer

`--simulate` answers from a pretend MiSTer, and says so:

```console
$ uv run mister-mcp status --simulate
Simulated: The MiSTer is on, at its menu.
```

Pairing with a secured Zaparoo, against a pretend one that saves nothing:

```console
$ uv run mister-mcp pair --simulate
Simulated: Paired with the MiSTer. Nothing was saved.
```

The server itself, as a voice session starts it; it ends when its input does:

```console
$ uv run mister-mcp serve --simulate < /dev/null
```

## The tools

| Tool | Does | Changes anything |
|---|---|---|
| `mister_status` | Whether the MiSTer is on, and the system and game it runs | No |
| `mister_search` | Up to five games whose names hold every word said, with their systems | No |
| `mister_launch` | Starts a game by name, or a system's core alone, reads back what runs, then shows it on the TV if that TV is already on. While a game runs, it asks first | Starts a game |
| `mister_launch_confirm` | The owner's yes to that question, with its one-time token: ends the running game and starts the one asked for | Starts a game |
| `mister_update_request` | Checks that update_all may run (512 MB free, none running, the MiSTer up two minutes) and asks, naming a running game | No |
| `mister_update_confirm` | The owner's yes, with its one-time token: starts update_all, which may restart the MiSTer | Updates the MiSTer |
| `mister_update_status` | Whether update_all runs, its current step and about how long is left, or how it ended | No |

Every answer has `say`, read aloud as it is, and `success` with `outcome`
for a program: `done`, `unreachable` (the MiSTer did not answer: off, or not
on the network), `not_found`, `refused`, or `working` (still going after the
voice's time, and carrying on), or `ask` (a question to read aloud, with a
`token` for the yes).

Which actions are risky is the owner's call (the plugin standard's rule 7).
Starting a game from the menu is not. Ending a running game is: a launch
while a game or core runs is a question that names what runs, and only
`mister_launch_confirm` with its token, within a minute, starts the new one.
Switching the MiSTer's power through a smart plug will be risky too; it is not
built yet.

update_all runs over SSH by key only, and only commands from a fixed list
are ever sent ([ADR-MM-004](decisions/ADR-MM-004-run-update-all-over-ssh-from-a-fixed-list.md)).
The key the MiSTer accepts sits alone in `~/.config/mister-mcp/ssh-key`.

## Settings

In `~/.config/mister-mcp/config.toml`, never in this repository:

<!-- not run: a settings file, not a command -->
```toml
[mister]
address = "mister.example"       # the MiSTer's name on the home network
addresses = ["192.0.2.10"]       # optional spares, tried in order when the name does not answer
```

The name is tried first, then each spare. Together they take at most six
seconds, so the voice still gets its answer in time. After that, the address
that answered is asked first. `mister_status` says which address it used.
When none of them answers, the voice names each one and says what to check.

To have the TV the MiSTer is plugged into show it after a start, add the
TV plugin ([tv-mcp](https://github.com/roykollensvendsen/tv-mcp)) and the
names it knows:

<!-- not run: a settings file, not a command -->
```toml
[tv]
command = ["uv", "run", "--directory", "~/tv-mcp", "tv-mcp", "serve"]
name = "the den"      # the TV, as tv-mcp knows it
device = "MiSTer"     # the device on its input, as tv-mcp's settings name it
```

The plugin starts that server for a moment, asks `tv_status` whether the
screen is on, and only then asks `tv_input` to show the device. It calls no
other TV tool, and closes the TV plugin again after each start
([ADR-MM-002](decisions/ADR-MM-002-switch-the-tv-through-tv-mcps-own-tools.md)).

A Zaparoo API key, if Zaparoo is set to ask for one, goes alone in
`~/.config/mister-mcp/zaparoo-key`, readable by the owner only
(`chmod 600`); the plugin refuses a key file others can read.

## The gates

Every one of these runs in continuous integration, and all of them run here:

```console
$ uv run ruff check .
All checks passed!
```

<!-- not run: the workflow runs each of these; nesting them here would run the suite inside itself -->
```bash
uv run ruff format --check .   # layout
uv run mypy src                # types
uv run pytest -q               # behaviour
python scripts/mutate.py       # that each rule's own test can fail
```

`CONTRIBUTING.md` says what each one is for, and
[`decisions/`](decisions/README.md) records the choices that shaped them,
including how a change is made here.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
