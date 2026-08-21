"""M125: a Gateway that is running is not a Gateway that is listening.

21 August, 08:53, four minutes before the ASX open. The Gateway process was up
but nobody had logged into it, so port 4002 was closed. `connectAsync` raised
ConnectionRefusedError, the application shut down, and the operator restarted
it. Two separate defects made that a full restart rather than a pause:

* **`connect()` had no retry**, while `_reconnect_with_backoff` already existed
  for the heartbeat. A connection LOST at 14:17 mid-session recovered by itself
  that same day; a connection not yet ESTABLISHED at startup did not try twice.
* **the pre-flight checked the process**, which cannot distinguish "up and
  logged in" from "up and refusing every connection" - quiet looking like
  healthy, in a new place.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus
from qat.preflight import KNOWN_IBKR_PORTS, Status, gateway_port_check


class _RefusingClient:
    """Refuses the first `refusals` attempts, then connects."""

    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.attempts = 0
        self.connected = False

    async def connectAsync(self, host, port, client_id, readonly=False):  # noqa: N802
        self.attempts += 1
        if self.attempts <= self.refusals:
            raise ConnectionRefusedError(22, "The remote computer refused the network connection")
        self.connected = True

    def isConnected(self) -> bool:  # noqa: N802
        return self.connected

    def disconnect(self) -> None:
        self.connected = False


def _adapter(client, **kwargs) -> IBAdapter:
    return IBAdapter(
        client,
        EventBus(),
        settings=Settings(_env_file=None, trading_mode="paper"),
        initial_backoff_seconds=0.0,
        max_backoff_seconds=0.0,
        **kwargs,
    )


# --- the connect retry --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gateway_thirty_seconds_late_no_longer_costs_a_restart(caplog) -> None:
    client = _RefusingClient(refusals=3)
    adapter = _adapter(client)

    with caplog.at_level(logging.INFO, logger="qat.data.broker.ib_adapter"):
        await adapter.connect()

    assert client.connected
    assert client.attempts == 4
    await adapter.disconnect()
    assert any("retrying" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_the_retry_is_bounded_and_raises_the_real_reason(caplog) -> None:
    """Not infinite. Past the bound something is wrong that waiting will not
    fix, and the ORIGINAL exception is what tells the operator which."""
    client = _RefusingClient(refusals=99)
    adapter = _adapter(client, max_connect_attempts=3)

    with caplog.at_level(logging.ERROR, logger="qat.data.broker.ib_adapter"):
        with pytest.raises(ConnectionRefusedError):
            await adapter.connect()

    assert client.attempts == 3
    assert any("logged in" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_a_first_attempt_that_works_does_not_wait(caplog) -> None:
    """The ordinary case must be unchanged - no delay, no retry noise."""
    client = _RefusingClient(refusals=0)
    adapter = _adapter(client)

    with caplog.at_level(logging.WARNING, logger="qat.data.broker.ib_adapter"):
        await adapter.connect()

    assert client.attempts == 1
    await adapter.disconnect()
    assert not [r for r in caplog.records if "retrying" in r.getMessage()]


@pytest.mark.asyncio
async def test_the_heartbeat_starts_only_after_a_successful_connect() -> None:
    """A heartbeat against a connection that never opened would reconnect in a
    loop and hide the failure."""
    client = _RefusingClient(refusals=99)
    adapter = _adapter(client, max_connect_attempts=2)

    with pytest.raises(ConnectionRefusedError):
        await adapter.connect()

    assert adapter._heartbeat_task is None
    await asyncio.sleep(0)


# --- the pre-flight port probe ------------------------------------------------


def test_a_closed_configured_port_fails_the_preflight() -> None:
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=4002)

    check = gateway_port_check(settings, probe=lambda host, port: False)

    assert check.status is Status.FAIL
    assert "NOT listening" in check.detail
    assert "not logged in" in check.detail


def test_an_open_configured_port_passes() -> None:
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=4002)

    check = gateway_port_check(settings, probe=lambda host, port: port == 4002)

    assert check.status is Status.OK
    assert "4002" in check.detail


def test_it_names_which_of_the_four_it_found() -> None:
    """ "The Gateway is not up" and "the Gateway is up, but it is the OTHER one"
    are indistinguishable from the configured port alone."""
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=4002)

    check = gateway_port_check(settings, probe=lambda host, port: port == 7497)

    assert check.status is Status.FAIL
    assert "7497 (paper TWS)" in check.detail
    assert "4002 (paper Gateway)" in check.detail


def test_nothing_listening_says_so_plainly() -> None:
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=4002)

    check = gateway_port_check(settings, probe=lambda host, port: False)

    assert "none of the four" in check.detail


def test_all_four_sockets_are_named() -> None:
    assert KNOWN_IBKR_PORTS == {
        4001: "live Gateway",
        4002: "paper Gateway",
        7496: "live TWS",
        7497: "paper TWS",
    }
