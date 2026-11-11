# Changelog

Every release, what changed in it, and why. Dates are the tag's date. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- `mister_status`: whether the MiSTer is on, and the system and game it runs,
  read from Zaparoo Core. A MiSTer that does not answer is said to be off or
  off the network, never one of the two.
- A MiSTer that is on but refuses the connection, because Zaparoo is not
  running on it, is said to be on, with the step that starts Zaparoo.
- `mister_search`: up to five games whose names hold every word said, among
  those Zaparoo has indexed, each with its system.
- `mister_launch`: starts a game by name, or a system's core alone, then
  reads back what the MiSTer runs. When a `[tv]` table is set, the TV the
  MiSTer is plugged into is then switched to it, only if it is already on.
- `mister-mcp serve` and `mister-mcp status`, each with `--simulate` for a
  pretend MiSTer whose every answer says "Simulated:".
