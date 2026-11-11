# ADR-MM-004: Run update_all over SSH, by key, from a fixed list of commands

## Status

Accepted, 2026-11-11. The owner asked for update_all by voice and said yes
to this plan through the manager session.

## Context

update_all keeps the MiSTer's cores, menu and Linux current. It is a script
on the SD card, `/media/fat/Scripts/update_all.sh`, run from the MiSTer's
Scripts menu. Zaparoo cannot run it: its `**mister.script` command is one
this plugin never sends (ADR-MM-001). A run takes minutes, far past the
voice's 15 seconds. It may reboot the MiSTer at the end, which ends any game.

The first version's rule was "the only SSH command ever is the fixed
shutdown". This record widens it, and only as far as written here.

Read from update_all's source (theypsilon/Update_All_MiSTer, master,
2026-11-11):

- `UPDATE_ALL_NON_INTERACTIVE=true` skips the settings countdown, the
  settings screen and the log viewer, so it runs with no terminal.
- While it runs, every printed line is written and flushed to
  `/tmp/update_all_print.log`, in memory. The full log ends up in
  `/media/fat/Scripts/.config/update_all/update_all.log`.
- It ends with a line starting "Success!", or lists the updaters that
  failed. When a system file changed it prints "Rebooting in N seconds..."
  or "Rebooting now..." and reboots (`autoreboot`, on by default). With
  autoreboot off it prints "You should reboot".
- The free-space refusal ("/media/fat is FULL. Minimum required space for
  /media/fat is 512MB.") comes from the Downloader it runs.

## Decision

- **SSH by key only**, with BatchMode and every password method off
  (`mister_mcp.ssh`). No password is written anywhere.
- **Commands from a fixed list, nothing else.** Each SSH command the plugin
  can send is a constant in `ALLOWED_COMMANDS`. A tool picks one by name and
  never passes words of its own or the voice's. A test pins the exact set:
  - free space on `/media/fat`;
  - whether update_all is already running;
  - the MiSTer's uptime;
  - the last lines of the live log and of the saved log;
  - start update_all detached, with no terminal and its output discarded.
    Its own logs are what is read back.
- **A request and a confirm.** `mister_update_request` checks first and asks.
  It refuses below 512 MB free on `/media/fat`, saying how much is free. It
  refuses while a run is already going, and within two minutes of the
  MiSTer starting. When a game or core runs, the question names it (the
  owner's ask-first rule). Its token is one-time and expires after a minute.
  `mister_update_confirm` starts the run.
- **Following a run.** `mister_update_status` (read only) reads the live log:
  started, the current step, done or failed. A failure is said in plain
  words with the next step; a full card is "The SD card is full; ask the
  manager what can be deleted." After a reboot the live log is gone, and
  the saved log tells the end.
- **Telling the owner unasked** needs a bridge feature that turns a plugin
  event into a whats_new item. Until then, `mister_update_status` is how the
  owner hears it.

## Consequences

- The plugin can now change the MiSTer: update_all writes cores and files,
  and may reboot it. That is why it needs a spoken yes, and why the list of
  commands is fixed and tested.
- A new kind of command needs a change to `ALLOWED_COMMANDS`, its test and
  this record, never a tool argument.
- The first real run is by day, with the owner at the MiSTer, after the SD
  card has room.
