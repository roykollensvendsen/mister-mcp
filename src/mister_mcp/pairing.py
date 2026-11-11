# SPDX-License-Identifier: GPL-3.0-or-later
"""Pairing with a secured Zaparoo Core, and the per-session cipher that follows (ADR-MM-005).

A secured Zaparoo serves a remote client only after it is paired. Pairing is
a PAKE2 handshake on P-256 (schollz/pake v3, as Zaparoo Core uses it) with
the six-digit PIN Zaparoo shows, then two HMAC confirms. Both sides end with
the same 32-byte pairing key; Zaparoo gives an auth token to go with it.
Each later connection derives its own AES-256-GCM keys from that key and a
fresh salt. The protocol is Core's docs/api/encryption.md.

The PIN is used once and never kept. The pairing key is kept only in the
owner's settings folder, readable by the owner alone, and never printed.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from ecdsa import NIST256p
from ecdsa.ellipticcurve import Point

if TYPE_CHECKING:
    import pathlib

#: The curve, and schollz/pake v3's fixed U and V points on it ("p256" in its initCurve).
CURVE = NIST256p
U = Point(
    CURVE.curve,
    793136080485469241208656611513609866400481671852,
    59748757929350367369315811184980635230185250460108398961713395032485227207304,
)
V = Point(
    CURVE.curve,
    1086685267857089638167386722555472967068468061489,
    9157340230202296554417312816309453883742349874205386245733062928888341584123,
)
#: The file, in the settings folder, that keeps the auth token and the pairing key.
PAIRING_FILE = "zaparoo-pairing.json"
#: Seconds one pairing request may take.
PAIR_WITHIN = 10.0

_PROTOCOL, _CURVE_NAME = b"zaparoo-v1", b"p256"
_WIRE_ORDER = ("ux", "uy", "vx", "vy", "xx", "xy", "yx", "yy")
_PIN = re.compile(r"\d{6}")

WRONG_PIN = (
    "Zaparoo did not accept that PIN. Check the six digits on the MiSTer, then run the pair command again."
)
#: What each refusal Zaparoo's pairing endpoints give means, with what to do next.
REFUSALS = {
    400: "Zaparoo did not understand the pairing request. Run the pair command again.",
    401: WRONG_PIN,
    403: "Zaparoo will not pair again with this PIN. Start a new pairing on the MiSTer, then run pair again.",
    404: "The pairing took too long. Start a new pairing on the MiSTer, then run the pair command.",
    410: "The PIN has expired. Start a new pairing on the MiSTer, then run the pair command.",
    429: "Zaparoo asked for a pause. Wait a moment, then run the pair command again.",
}
UNTRUSTED = (
    "The MiSTer could not prove it knows the PIN, so nothing was saved. "
    "Start a new pairing on the MiSTer, then run the pair command again."
)


class PairingError(ValueError):
    """Pairing failed; the message says why and what to do next."""


@dataclass(frozen=True)
class Pairing:
    """What a paired client keeps: the auth token (not secret) and the pairing key (secret)."""

    auth_token: str
    pairing_key: bytes = field(repr=False)


def _bytes(n: int) -> bytes:
    """Go's big.Int.Bytes(): big-endian with no leading zeros; empty for zero."""
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def encode(role: int, points: dict[str, tuple[int, int] | None]) -> bytes:
    """A PAKE message in Zaparoo's wire format: decimal strings, in its field order, role last."""
    wire: dict[str, Any] = {}
    for name in ("u", "v", "x", "y"):
        point = points.get(name)
        wire[f"{name}x"], wire[f"{name}y"] = (str(point[0]), str(point[1])) if point else ("0", "0")
    wire["role"] = role
    return json.dumps({k: wire[k] for k in (*_WIRE_ORDER, "role")}, separators=(",", ":")).encode()


def decode(message: bytes, *, role: int) -> dict[str, tuple[int, int]]:
    """The points in a PAKE message from the party in `role`; PairingError when it is not one."""
    try:
        wire = json.loads(message)
        coords = {k: int(str(wire[k])) for k in _WIRE_ORDER}
        their_role = wire["role"]
    except (ValueError, KeyError, TypeError) as error:
        raise PairingError(REFUSALS[400]) from error
    if their_role != role or any(n < 0 for n in coords.values()):
        raise PairingError(REFUSALS[400])
    return {name: (coords[f"{name}x"], coords[f"{name}y"]) for name in ("u", "v", "x", "y")}


def _on_curve(point: tuple[int, int]) -> Point:
    if not CURVE.curve.contains_point(*point):
        raise PairingError(REFUSALS[400])
    return Point(CURVE.curve, *point)


class PakeClient:
    """The client, role 0, of schollz/pake v3's handshake on P-256."""

    def __init__(self, pin: str, *, alpha: int | None = None) -> None:
        """Start with the six-digit `pin`; `alpha` fixes the secret, for tests only."""
        self._pin = pin.encode()
        self._pw = int.from_bytes(self._pin, "big")
        self._alpha = alpha if alpha is not None else 1 + secrets.randbelow(CURVE.order - 1)
        x = self._pw * U + self._alpha * CURVE.generator
        self._x = (x.x(), x.y())

    def message(self) -> bytes:
        """Message A: U, V and X, with Y not yet known."""
        return encode(0, {"u": (U.x(), U.y()), "v": (V.x(), V.y()), "x": self._x, "y": None})

    def update(self, reply: bytes) -> bytes:
        """The session key, from Zaparoo's message B."""
        y = _on_curve(decode(reply, role=1)["y"])
        z = self._alpha * (y + (-(self._pw * V)))
        digest = hashlib.sha256(self._pin)
        for n in (*self._x, y.x(), y.y(), z.x(), z.y()):
            digest.update(_bytes(n))
        return digest.digest()


def _expand(prk: bytes, info: str, length: int) -> bytes:
    return HKDFExpand(hashes.SHA256(), length, info.encode()).derive(prk)


def confirm_keys(session_key: bytes, msg_a: bytes, msg_b: bytes) -> tuple[bytes, bytes, bytes]:
    """The client's and server's confirm keys and the pairing key, bound to both raw messages."""
    prk = hmac.new(msg_a + msg_b, session_key, hashlib.sha256).digest()  # HKDF-Extract
    return (
        _expand(prk, "zaparoo-confirm-A", 32),
        _expand(prk, "zaparoo-confirm-B", 32),
        _expand(prk, "zaparoo-pairing-v1", 32),
    )


def pairing_hmac(key: bytes, role: str, name: str, msg_a: bytes, msg_b: bytes) -> bytes:
    """Zaparoo's confirm: HMAC-SHA256 over length-prefixed protocol, curve, role, name and messages."""
    mac = hmac.new(key, digestmod=hashlib.sha256)
    for part in (_PROTOCOL, _CURVE_NAME, role.encode(), name.encode(), msg_a, msg_b):
        mac.update(len(part).to_bytes(4, "big") + part)
    return mac.digest()


async def _call(post: Any, path: str, body: dict[str, str]) -> dict[str, Any]:  # noqa: ANN401
    status, answer = await post(path, body)
    if status != 200:  # noqa: PLR2004 - HTTP's own OK
        raise PairingError(REFUSALS.get(status, REFUSALS[400]))
    return dict(answer)


async def pair(pin: str, *, name: str, post: Any) -> Pairing:  # noqa: ANN401
    """Pair as `name` with the PIN Zaparoo shows, through `post`; nothing is kept here."""
    # RULE: a pin that is not six digits is never sent
    if not _PIN.fullmatch(pin):
        msg = "A Zaparoo PIN is six digits. Run the pair command again, and type the digits the MiSTer shows."
        raise PairingError(msg)
    client = PakeClient(pin)
    msg_a = client.message()
    started = await _call(post, "/api/pair/start", {"pake": base64.b64encode(msg_a).decode(), "name": name})
    msg_b = base64.b64decode(started["pake"])
    a_key, b_key, pairing_key = confirm_keys(client.update(msg_b), msg_a, msg_b)
    confirm = base64.b64encode(pairing_hmac(a_key, "client", name, msg_a, msg_b)).decode()
    finished = await _call(post, "/api/pair/finish", {"session": started["session"], "confirm": confirm})
    expected = pairing_hmac(b_key, "server", name, msg_a, msg_b)
    # RULE: a server that cannot prove the pin is never trusted
    if not hmac.compare_digest(expected, base64.b64decode(finished.get("confirm", ""))):
        raise PairingError(UNTRUSTED)
    return Pairing(auth_token=str(finished["authToken"]), pairing_key=pairing_key)


def http_post(address: str, port: int) -> Any:  # noqa: ANN401
    """POST JSON to Zaparoo's pairing endpoints at `address`:`port`, answering (status, body)."""

    def send(path: str, body: dict[str, str]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"http://{address}:{port}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=PAIR_WITHIN) as answer:  # noqa: S310
                return answer.status, json.loads(answer.read() or b"{}")
        except urllib.error.HTTPError as refused:
            return refused.code, {}

    async def post(path: str, body: dict[str, str]) -> tuple[int, dict[str, Any]]:
        return await asyncio.to_thread(send, path, body)

    return post


def save_pairing(path: pathlib.Path, pairing: Pairing) -> None:
    """Keep `pairing` in `path`, readable by the owner alone."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"authToken": pairing.auth_token, "pairingKey": base64.b64encode(pairing.pairing_key).decode()}
    )
    # RULE: the pairing key is kept where only the owner can read it
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as kept:
        kept.write(body)


def load_pairing(path: pathlib.Path) -> Pairing | None:
    """The pairing kept in `path`; None when there is none; refused when others can read it."""
    if not path.is_file():
        return None
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        msg = f"{path} can be read by others. Run chmod 600 {path} in a terminal, then try again."
        raise PairingError(msg)
    try:
        kept = json.loads(path.read_text())
        return Pairing(auth_token=str(kept["authToken"]), pairing_key=base64.b64decode(kept["pairingKey"]))
    except (ValueError, KeyError, TypeError) as error:
        msg = f"{path} is damaged. Pair again: run the pair command."
        raise PairingError(msg) from error


def session_keys(pairing_key: bytes, salt: bytes) -> tuple[bytes, bytes, bytes, bytes]:
    """The client-to-server and server-to-client keys and nonce bases for one connection."""
    prk = hmac.new(salt, pairing_key, hashlib.sha256).digest()
    return (
        _expand(prk, "zaparoo-c2s-v1", 32),
        _expand(prk, "zaparoo-s2c-v1", 32),
        _expand(prk, "zaparoo-c2s-nonce-v1", 12),
        _expand(prk, "zaparoo-s2c-nonce-v1", 12),
    )


class _Cipher:
    """AES-256-GCM in one direction, with a nonce counted up from its base."""

    def __init__(self, key: bytes, base: bytes, aad: bytes) -> None:
        self._aead, self._base, self._aad = AESGCM(key), base, aad
        self.counter = 0

    def _nonce(self) -> bytes:
        mixed = int.from_bytes(self._base[4:], "big") ^ self.counter
        return self._base[:4] + mixed.to_bytes(8, "big")

    def seal(self, plain: bytes) -> bytes:
        """Encrypt the next frame."""
        sealed = self._aead.encrypt(self._nonce(), plain, self._aad)
        self.counter += 1
        return sealed

    def open(self, sealed: bytes) -> bytes:
        """Decrypt the next frame; raises when it was not sealed with this key, nonce and AAD."""
        plain = self._aead.decrypt(self._nonce(), sealed, self._aad)
        self.counter += 1
        return plain


def session_cipher(key: bytes, base: bytes, aad: bytes) -> _Cipher:
    """One direction's cipher for a connection."""
    return _Cipher(key, base, aad)
