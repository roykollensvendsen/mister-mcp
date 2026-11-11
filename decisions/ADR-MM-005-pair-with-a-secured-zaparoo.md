# ADR-MM-005: Pair with a secured Zaparoo, by a PIN the owner types

## Status

Accepted, 2026-11-11. The owner secured Zaparoo Core on the MiSTer and asked
for the voice plugin to be paired; the manager session relayed his yes.

## Context

A secured Zaparoo Core serves a remote WebSocket client only when it opens
with an encrypted first frame from a paired client. Plaintext works only
from the MiSTer itself. This plugin runs on another computer, so once the
owner turned security on, it lost status, search and launch.

Pairing, as Core's `docs/api/encryption.md` and `pkg/api/pairing.go`
describe it: the owner starts a pairing on the MiSTer, which shows a
six-digit PIN for five minutes. The client and Core run a PAKE2 handshake on
P-256 (schollz/pake v3, no identities bound) through `POST /api/pair/start`.
Each then proves the PIN with an HMAC over a length-prefixed transcript
(`/api/pair/finish`). Both end with a 32-byte pairing key, and Core issues an
auth token. Every later connection derives AES-256-GCM keys from that key
and a fresh 16-byte salt.

## Options considered

- **A static API key with encryption turned off.** Not taken: Core calls it
  an admin escape hatch, so the key would carry admin rights, and every frame
  would be plaintext on the home network.
- **Leave Zaparoo unsecured.** That is the owner's call, not this plugin's.
- **Pair as Zaparoo's own apps do.** Taken.

## Decision

- `mister-mcp pair` asks for the PIN with `getpass`, so what is typed is
  not shown. The owner types it himself, on this computer, never to an
  assistant. A PIN that is not six digits is refused before anything is
  sent.
- The client checks Zaparoo's confirm too. A server that cannot prove it
  knows the PIN is not trusted, and nothing is saved.
- The auth token and the pairing key are kept in
  `~/.config/mister-mcp/zaparoo-pairing.json`, mode 0600. A file others can
  read is refused. The key is never printed, logged or committed.
- The role is Zaparoo's to give. A client cannot ask for one: Core gives the
  first paired client `admin` and later ones `member`. The owner's phone
  was paired first, so this plugin is a member. That means status, search
  and launch, with no settings, power or updates.
- Two pinned dependencies: `cryptography` for AES-GCM and HKDF, and `ecdsa`
  for the raw P-256 point maths, which `cryptography` does not expose.
  ecdsa's maths is not constant-time. That is accepted for a one-off
  handshake on the home network, guarded by a PIN that allows three tries
  and lasts five minutes.

## Proof

The tests pin Zaparoo's own known answers: the U and V points, the spec's
example message, the nonce XOR cases and the HKDF labels. They also pin the
HMAC transcript exactly as Core builds it, and a responder that mirrors
pake.go's role 1 step by step. A cross-check that runs Core's Go code was
not available in this session. The live pairing is the last check, and a
mistake there fails only as "wrong PIN" (HTTP 401).

## Consequences

- The encrypted connection itself, which uses this pairing, is a separate
  change.
- Losing the file means pairing again. Removing the client in Zaparoo's
  settings undoes the pairing from the MiSTer's side.
