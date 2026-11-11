<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# AGENTS.md

Instructions for coding agents working in this repository. People should
start with [README.md](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md);
this file is the same rules, for an agent.

## What this is

Voice control for a MiSTer FPGA: an MCP server that claude-voice can take in
as an optional plugin. It says what the MiSTer is running, finds a game by
name and starts it. What it reuses, and why, is in [`decisions/`](decisions/README.md).

## Hard rules

1. **Nothing on the MiSTer is written, deleted or changed** by any tool: no
   file, no setting, no command of the plugin's own choosing. Only the API
   calls listed in the decision records are ever sent.
2. **A TV is never switched on** by this plugin. A TV that is already on may be
   switched to the MiSTer's input, through the TV plugin's own tools.
3. **Nothing about the owner's home is committed**: no home-network address,
   hardware address, host name, key or token. Examples use 192.0.2.x and
   00:00:5E:00:53:xx. `scripts/private_data_scan.py` refuses the rest, in the
   pre-commit hook and in CI; never weaken it to make a commit pass.
4. **No link to a Claude session in a commit message.** No `Claude-Session:`
   line, whatever an assistant's own attribution says;
   `scripts/no_session_links.py` refuses it.
5. **Never touch the real MiSTer** unless the owner asks for it in this
   session. The simulator is for every try until then.
6. Every line marked `# RULE:` has a row in `scripts/mutations.toml` and a
   test named after it, and `uv run python scripts/mutate.py` must show each
   rule's own test going red.

## Commands

The gates are in [CONTRIBUTING.md](CONTRIBUTING.md#the-gates); run them all
after the last edit.
