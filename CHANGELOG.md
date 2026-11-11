# Changelog

Every release, what changed in it, and why. Dates are the tag's date. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- update_all by voice (ADR-MM-004): `mister_update_request` checks and asks,
  naming a running game and refusing below 512 MB free, while a run is
  going, or just after the MiSTer started; `mister_update_confirm` starts it
  on the owner's yes; `mister_update_status` says its step, about how long
  is left, and how it ended. Every SSH command comes from a fixed list.
- The quality ratchet counts layer violations: each module has a layer, and
  may import at load time only from the layers below it.
- SSH to the MiSTer is by key only: password and keyboard login are off,
  and no password is written anywhere, not even the factory default. A
  settings file holding a password is refused. A refused key is said with
  `ssh-copy-id` and the advice to change the MiSTer's default password.
- A start Zaparoo refuses is said in plain words, by its error category,
  with what to do next; Zaparoo's own message is never read aloud. A start
  that timed out or was cut off is said as not yet known, not as refused.
- A start is read back up to three times, a second apart, so a game a real
  MiSTer is still loading is not said to have failed.
- The commands the voice suggests run as typed: `uv run --directory
  ~/mister-mcp mister-mcp status`, and the TV plugin's own command from the
  settings with `status` in place of `serve`.
- A launch while a game runs asks first, naming the game it would end.
  `mister_launch_confirm` with the question's one-time token, within a
  minute, starts the new one. From the menu, a launch starts at once.
- A launch still going at the voice's deadline says to ask what the MiSTer
  is playing, never to ask again, so a slow start is not sent twice.
- The MiSTer is found by its name first, then by spare `addresses` from the
  settings, in order, within six seconds. Status says which address
  answered. When none does, the voice names each one tried, in Norwegian, in
  the owner's words, with what to check.
- `mister_status`: whether the MiSTer is on, and the system and game it runs,
  read from Zaparoo Core. A MiSTer that does not answer is said to be off or
  off the network, never one of the two.
- A MiSTer that is on but refuses the connection, because Zaparoo is not
  running on it, is said to be on, with the step that starts Zaparoo.
- SSH options for the later power work: key only, in batch mode, never a
  password. A missing key is said in Norwegian, in the owner's words, with the
  `ssh-copy-id` that puts it back. No SSH command runs yet.
- Every failure says what is wrong and what to do next: an unknown system
  is answered with the systems the MiSTer has, a start the MiSTer does not
  show, a TV left alone, an unreachable TV plugin and a settings file that
  is not valid TOML each name the step to take.
- `mister_search`: up to five games whose names hold every word said, among
  those Zaparoo has indexed, each with its system.
- `mister_launch`: starts a game by name, or a system's core alone, then
  reads back what the MiSTer runs. When a `[tv]` table is set, the TV the
  MiSTer is plugged into is then switched to it, only if it is already on.
- `mister-mcp serve` and `mister-mcp status`, each with `--simulate` for a
  pretend MiSTer whose every answer says "Simulated:".

### Fixed

- The TV's screen is read from its own entry under `tvs` in tv-mcp's
  answer. Reading only the top level took every TV for off, so the MiSTer
  was never shown on it. The pretend TV plugins now answer in that shape.
- A TV plugin that is slow to start or answer is still closed afterwards,
  in its own two-second deadline, so its process is never left running.
