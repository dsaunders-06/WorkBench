"""M105: "Test Broker Connection" returned a tick without testing anything.

    def _check_broker(self, broker):
        if broker != "alpaca":
            return True, f"{label} needs no connection test"

**It was true when written.** Alpaca was the only broker reachable over a
network; the others were `mock` and `simulated`, which run in-process and
genuinely need no connection test. The sentence was accurate for every broker
it could apply to.

**IBKR broke that assumption and nothing noticed.** It is a real broker over a
socket, and it is the one where "is the Gateway up?" is the most likely thing
to be wrong - yet the button returned a GREEN TICK having checked nothing. A
check that cannot fail, in the control whose entire purpose is to fail when the
broker is unreachable.

Found by the operator clicking it 47 minutes before the first ASX session.

The distinction the fix keeps: `mock` needs no connection and says so, because
that IS true and pretending otherwise would be the opposite lie.
"""

from __future__ import annotations

from typing import Any

from qat.presentation.settings import check_broker_connection


class _IB:
    def __init__(self, connected: bool = True, accounts: list[str] | None = None) -> None:
        self._connected = connected
        self._accounts = accounts if accounts is not None else ["DUQ200898"]
        self.disconnected = False

    def isConnected(self) -> bool:
        return self._connected

    def connect(
        self, host: str, port: int, clientId: int, readonly: bool = False, **kw: Any
    ) -> None:
        if not self._connected:
            raise ConnectionRefusedError("cannot connect to 127.0.0.1:4002")

    def managedAccounts(self) -> list[str]:
        return list(self._accounts)

    def disconnect(self) -> None:
        self.disconnected = True


def _settings(**overrides: Any) -> Any:
    from qat.config import Settings

    fields: dict[str, Any] = {
        "_env_file": None,
        "broker": "ibkr",
        "trading_mode": "paper",
        "market": "ASX",
        "ibkr_port": 4002,
    }
    fields.update(overrides)
    return Settings(**fields)


def test_a_reachable_gateway_reports_the_account() -> None:
    ok, message = check_broker_connection("ibkr", _settings(), ib_client=_IB())

    assert ok is True
    assert "DUQ200898" in message


def test_an_unreachable_gateway_is_a_FAILURE_not_a_tick() -> None:
    """The whole defect. A broker that cannot be reached must not return the
    same green tick as one that answered."""
    ok, message = check_broker_connection("ibkr", _settings(), ib_client=_IB(connected=False))

    assert ok is False, "an unreachable Gateway reported success"
    assert "Gateway" in message or "connect" in message.lower()


def test_a_live_account_number_is_reported_as_a_failure() -> None:
    """Paper accounts are prefixed DU. A live account behind a paper
    configuration is the mismatch W1.4 exists for, and the Settings screen is
    exactly where somebody would look to confirm which account they are on."""
    ok, message = check_broker_connection("ibkr", _settings(), ib_client=_IB(accounts=["U1234567"]))

    assert ok is False
    assert "U1234567" in message


def test_the_connection_is_always_closed() -> None:
    """A test button that leaks a connection would eventually take the
    clientId the application itself needs."""
    client = _IB()

    check_broker_connection("ibkr", _settings(), ib_client=client)

    assert client.disconnected


def test_the_probe_uses_a_client_id_that_cannot_collide_with_the_app() -> None:
    """IBKR does not multiplex a clientId - a second connection using one
    already in use silently displaces the first. A test button that knocked the
    running application off its Gateway would be worse than no button."""
    seen: dict[str, Any] = {}

    class _Recording(_IB):
        def connect(self, host: str, port: int, clientId: int, **kw: Any) -> None:
            seen["clientId"] = clientId
            seen["readonly"] = kw.get("readonly")

    settings = _settings(ibkr_client_id=1)
    check_broker_connection("ibkr", settings, ib_client=_Recording())

    assert seen["clientId"] != settings.ibkr_client_id
    assert seen["readonly"] is True, "the test button must not open a writable session"


def test_a_simulated_broker_still_needs_no_connection() -> None:
    """The original sentence was TRUE for the brokers it was written for, and
    stays. Claiming an in-process broker had been 'connected to' would be the
    same class of lie pointing the other way."""
    ok, message = check_broker_connection("mock", _settings(broker="mock"))

    assert ok is True
    assert "no connection" in message.lower()
