# ADR-MM-002: Switch the TV through the TV plugin's own tools

## Status

Accepted, 2026-11-11, after asking tv-mcp's session how it wants other
plugins to reach a TV.

## Context

After a game starts, the TV the MiSTer is plugged into should show it, but
only when that TV is already on: this plugin never switches a TV on. tv-mcp
owns the TVs. It names the device on each input in its owner's settings
(`[tvs.<key>.inputs]`, "HDMI 3" = "MiSTer FPGA"), its `tv_input` tool takes
such a name, and `tv_input` itself refuses unless the TV's own screen reads
"on" (its rule "an input is changed only while the screen is on").

A plugin is a child process of the bridge and cannot ask the bridge to call
another plugin's tool.

## Options considered

- **Import tv-mcp and drive its service directly.** Not taken: tv-mcp's
  session asked that a TV be acted on through its tools, not its internals,
  so that one place owns the TV and its guards.
- **Read tv-mcp's settings and talk to the TV ourselves.** Not taken: a
  second copy of the TV's guards, and a reason to read another plugin's
  private file.
- **Leave it to the voice**, answering "now switch the TV". Not taken as the
  only way: the voice may not do it, and the owner asked for the launch to
  switch the TV. It remains what the answer says when the switch is not made.
- **Do nothing.** Not taken: the owner asked for it.

## Decision

When the owner's `~/.config/mister-mcp/config.toml` has a `[tv]` table, the
plugin starts the TV plugin's own MCP server as a child over stdio (the
command given there, such as `uv run --directory ~/tv-mcp tv-mcp serve`),
calls `tv_status` for that TV, and only when it reports the screen on
(`screen`, or `state` when there is no `screen`) calls
`tv_input(source=<device>, tv=<tv>)` and reports what `tv_input` said. It
never calls any other TV tool. When `tv_input` is not offered (its feature is
off in tv-mcp's settings), the TV is left alone and the answer says so; this
plugin never switches that feature on. mister-mcp never reads tv-mcp's
settings. The child is closed after each launch, and is started only after
the MiSTer showed the game had started.

The rest of the plugin sees only a small interface, `TvSwitch.show_mister()`.
When plugins can ask the bridge to call another plugin's tool, a `TvSwitch`
that asks the bridge for `tv_input` replaces the stdio child, and nothing
else changes.

## Consequences

- The owner's working rule that nothing switches a TV on at night holds here
  at every hour, because no power tool is ever called and `tv_input` refuses a
  TV whose screen is not on. A start at night can still change what an
  already-on screen shows, because the owner asked for the game. A time window
  of its own would be a new decision.

- A second tv-mcp process talks to the TV for a moment, beside the bridge's.
- Starting it adds a few seconds to a launch, so the TV step has its own
  deadline inside the voice's time; past it, the game is still started and
  the answer says the TV was not switched.
- A change to tv-mcp's tool names or answers breaks this step; the tests use a
  stand-in with the fields tv-mcp's session documented.

## Related

[ADR-MM-001](ADR-MM-001-build-on-zaparoo-core.md), `src/mister_mcp/tv.py`.
