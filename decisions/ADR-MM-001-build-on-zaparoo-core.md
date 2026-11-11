# ADR-MM-001: Build on Zaparoo Core's API, not misterclaw or a launcher of our own

## Status

Accepted, 2026-11-11, within the design the owner approved for this plugin
(reuse first; no tool writes, deletes or runs a command of its own choosing).

## Context

The plugin has to say what the MiSTer is running, find a game by name and
start a game or a core. Three projects already reach a MiSTer, read at their
sources on 2026-11-11:

- **Zaparoo Core** (github.com/ZaparooProject/zaparoo-core, GPL-3.0-or-later,
  v2.22.1 released 2026-11-10). Runs on the MiSTer. A JSON-RPC 2.0 API over a
  WebSocket on port 7497, path `/api/v0.1`, whose published contract "will
  receive backward-compatible, additive changes only" (`docs/api/index.md`).
  It has exactly the three calls needed: `media.active`, `media.search` and
  `run`. It also has many calls that change things (`settings.update`,
  `media.generate`, `mappings.*`, `input.*`, `screenshot`, ...), and on a
  MiSTer an unauthenticated client on the network may call most of them.
  `run` takes ZapScript, which can also run programs (`**execute`, gated by
  `allow_execute`), run any script in `/media/fat/Scripts` (`**mister.script`,
  not gated) and switch the MiSTer's ini file (`**mister.ini`).
- **misterclaw** (github.com/catallo/misterclaw, MIT, Go). An MCP server with
  its own daemon on the MiSTer, over a TCP protocol with "no authentication or
  encryption" (its README). Its tools include `mister_shell` and
  `mister_cfg_write`.
- **mrext Remote** (github.com/wizzomafizzo/mrext, GPL-3.0, port 8182). An
  HTTP API with status, search and launch, and on the same unauthenticated
  server file delete, rename and create, ini writes and reboot. Its author now
  leads Zaparoo.

## Options considered

- **misterclaw.** Not taken: it runs shell commands and writes files by
  design, which this plugin's safety rules forbid, and it would mean
  installing a second daemon on the MiSTer.
- **mrext Remote.** Not taken: workable for the three calls, but the same
  server deletes files and writes settings, and development has moved to
  Zaparoo.
- **Our own launcher over SSH** (writing MGL files, `/dev/MiSTer_cmd`). Not
  taken: it writes files on the MiSTer and needs a shell, the two things the
  plugin must never do, and it would duplicate what Zaparoo already does.
- **Do nothing.** Not taken: the owner asked for voice control.

## Decision

The plugin is a small Zaparoo Core client. It speaks JSON-RPC over the
WebSocket, and only the methods `version`, `media.active`, `media.search`,
`systems` and `run` ever leave it: a fixed allow-list in the client, checked
before anything is sent. `run` carries only one of two texts the plugin builds
itself: `**launch.system:<id>`, where the id is one Zaparoo listed in
`systems`, or the exact `zapScript` of a search result, which must start with
`@` and contain neither `**` nor `||`. Every `run` is sent with
`unsafe: true`, which makes Core treat it as remote and refuse `**execute`
and `**input` even if a text slipped through.

`unsafe: true` unlocks nothing. Despite its name in Zaparoo's documentation
("allow unsafe operations"), in Core's code it marks the request as coming
from a remote source, and `**execute` and `**input.*` then refuse it
(`pkg/zapscript/utils.go`, `pkg/zapscript/input.go`, read 2026-11-11). It does
not stop `**mister.script` or `**mister.ini`; only the text check above does.
The words the owner says never reach `run`: a game's name goes to
`media.search`, and only the `zapScript` of the one result picked is sent; a
system's name is matched against `systems`, and only the listed id is sent.
`tests/test_launch.py::test_the_voices_own_words_never_reach_a_start` and
`test_a_bad_launch_text_from_zaparoo_itself_is_never_sent` show both. When Core cannot be reached, the
plugin says the MiSTer is off or not on the network; it never guesses which.

## Consequences

- The MiSTer has to run Zaparoo Core, which most MiSTer setups do.
- Core's own gaps remain on the MiSTer: any client on the home network may
  call its settings and input methods. This plugin never does, but it cannot
  stop another client. Pairing as a member client, an API key, and
  `block_commands` for `execute`, `mister.script` and `mister.ini` close them,
  and each is a change on the MiSTer for the owner to make
  ([deferred.md](deferred.md)).
- A search finds only what Core has indexed; a game added since is not found
  until Core indexes it again, which this plugin will not start.
- Zaparoo's API is v0.1 and may still grow; a breaking change would show
  only against the real MiSTer, never against the simulator.

## Related

[ADR-MM-002](ADR-MM-002-switch-the-tv-through-tv-mcps-own-tools.md),
`src/mister_mcp/zaparoo.py`, `src/mister_mcp/simulator.py`.
