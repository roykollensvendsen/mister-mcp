# Changelog

Every release, what changed in it, and why. Dates are the tag's date. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

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
