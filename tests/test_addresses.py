# SPDX-License-Identifier: GPL-3.0-or-later
"""The MiSTer is found by its name first, then by the spare addresses in the settings, in order."""

import asyncio

import pytest

from mister_mcp.server import ANSWER_WITHIN
from mister_mcp.service import MisterService
from mister_mcp.settings import load_settings
from mister_mcp.simulator import SimulatedMister
from mister_mcp.zaparoo import (
    FIND_WITHIN,
    READ_WAIT,
    FallbackTransport,
    UnreachableError,
    connect_wait_for,
)

NAME, SPARE, OTHER = "mister.example", "192.0.2.10", "192.0.2.11"


class _Network:
    """Which addresses answer, and in what order they were tried."""

    def __init__(self, **answering):
        self.answering = {key.replace("_", "."): mister for key, mister in answering.items()}
        self.tried: list[str] = []

    def reach(self, address):
        network = self

        class _At:
            async def send(self, request, *, wait):
                network.tried.append(address)
                mister = network.answering.get(address)
                if mister is None:
                    msg = f"{address} does not answer"
                    raise UnreachableError(msg, tried=(address,))
                return await mister.send(request, wait=wait)

        return _At()


def _status(network, addresses):
    return asyncio.run(MisterService(FallbackTransport(addresses, reach=network.reach)).status())


def test_addresses_are_tried_in_the_order_the_settings_give():
    network = _Network(**{"192.0.2.11": SimulatedMister()})
    answer = _status(network, [NAME, SPARE, OTHER])
    assert network.tried == [NAME, SPARE, OTHER]
    assert answer["success"] is True


def test_the_status_says_which_address_answered():
    network = _Network(**{SPARE: SimulatedMister()})
    answer = _status(network, [NAME, SPARE])
    assert answer["address"] == SPARE
    assert SPARE in answer["say"]


def test_the_name_is_used_when_it_answers():
    network = _Network(**{NAME: SimulatedMister()})
    answer = _status(network, [NAME, SPARE])
    assert network.tried == [NAME]
    assert answer["address"] == NAME


def test_the_address_that_answered_is_asked_first_after_that():
    network = _Network(**{SPARE: SimulatedMister()})
    service = MisterService(FallbackTransport([NAME, SPARE], reach=network.reach))
    asyncio.run(service.launch(game="Micro Mages"))
    assert network.tried[:2] == [NAME, SPARE]
    assert set(network.tried[2:]) == {SPARE}


def test_none_answering_names_every_address_tried_and_the_next_step():
    answer = _status(_Network(), [NAME, SPARE])
    assert answer["outcome"] == "unreachable"
    assert answer["on"] is None
    assert answer["say"] == (
        f"Fant ikke MiSTer-en på {NAME} eller {SPARE}. Sjekk at den er på og koblet til nettet. "
        "Har den fått ny adresse, si den til meg."
    )


def test_three_addresses_are_named_with_commas():
    answer = _status(_Network(), [NAME, SPARE, OTHER])
    assert f"på {NAME}, {SPARE} eller {OTHER}." in answer["say"]


def test_a_mister_without_zaparoo_at_the_name_stops_the_search():
    network = _Network(**{NAME: SimulatedMister(zaparoo=False), SPARE: SimulatedMister()})
    answer = _status(network, [NAME, SPARE])
    assert network.tried == [NAME]
    assert answer["on"] is True


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_finding_the_mister_fits_in_the_voices_time(count):
    assert connect_wait_for(count) * count <= FIND_WITHIN
    assert FIND_WITHIN + READ_WAIT + 2.0 <= ANSWER_WITHIN


def test_the_settings_give_the_name_first_then_the_spares(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(f'[mister]\naddress = "{NAME}"\naddresses = ["{SPARE}", "{NAME}", "{OTHER}"]\n')
    assert load_settings(path).where() == [NAME, SPARE, OTHER]


def test_spares_alone_are_enough(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(f'[mister]\naddresses = ["{SPARE}"]\n')
    assert load_settings(path).where() == [SPARE]
