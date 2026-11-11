# SPDX-License-Identifier: GPL-3.0-or-later
"""Talking to a secured Zaparoo over its encrypted WebSocket (ADR-MM-005).

A pretend Zaparoo runs on localhost here, speaking the frames Core's
docs/api/encryption.md describes, with session keys derived the same way.
"""

import asyncio
import base64
import json

import pytest
import websockets

from mister_mcp import cli
from mister_mcp.pairing import (
    PAIRING_FILE,
    EncryptedSession,
    Pairing,
    PairingError,
    save_pairing,
    session_cipher,
    session_keys,
)
from mister_mcp.service import PAIR_NEEDED, MisterService
from mister_mcp.zaparoo import (
    FallbackTransport,
    WebSocketTransport,
    Zaparoo,
    ZaparooNeedsPairingError,
)

TOKEN = "test-auth-token"  # noqa: S105 - a made-up token for the tests
KEY = b"\x42" * 32
PAIRED = Pairing(auth_token=TOKEN, pairing_key=KEY)
NEEDS_ENCRYPTION = {"jsonrpc": "2.0", "id": None, "error": {"code": -32002, "message": "encryption required"}}


def _secured(seen):
    """A secured Zaparoo: answers an encrypted media.active, refuses anything plaintext."""

    async def handler(socket):
        first = json.loads(await socket.recv())
        seen.append(first)
        if "e" not in first:
            await socket.send(json.dumps(NEEDS_ENCRYPTION))
            return
        assert (first["v"], first["t"]) == (1, TOKEN)
        c2s_key, s2c_key, c2s_base, s2c_base = session_keys(KEY, base64.b64decode(first["s"]))
        aad = f"{first['t']}:ws".encode()
        inbound, outbound = session_cipher(c2s_key, c2s_base, aad), session_cipher(s2c_key, s2c_base, aad)
        request = json.loads(inbound.open(base64.b64decode(first["e"])))
        note = {"jsonrpc": "2.0", "method": "media.started", "params": {}}
        await socket.send(
            json.dumps({"e": base64.b64encode(outbound.seal(json.dumps(note).encode())).decode()})
        )
        answer = {"jsonrpc": "2.0", "id": request["id"], "result": None}
        await socket.send(
            json.dumps({"e": base64.b64encode(outbound.seal(json.dumps(answer).encode())).decode()})
        )

    return handler


def _with_server(seen, scenario):
    async def run():
        async with websockets.serve(_secured(seen), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            return await scenario(port)

    return asyncio.run(run())


def test_a_paired_client_asks_and_hears_through_the_encryption():
    seen = []

    async def scenario(port):
        transport = WebSocketTransport("127.0.0.1", port=port, framing=lambda: EncryptedSession(PAIRED))
        return await Zaparoo(transport).active()

    assert _with_server(seen, scenario) is None
    assert set(seen[0]) == {"v", "e", "t", "s"}
    assert "media.active" not in json.dumps(seen[0])


def test_each_connection_has_its_own_salt():
    one, other = EncryptedSession(PAIRED), EncryptedSession(PAIRED)
    assert json.loads(one.first("{}"))["s"] != json.loads(other.first("{}"))["s"]


def test_a_refused_login_is_said_as_needing_pairing():
    seen = []

    async def scenario(port):
        try:
            await Zaparoo(WebSocketTransport("127.0.0.1", port=port)).active()
        except ZaparooNeedsPairingError as error:
            return error
        return None

    assert isinstance(_with_server(seen, scenario), ZaparooNeedsPairingError)


def test_a_refused_login_names_the_pair_command():
    seen = []

    async def scenario(port):
        transport = FallbackTransport(
            ["127.0.0.1"], reach=lambda address: WebSocketTransport(address, port=port)
        )
        return await MisterService(transport).status()

    answer = _with_server(seen, scenario)
    assert answer["say"] == PAIR_NEEDED
    assert "uv run --directory ~/mister-mcp mister-mcp pair" in PAIR_NEEDED
    assert "Fant ikke" not in answer["say"]


def test_a_frame_that_does_not_decrypt_is_never_believed():
    session = EncryptedSession(PAIRED)
    session.first("{}")
    forged = json.dumps({"e": base64.b64encode(b"\x00" * 40).decode()})
    with pytest.raises(PairingError):
        session.read(forged)


def test_the_kept_pairing_is_what_the_plugin_connects_with(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "FOLDER", tmp_path)
    assert cli.framing_from_pairing() is None
    save_pairing(tmp_path / PAIRING_FILE, PAIRED)
    framing = cli.framing_from_pairing()
    assert json.loads(framing().first("{}"))["t"] == TOKEN
