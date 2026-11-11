# Changelog

Every release, what changed in it, and why. Dates are the tag's date. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- `mister_status`: whether the MiSTer is on, and the system and game it runs,
  read from Zaparoo Core. A MiSTer that does not answer is said to be off or
  off the network, never one of the two.
- `mister-mcp serve` and `mister-mcp status`, each with `--simulate` for a
  pretend MiSTer whose every answer says "Simulated:".
