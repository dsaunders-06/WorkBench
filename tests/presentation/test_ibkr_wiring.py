"""M101: wiring IBAdapter into the running application.

Stage 1 built and live-verified the adapter - entries with protection
attached, fills, the protection scan, order resolution - and **none of it was
reachable by the app**, because `resolve_broker` raised for `broker=ibkr`. Every
one of those capabilities has only ever been exercised by a script.

Two things had to be true before this could be wired, and both now are:

* **The adapter implements what the app needs.** `broker_capabilities.py`
  reports 11 of 12; the only gap is `announcements`, and the refusal used to
  cite exactly that.
* **The gap is a DECISION rather than an omission.** Task 5 chose option 1 -
  accept it, report it as UNAVAILABLE. Continuing to refuse construction over
  a capability the operator has deliberately accepted would contradict the
  decision, so this constructs and logs instead.

**Connection is a lifecycle concern, not a construction one.** `IBAdapter`
needs an `await connect()` that also starts the heartbeat and the
reconnect-with-backoff loop, and `resolve_broker` is synchronous. So the
connection is an `Engine` - registered FIRST, so the socket is up before any
engine that might place an order, and stopped LAST because `stop_all` reverses.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter, LivePortInPaperModeError
from qat.domain.bus import EventBus
from qat.presentation.runtime import (
    BrokerConnection,
    BrokerNotAvailableError,
    resolve_broker,
)


class FakeIB:
    """Enough of ib_async.IB to be constructed and connected."""

    def __init__(self) -> None:
        self.connected = False
        self.connect_args: dict[str, Any] = {}
        self.disconnected = False

    def isConnected(self) -> bool:
        return self.connected

    async def connectAsync(
        self, host: str, port: int, clientId: int, timeout: float = 4.0, readonly: bool = False
    ) -> None:
        self.connected = True
        self.connect_args = {
            "host": host,
            "port": port,
            "clientId": clientId,
            "readonly": readonly,
        }

    def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


def _paper(**overrides: Any) -> Settings:
    fields: dict[str, Any] = {
        "_env_file": None,
        "broker": "ibkr",
        "trading_mode": "paper",
        "market": "ASX",
        "ibkr_port": 4002,
    }
    fields.update(overrides)
    return Settings(**fields)


def test_ibkr_now_resolves_to_a_real_adapter() -> None:
    """The blocker. Everything Stage 1 built was unreachable by the app."""
    broker = resolve_broker(_paper(), bus=EventBus(), ib_client=FakeIB())

    assert isinstance(broker, IBAdapter)


def test_it_never_silently_becomes_a_mock() -> None:
    """The original refusal's whole point, and it survives: quietly paper-trading
    against a simulator while believing the destination broker is connected
    would be worse than failing to start."""
    from qat.data.broker.mock_broker import MockBroker

    broker = resolve_broker(_paper(), bus=EventBus(), ib_client=FakeIB())

    assert not isinstance(broker, MockBroker)


def test_it_refuses_without_the_event_bus() -> None:
    """`IBAdapter` publishes a KillSwitchEvent when reconnection is exhausted.
    Built against a private bus, that event would halt nothing - the adapter
    would look connected and the account would be unprotected against a
    connection it had given up on."""
    with pytest.raises(BrokerNotAvailableError, match="bus|EventBus"):
        resolve_broker(_paper(), bus=None, ib_client=FakeIB())


def test_a_live_port_in_paper_mode_still_refuses() -> None:
    """W1.4's guard reaches the wiring, not just the adapter."""
    with pytest.raises(LivePortInPaperModeError):
        resolve_broker(_paper(ibkr_port=4001), bus=EventBus(), ib_client=FakeIB())


def test_live_mode_refuses_to_construct_without_confirmation() -> None:
    """`live_trading_confirmed` is never passed True from here. Only the in-app
    confirmation dialog may set it, and it is not wired - so this path cannot
    reach a live account by configuration alone."""
    from qat.data.broker.ib_adapter import LiveTradingNotConfirmedError

    with pytest.raises(LiveTradingNotConfirmedError):
        resolve_broker(
            _paper(trading_mode="live", ibkr_port=4002), bus=EventBus(), ib_client=FakeIB()
        )


def test_the_accepted_announcements_gap_is_logged_not_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The refusal used to cite the missing capabilities. Task 5 accepted the
    only one left, so refusing over it would contradict a decision the operator
    took - it is stated instead."""
    with caplog.at_level(logging.WARNING):
        resolve_broker(_paper(), bus=EventBus(), ib_client=FakeIB())

    assert any("announcements" in r.message for r in caplog.records), [
        r.message for r in caplog.records
    ]


# --- the connection lifecycle ---------------------------------------------


async def test_the_connection_engine_connects_on_start() -> None:
    client = FakeIB()
    adapter = resolve_broker(_paper(), bus=EventBus(), ib_client=client)

    await BrokerConnection(adapter).start()

    assert client.connected
    assert client.connect_args["port"] == 4002


async def test_it_disconnects_on_stop() -> None:
    client = FakeIB()
    adapter = resolve_broker(_paper(), bus=EventBus(), ib_client=client)
    connection = BrokerConnection(adapter)
    await connection.start()

    await connection.stop()

    assert client.disconnected


async def test_a_broker_that_needs_no_connection_is_a_no_op() -> None:
    """MockBroker and Alpaca have no connect step. The engine has to tolerate
    them rather than the caller having to know which is which."""

    class _NoConnect:
        name = "no-connect"

    connection = BrokerConnection(_NoConnect())
    await connection.start()
    await connection.stop()


def test_the_engine_satisfies_the_orchestrator_protocol() -> None:
    connection = BrokerConnection(resolve_broker(_paper(), bus=EventBus(), ib_client=FakeIB()))

    assert isinstance(connection.name, str) and connection.name
    assert callable(connection.start) and callable(connection.stop)


# --- registration in the runtime ------------------------------------------


def test_the_runtime_registers_the_connection_first() -> None:
    """Order is the safety property. The socket must be up before any engine
    that could place an order, and - because `stop_all` reverses - the broker
    must be the LAST thing disconnected. A broker torn down while the bridge is
    still running turns every order into an error rather than a refusal.
    """
    from qat.presentation.runtime import Runtime

    runtime = Runtime.build_demo(settings=Settings(_env_file=None, trading_mode="paper"))
    engines = runtime.orchestrator._engines

    assert engines, "no engines registered at all"
    assert isinstance(engines[0], BrokerConnection), [type(e).__name__ for e in engines]


def test_the_runtime_builds_with_an_ibkr_broker_without_connecting() -> None:
    """Construction must not open a socket - the app has to be buildable with
    no Gateway running, or a test suite and a first launch both fail on
    something that is only needed at start."""
    from qat.presentation.runtime import Runtime

    client = FakeIB()
    broker = resolve_broker(_paper(), bus=EventBus(), ib_client=client)
    runtime = Runtime.build_demo(settings=_paper(), broker=broker)

    assert runtime.broker is broker
    assert not client.connected, "building the runtime opened a broker connection"


def test_the_default_client_is_a_real_ib_and_is_not_connected() -> None:
    """The path production actually takes, and every other test here bypasses
    it by injecting a fake. A mutation run made that visible: breaking the
    default-client branch changed nothing, because nothing exercised it.

    `ib_async.IB()` opens no socket at construction, so this is safe with no
    Gateway running - which is also the property being asserted. If building
    the adapter ever started connecting, the app would fail to start whenever
    the Gateway was down instead of retrying through the heartbeat.
    """
    from ib_async import IB

    broker = resolve_broker(_paper(), bus=EventBus())

    assert isinstance(broker.ib_client, IB)
    assert not broker.ib_client.isConnected()


def test_the_runtime_builds_on_ibkr_without_being_handed_a_broker() -> None:
    """The path a real launch takes, and the one the live check broke on.

    `test_the_runtime_builds_with_an_ibkr_broker_without_connecting` passes a
    pre-built adapter, which injected straight around the defect:
    `build_demo` called `resolve_broker(settings)` with no bus, so the app
    itself could not construct the very broker this milestone wired in. The
    test agreed with the code because it never asked the code to do the part
    that was missing.
    """
    from qat.presentation.runtime import Runtime

    runtime = Runtime.build_demo(settings=_paper())

    assert isinstance(runtime.broker, IBAdapter)
    assert runtime.broker.bus is runtime.bus, (
        "the adapter was built against a different bus than the application "
        "runs on - its KillSwitchEvent would halt nothing"
    )
