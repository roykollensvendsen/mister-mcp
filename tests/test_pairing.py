# SPDX-License-Identifier: GPL-3.0-or-later
"""Pairing with a secured Zaparoo Core (ADR-MM-005).

Zaparoo pairs a client with a PAKE2 handshake on P-256, schollz/pake v3, and
two HMAC confirms (Core's docs/api/encryption.md and pkg/api/pairing.go). The
known answers here are Zaparoo's own: the U and V points, the spec's example
message, the nonce cases and the HKDF labels. The responder below mirrors
pake.go's role 1, step by step, so the client is checked against it.
"""

import asyncio
import base64
import hashlib
import hmac
import http.server
import json
import stat
import threading

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from ecdsa import NIST256p
from ecdsa.ellipticcurve import Point

from mister_mcp import cli
from mister_mcp.pairing import (
    CURVE,
    FULL,
    NEW_PIN,
    PAIRING_FILE,
    PIN_LIFETIME,
    PIN_TRIES,
    WRONG_PIN,
    ZAPAROO_PAIR_INTERVAL,
    Pairing,
    PairingError,
    PakeClient,
    U,
    V,
    _error_body,
    confirm_keys,
    decode,
    http_post,
    load_pairing,
    pair,
    pairing_hmac,
    save_pairing,
    session_cipher,
    session_keys,
)
from mister_mcp.simulator import SimulatedPairing

PIN = "482915"
NAME = "mister-mcp"
TOKEN = "test-auth-token"  # noqa: S105 - a made-up token for the tests

#: The example client message in Zaparoo's docs/api/encryption.md, as printed there.
SPEC_EXAMPLE = {
    "role": 0,
    "ux": "793136080485469241208656611513609866400481671852",
    "uy": "59748757929350367369315811184980635230185250460108398961713395032485227207304",
    "vx": "1086685267857089638167386722555472967068468061489",
    "vy": "9157340230202296554417312816309453883742349874205386245733062928888341584123",
    "xx": "48439561293906451759052585252797914202762949526041747995844080717082404635286",
    "xy": "36134250956749795798585127919587881956611106672985015071877198253568414405109",
    "yx": "0",
    "yy": "0",
}


def _bytes(n):
    """Go's big.Int.Bytes(): big-endian, no leading zeros, empty for zero."""
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


class Responder:
    """Zaparoo's side, mirroring schollz/pake v3 pake.go Update() for role 1."""

    def __init__(self, pin, alpha=7919):
        self.pw = int.from_bytes(pin.encode(), "big")
        self.pin, self.alpha = pin.encode(), alpha

    def answer(self, msg_a):
        a = json.loads(msg_a)
        x = Point(CURVE.curve, int(a["xx"]), int(a["xy"]))
        assert CURVE.curve.contains_point(x.x(), x.y())
        upw, vpw = self.pw * U, self.pw * V
        y = vpw + self.alpha * CURVE.generator
        z = self.alpha * (x + (-upw))
        h = hashlib.sha256(self.pin)
        for n in (x.x(), x.y(), y.x(), y.y(), z.x(), z.y()):
            h.update(_bytes(n))
        self.key = h.digest()
        wire = {
            "ux": str(U.x()),
            "uy": str(U.y()),
            "vx": str(V.x()),
            "vy": str(V.y()),
            "xx": a["xx"],
            "xy": a["xy"],
            "yx": str(y.x()),
            "yy": str(y.y()),
            "role": 1,
        }
        return json.dumps(wire, separators=(",", ":")).encode()


class FakeZaparoo:
    """A pretend Zaparoo pairing endpoint, with the HTTP answers Core gives."""

    def __init__(self, pin=PIN, *, status_start=200, status_finish=200, bad_server_hmac=False):
        self.responder = Responder(pin)
        self.name = None
        self.status_start, self.status_finish = status_start, status_finish
        self.bad_server_hmac = bad_server_hmac

    async def __call__(self, path, body):
        if path == "/api/pair/start":
            if self.status_start != 200:
                return self.status_start, {"error": "no"}
            self.msg_a = base64.b64decode(body["pake"])
            self.name = body["name"]
            self.msg_b = self.responder.answer(self.msg_a)
            return 200, {"session": "s-1", "pake": base64.b64encode(self.msg_b).decode()}
        assert path == "/api/pair/finish"
        assert body["session"] == "s-1"
        a_key, b_key, self.pairing_key = confirm_keys(self.responder.key, self.msg_a, self.msg_b)
        expected = pairing_hmac(a_key, "client", self.name, self.msg_a, self.msg_b)
        if self.status_finish != 200 or base64.b64decode(body["confirm"]) != expected:
            return 401, {"error": "pairing confirmation HMAC mismatch"}
        server = pairing_hmac(b_key, "server", self.name, self.msg_a, self.msg_b)
        if self.bad_server_hmac:
            server = bytes(32)
        return 200, {"authToken": TOKEN, "clientId": "c-1", "confirm": base64.b64encode(server).decode()}


def _run(coro):
    return asyncio.run(coro)


# -- Zaparoo's own known answers -------------------------------------------------------------


def test_the_u_and_v_points_are_schollz_pakes_p256_ones():
    assert (U.x(), U.y()) == (int(SPEC_EXAMPLE["ux"]), int(SPEC_EXAMPLE["uy"]))
    assert (V.x(), V.y()) == (int(SPEC_EXAMPLE["vx"]), int(SPEC_EXAMPLE["vy"]))
    assert CURVE is NIST256p


def test_the_specs_example_message_decodes_to_points_on_the_curve():
    points = decode(json.dumps(SPEC_EXAMPLE).encode(), role=0)
    assert CURVE.curve.contains_point(*points["x"])


def test_a_client_message_is_zaparoos_wire_format_in_its_order():
    msg = PakeClient(PIN, alpha=12345).message()
    assert list(json.loads(msg)) == ["ux", "uy", "vx", "vy", "xx", "xy", "yx", "yy", "role"]
    assert json.loads(msg)["role"] == 0
    assert json.loads(msg)["yx"] == "0"
    assert b" " not in msg


def test_the_nonce_is_the_base_with_the_counter_xored_into_its_last_8_bytes():
    # Zaparoo's TestKAT_NonceXORConstruction, with its literal values.
    base = bytes(range(1, 13))
    key = b"\x77" * 32
    aad = b"auth-token:ws"
    cases = {
        0: base,
        1: bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13]),
        0xFFFFFFFFFFFFFFFE: bytes([1, 2, 3, 4]) + bytes(b ^ 255 for b in range(5, 12)) + bytes([12 ^ 254]),
    }
    for counter, nonce in cases.items():
        cipher = session_cipher(key, base, aad)
        cipher.counter = counter
        assert cipher.seal(b"zaparoo") == AESGCM(key).encrypt(nonce, b"zaparoo", aad)


def test_the_session_keys_use_the_specs_labels():
    # Zaparoo's TestKAT_DeriveSessionKeysMatchesSpecLabels, re-derived with its literal labels.
    pairing_key, salt = b"\x42" * 32, b"\xaa" * 16
    prk = hmac.new(salt, pairing_key, hashlib.sha256).digest()

    def expand(info, n):
        return HKDFExpand(hashes.SHA256(), n, info.encode()).derive(prk)

    assert session_keys(pairing_key, salt) == (
        expand("zaparoo-c2s-v1", 32),
        expand("zaparoo-s2c-v1", 32),
        expand("zaparoo-c2s-nonce-v1", 12),
        expand("zaparoo-s2c-nonce-v1", 12),
    )


def test_the_confirm_hmac_is_zaparoos_length_prefixed_transcript():
    key = b"\x01" * 32
    transcript = b"".join(
        len(f).to_bytes(4, "big") + f for f in (b"zaparoo-v1", b"p256", b"client", b"mister-mcp", b"A", b"B")
    )
    expected = hmac.new(key, transcript, hashlib.sha256).digest()
    assert pairing_hmac(key, "client", "mister-mcp", b"A", b"B") == expected


# -- the handshake -------------------------------------------------------------------------


def test_the_client_and_a_mirrored_responder_agree_on_the_session_key():
    client = PakeClient(PIN)
    responder = Responder(PIN)
    msg_b = responder.answer(client.message())
    assert client.update(msg_b) == responder.key


def test_a_wrong_pin_gives_a_different_session_key():
    client = PakeClient("111111")
    responder = Responder(PIN)
    assert client.update(responder.answer(client.message())) != responder.key


def test_a_reply_that_is_not_on_the_curve_is_refused():
    client = PakeClient(PIN)
    bad = json.loads(Responder(PIN).answer(client.message()))
    bad["yy"] = str(int(bad["yy"]) + 1)
    with pytest.raises(PairingError):
        client.update(json.dumps(bad).encode())


def test_a_reply_in_the_clients_own_role_is_refused():
    client = PakeClient(PIN)
    with pytest.raises(PairingError):
        client.update(client.message())


def test_pairing_gives_the_auth_token_and_pairing_key():
    zaparoo = FakeZaparoo()
    got = _run(pair(PIN, name=NAME, post=zaparoo))
    assert got == Pairing(auth_token=TOKEN, pairing_key=zaparoo.pairing_key)
    assert zaparoo.name == NAME


@pytest.mark.parametrize(
    ("start", "finish", "said"),
    [
        (200, 401, "did not accept that PIN"),
        (410, 200, "new PIN"),
        (403, 200, "Start a new pairing"),
        (429, 200, "Wait a moment"),
    ],
)
def test_a_refused_pairing_says_why_and_what_to_do(start, finish, said):
    with pytest.raises(PairingError, match=said):
        _run(pair(PIN, name=NAME, post=FakeZaparoo(status_start=start, status_finish=finish)))


class Clock:
    """Time that moves only when the pairing pauses or a test moves it."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    async def pause(self, seconds):
        self.now += seconds


def test_the_finish_waits_out_zaparoos_one_request_a_second():
    clock = Clock()
    got = _run(pair(SimulatedPairing.PIN, name=NAME, post=SimulatedPairing(clock), pause=clock.pause))
    assert got.auth_token == "simulated"  # noqa: S105 - the simulated Zaparoo's made-up token


def test_a_second_pairing_request_within_zaparoos_interval_is_refused():
    clock = Clock()
    zaparoo = SimulatedPairing(clock)
    client = PakeClient(SimulatedPairing.PIN)
    start = {"pake": base64.b64encode(client.message()).decode(), "name": NAME}
    assert _run(zaparoo("/api/pair/start", start))[0] == 200
    clock.now += ZAPAROO_PAIR_INTERVAL - 0.01
    assert _run(zaparoo("/api/pair/finish", {"session": "simulated", "confirm": ""})) == (429, {})
    with pytest.raises(PairingError, match="asked for a pause"):
        _run(pair(SimulatedPairing.PIN, name=NAME, post=zaparoo, pause=clock.pause))


def _try(pin, zaparoo, clock):
    """A pairing started after waiting out Zaparoo's one request a second, as a person would."""
    clock.now += ZAPAROO_PAIR_INTERVAL
    return _run(pair(pin, name=NAME, post=zaparoo, pause=clock.pause))


def test_a_pin_is_spent_after_three_wrong_tries():
    clock = Clock()
    zaparoo = SimulatedPairing(clock)
    said = []
    for _ in range(3):
        with pytest.raises(PairingError) as refused:
            _try("123456", zaparoo, clock)
        said.append(str(refused.value))
    assert said[:2] == [WRONG_PIN, WRONG_PIN]
    assert said[2] == NEW_PIN
    with pytest.raises(PairingError, match=NEW_PIN):
        _try(SimulatedPairing.PIN, zaparoo, clock)


def test_a_pin_older_than_five_minutes_is_refused():
    clock = Clock()
    zaparoo = SimulatedPairing(clock)
    clock.now += PIN_LIFETIME + 1
    with pytest.raises(PairingError, match=NEW_PIN):
        _try(SimulatedPairing.PIN, zaparoo, clock)
    with pytest.raises(PairingError, match=NEW_PIN):
        _try(SimulatedPairing.PIN, zaparoo, clock)


def test_a_pin_still_within_its_five_minutes_and_three_tries_pairs():
    clock = Clock()
    shown = clock.now
    zaparoo = SimulatedPairing(clock)
    for _ in range(PIN_TRIES - 1):
        with pytest.raises(PairingError, match="did not accept that PIN"):
            _try("123456", zaparoo, clock)
    clock.now = shown + PIN_LIFETIME - 1 - ZAPAROO_PAIR_INTERVAL
    assert _try(SimulatedPairing.PIN, zaparoo, clock).auth_token == "simulated"  # noqa: S105


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, "no pairing in progress"),
        (403, "too many failed attempts"),
        (410, "pairing expired"),
    ],
)
def test_a_spent_or_expired_pin_is_said_as_needing_a_new_pin(status, error):
    async def zaparoo(path, body):
        return status, {"error": error}

    with pytest.raises(PairingError) as refused:
        _run(pair(PIN, name=NAME, post=zaparoo))
    assert str(refused.value) == NEW_PIN


def test_a_full_zaparoo_is_said_as_full_not_as_a_spent_pin():
    async def zaparoo(path, body):
        return 403, {"error": "maximum paired clients reached"}

    with pytest.raises(PairingError) as refused:
        _run(pair(PIN, name=NAME, post=zaparoo))
    assert str(refused.value) == FULL


def test_a_wrong_pin_is_said_as_a_wrong_pin():
    with pytest.raises(PairingError, match="did not accept that PIN"):
        _run(pair("111111", name=NAME, post=FakeZaparoo()))


def test_a_server_that_cannot_prove_the_pin_is_never_trusted():
    with pytest.raises(PairingError, match="could not prove"):
        _run(pair(PIN, name=NAME, post=FakeZaparoo(bad_server_hmac=True)))


def test_a_pin_that_is_not_six_digits_is_never_sent():
    zaparoo = FakeZaparoo()
    with pytest.raises(PairingError, match="six digits"):
        _run(pair("12 34", name=NAME, post=zaparoo))
    assert zaparoo.name is None


# -- keeping the pairing -------------------------------------------------------------------


def test_the_pairing_key_is_kept_where_only_the_owner_can_read_it(tmp_path):
    path = tmp_path / PAIRING_FILE
    save_pairing(path, Pairing(auth_token=TOKEN, pairing_key=b"\x42" * 32))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_pairing(path) == Pairing(auth_token=TOKEN, pairing_key=b"\x42" * 32)


def test_a_pairing_file_others_can_read_is_refused(tmp_path):
    path = tmp_path / PAIRING_FILE
    save_pairing(path, Pairing(auth_token=TOKEN, pairing_key=b"\x42" * 32))
    path.chmod(0o644)
    with pytest.raises(PairingError, match="chmod 600"):
        load_pairing(path)


def test_no_pairing_file_means_not_paired(tmp_path):
    assert load_pairing(tmp_path / PAIRING_FILE) is None


def test_the_pairing_key_never_shows_in_its_repr():
    assert "42" not in repr(Pairing(auth_token=TOKEN, pairing_key=b"\x42" * 32)).replace(TOKEN, "")


def test_the_pin_is_typed_by_the_owner_and_never_shown(tmp_path, monkeypatch, capsys):

    settings = tmp_path / "config.toml"
    settings.write_text('[mister]\naddress = "192.0.2.10"\n')
    asked = []

    def hidden(prompt):
        asked.append(prompt)
        return PIN

    monkeypatch.setattr(cli.getpass, "getpass", hidden)
    monkeypatch.setattr(cli, "http_post", lambda address, port: FakeZaparoo())
    monkeypatch.setattr(cli, "FOLDER", tmp_path)
    assert cli.main(["pair", "--settings-file", str(settings)]) == 0
    printed = capsys.readouterr()
    assert asked == [cli.ASK_PIN]
    assert PIN not in printed.out + printed.err
    assert load_pairing(tmp_path / PAIRING_FILE).auth_token == TOKEN


def test_a_pairing_that_fails_saves_nothing(tmp_path, monkeypatch, capsys):

    settings = tmp_path / "config.toml"
    settings.write_text('[mister]\naddress = "192.0.2.10"\n')
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "111111")
    monkeypatch.setattr(cli, "http_post", lambda address, port: FakeZaparoo())
    monkeypatch.setattr(cli, "FOLDER", tmp_path)
    assert cli.main(["pair", "--settings-file", str(settings)]) == 1
    assert "did not accept that PIN" in capsys.readouterr().err
    assert not (tmp_path / PAIRING_FILE).exists()


def test_the_simulated_zaparoo_pairs_only_with_its_own_pin():
    paired = asyncio.run(pair(SimulatedPairing.PIN, name="test", post=SimulatedPairing()))
    assert paired.auth_token == "simulated"  # noqa: S105 - the simulator's own token
    with pytest.raises(PairingError, match="did not accept that PIN"):
        asyncio.run(pair("123456", name="test", post=SimulatedPairing()))


def test_a_simulated_pairing_saves_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "FOLDER", tmp_path)
    assert cli.main(["pair", "--simulate"]) == 0
    assert capsys.readouterr().out.startswith("Simulated: Paired")
    assert list(tmp_path.iterdir()) == []


def test_pairing_without_an_address_says_where_to_set_it(tmp_path, capsys):
    settings = tmp_path / "config.toml"
    settings.write_text("[mister]\n")
    assert cli.main(["pair", "--settings-file", str(settings)]) == 1
    assert "set [mister] address" in capsys.readouterr().err


def test_a_mister_that_does_not_answer_the_pairing_is_said_as_off(tmp_path, monkeypatch, capsys):
    settings = tmp_path / "config.toml"
    settings.write_text('[mister]\naddress = "192.0.2.10"\n')

    async def unreachable(path, body):
        raise ConnectionRefusedError

    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: PIN)
    monkeypatch.setattr(cli, "http_post", lambda address, port: unreachable)
    monkeypatch.setattr(cli, "FOLDER", tmp_path)
    assert cli.main(["pair", "--settings-file", str(settings)]) == 1
    assert "Could not reach Zaparoo at 192.0.2.10" in capsys.readouterr().err
    assert not (tmp_path / PAIRING_FILE).exists()


class _Endpoint(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        status = 200 if self.path == "/api/pair/start" else 410
        reply = json.dumps({"echo": body["name"]} if status == 200 else {"error": "pairing expired"}).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


def test_the_pairing_posts_are_json_and_a_refusal_is_its_status():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Endpoint)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        post = http_post("127.0.0.1", server.server_address[1])
        assert asyncio.run(post("/api/pair/start", {"name": "test"})) == (200, {"echo": "test"})
        assert asyncio.run(post("/api/pair/finish", {"name": "test"})) == (410, {"error": "pairing expired"})
    finally:
        server.shutdown()


@pytest.mark.parametrize("raw", [b"Too Many Requests\n", b"[1]", b""])
def test_a_refusal_body_that_is_not_zaparoos_json_is_read_as_none(raw):
    assert _error_body(raw) == {}


def test_a_damaged_pairing_file_says_to_pair_again(tmp_path):
    kept = tmp_path / PAIRING_FILE
    kept.write_text("not json")
    kept.chmod(0o600)
    with pytest.raises(PairingError, match="damaged"):
        load_pairing(kept)


def test_a_reply_that_is_not_zaparoos_format_is_refused():
    with pytest.raises(PairingError):
        decode(b"not json", role=1)


def test_what_one_side_seals_the_other_opens_once():
    sender = session_cipher(bytes(32), bytes(12), b"aad")
    receiver = session_cipher(bytes(32), bytes(12), b"aad")
    sealed = sender.seal(b"hello")
    assert receiver.open(sealed) == b"hello"
    with pytest.raises(InvalidTag):
        receiver.open(sealed)
