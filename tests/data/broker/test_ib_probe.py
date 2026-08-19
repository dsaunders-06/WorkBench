"""The read-only IBKR capability probe (Task 1 of the IBKR move plan).

W1.1's whole argument is that the four missing optional capabilities fail
SILENTLY: every caller guards with `getattr`, so a missing method neither
crashes nor corrupts - it just stops verifying, absorbing and detecting. The
measurement therefore has to record the RESPONSE ITSELF, and it has to
distinguish four outcomes that a summary would collapse into one:

    absent  the client has no such method at all
    raised  it exists and blew up - and WHAT it raised is the evidence
    empty   it answered, with nothing
    data    it answered, with something, and the shape is the finding

`scripts/broker_capabilities.py` cannot do any of this. It inspects classes
with `hasattr` and connects to nothing, so it prints the same table on the day
the account goes live as it printed the day before. These tests are against
the thing that actually asks a Gateway.

Two properties here are safety, not reporting. The probe must place, cancel
and modify nothing - Stage 1 allows exactly one write and it is operator-
approved and separate. And one call raising must not abort the others: a
Gateway session is not cheap to arrange, and a measurement that stops at the
first exception wastes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.ib_adapter import LivePortInPaperModeError
from qat.data.broker.ib_probe import (
    ANNOUNCEMENTS,
    Observation,
    connection_target,
    observed_perm_ids,
    probe,
    render,
)


def _trade(perm_id: int, symbol: str = "BHP", order_type: str = "STP") -> Trade:
    from ib_async import Contract

    order = IBOrder(orderId=1, action="SELL", totalQuantity=10, orderType=order_type)
    order.permId = perm_id
    return Trade(
        contract=Contract(symbol=symbol, secType="STK", exchange="ASX"),
        order=order,
        orderStatus=OrderStatus(status="Submitted", permId=perm_id),
    )


class FakeIB:
    """A Gateway that answers however the test needs it to.

    Anything not passed is answered with an empty list. `placeOrder`,
    `cancelOrder` and `modifyOrder` exist only to fail loudly - the probe must
    never reach them.
    """

    def __init__(self, absent: tuple[str, ...] = (), **responses: Any) -> None:
        self._absent = set(absent)
        self._responses = responses
        self.wrote = False

    def __getattribute__(self, name: str) -> Any:
        # Genuinely missing, not merely answering None: a subclass that
        # `del`s an inherited method still inherits it, which would have made
        # the absent case pass for the wrong reason.
        try:
            absent = object.__getattribute__(self, "_absent")
        except AttributeError:
            absent = set()
        if name in absent:
            raise AttributeError(name)
        return object.__getattribute__(self, name)

    def _answer(self, name: str) -> Any:
        value = self._responses.get(name, [])
        if isinstance(value, Exception):
            raise value
        return value

    def isConnected(self) -> bool:
        return True

    def managedAccounts(self) -> list[str]:
        return self._answer("managedAccounts") or ["DU1234567"]

    def fills(self) -> Any:
        return self._answer("fills")

    def reqExecutions(self, execFilter: Any = None) -> Any:
        return self._answer("reqExecutions")

    def openTrades(self) -> Any:
        return self._answer("openTrades")

    def reqAllOpenOrders(self) -> Any:
        return self._answer("reqAllOpenOrders")

    def positions(self, account: str = "") -> Any:
        return self._answer("positions")

    def placeOrder(self, *args: Any, **kwargs: Any) -> None:
        self.wrote = True
        raise AssertionError("the probe placed an order - it is read-only")

    def cancelOrder(self, *args: Any, **kwargs: Any) -> None:
        self.wrote = True
        raise AssertionError("the probe cancelled an order - it is read-only")

    def modifyOrder(self, *args: Any, **kwargs: Any) -> None:
        self.wrote = True
        raise AssertionError("the probe modified an order - it is read-only")


def _by_call(observations: list[Observation], call: str) -> Observation:
    matches = [o for o in observations if o.call == call]
    assert matches, f"nothing probed {call}; probed {[o.call for o in observations]}"
    return matches[0]


@pytest.mark.asyncio
async def test_a_method_the_client_does_not_have_is_recorded_as_absent() -> None:
    """The silent absence is the entire subject of the measurement. A probe
    that skipped a missing method would reproduce the very failure W1.1 exists
    to expose."""

    client = FakeIB(absent=("fills",))
    assert not hasattr(client, "fills")

    observations = await probe(client)

    assert _by_call(observations, "IB.fills()").outcome == "absent"


@pytest.mark.asyncio
async def test_a_call_that_raises_is_recorded_with_what_it_raised() -> None:
    client = FakeIB(reqExecutions=RuntimeError("no market data permissions"))

    observation = _by_call(await probe(client), "IB.reqExecutions()")

    assert observation.outcome == "raised"
    assert "no market data permissions" in observation.raw
    assert "RuntimeError" in observation.raw


@pytest.mark.asyncio
async def test_one_call_raising_does_not_stop_the_others() -> None:
    """A Gateway session is arranged, not summoned. A measurement that aborts
    on the first exception spends the session and returns one line."""
    client = FakeIB(fills=RuntimeError("boom"), openTrades=[_trade(perm_id=101)])

    observations = await probe(client)

    assert _by_call(observations, "IB.fills()").outcome == "raised"
    assert _by_call(observations, "IB.openTrades()").outcome == "data"


@pytest.mark.asyncio
async def test_an_empty_answer_is_not_recorded_as_data() -> None:
    """'Returned empty' and 'returned nothing because it is not implemented'
    are different findings and the report has to tell them apart."""
    client = FakeIB(fills=[], openTrades=[_trade(perm_id=7)])

    observations = await probe(client)

    assert _by_call(observations, "IB.fills()").outcome == "empty"
    assert _by_call(observations, "IB.openTrades()").outcome == "data"


@pytest.mark.asyncio
async def test_the_raw_response_is_captured_not_summarised() -> None:
    """Step 3 of Task 1: put the raw response in the report. The spec's whole
    argument is that the absence is silent, so the evidence has to be the
    response itself rather than a count of it."""
    client = FakeIB(openTrades=[_trade(perm_id=42, symbol="CBA")])

    observation = _by_call(await probe(client), "IB.openTrades()")

    assert "CBA" in observation.raw
    assert "42" in observation.raw
    assert observation.count == 1


@pytest.mark.asyncio
async def test_an_awaitable_response_is_awaited() -> None:
    """ib_async exposes both `reqExecutions` and `reqExecutionsAsync`, and a
    coroutine captured with `repr` would record the object rather than the
    answer - a probe that measured nothing while looking like it had."""

    class AsyncIB(FakeIB):
        async def reqExecutions(self, execFilter: Any = None) -> Any:  # type: ignore[override]
            return [_trade(perm_id=9)]

    observation = _by_call(await probe(AsyncIB()), "IB.reqExecutions()")

    assert observation.outcome == "data"
    assert "coroutine" not in observation.raw


@pytest.mark.asyncio
async def test_perm_ids_are_collected_for_the_restart_comparison() -> None:
    """Task 3 chose permId as the order identity BECAUSE orderId is
    per-session, and recorded that permId surviving a Gateway restart was
    assumed and unmeasured. The comparison is: note them, restart, look
    again."""
    client = FakeIB(openTrades=[_trade(perm_id=1234), _trade(perm_id=5678)])

    assert observed_perm_ids(await probe(client)) == [1234, 5678]


@pytest.mark.asyncio
async def test_announcements_is_recorded_as_having_no_equivalent_to_call() -> None:
    """Measured 19 August: reqFundamentalData is XML reports and
    reqHistoricalNews is unstructured text. The finding is the absence, and it
    belongs in the report as a recorded decision rather than as a gap the
    reader has to notice is missing."""
    observations = await probe(FakeIB())

    announcements = _by_call(observations, ANNOUNCEMENTS)
    assert announcements.outcome == "absent"
    assert "no structured" in announcements.raw.lower()


@pytest.mark.asyncio
async def test_the_probe_never_writes() -> None:
    """The only write in Stage 1 is one operator-approved stop, placed by
    hand. This asserts the probe is not it."""
    client = FakeIB(openTrades=[_trade(perm_id=1)], fills=[])

    await probe(client)

    assert client.wrote is False


@pytest.mark.asyncio
async def test_the_report_carries_every_raw_response_verbatim() -> None:
    client = FakeIB(openTrades=[_trade(perm_id=99, symbol="RIO")])

    report = render(await probe(client), account="DU1234567")

    assert "RIO" in report
    assert "IB.openTrades()" in report
    assert "DU1234567" in report


def test_a_live_port_is_refused_in_paper_mode() -> None:
    """The probe connects on its own rather than through IBAdapter, so it does
    not inherit W1.4's guard - it has to carry it. A measurement script is
    exactly the kind of thing run in a hurry against whatever Gateway happens
    to be open."""
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=4001)

    with pytest.raises(LivePortInPaperModeError):
        connection_target(settings)


def test_a_paper_port_is_accepted_in_paper_mode() -> None:
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=4002)

    host, port, client_id = connection_target(settings)

    assert port == 4002
    assert client_id != settings.ibkr_client_id, (
        "the probe must not collide with the app's own connection - IBKR "
        "silently disconnects the earlier client on a duplicate clientId"
    )


def test_a_live_account_number_is_refused() -> None:
    """Paper accounts are prefixed DU. If managedAccounts() answers with a
    live account the Gateway is the wrong session, and the next thing the
    operator does is place a stop."""
    from qat.data.broker.ib_probe import check_paper_account

    with pytest.raises(LivePortInPaperModeError):
        check_paper_account(["U1234567"])

    check_paper_account(["DU1234567"])


def test_the_timestamp_is_recorded_so_two_runs_can_be_compared() -> None:
    observation = Observation(question="q", call="IB.fills()", outcome="empty", raw="[]", count=0)
    report = render([observation], account="DU1", now=datetime(2026, 8, 19, 4, 0, tzinfo=UTC))

    assert "2026-08-19" in report


async def test_the_async_variant_is_preferred_when_the_client_has_one() -> None:
    """ib_async's sync `reqExecutions`/`reqAllOpenOrders` are wrappers that
    call `IB._run(...)`, which raises when there is already a running event
    loop - and the probe runs inside `asyncio.run`. Calling the sync form
    would record OUR nested-loop bug as an IBKR finding: a "raised" outcome in
    the report that says nothing about the broker, on a Gateway session that
    is not cheap to arrange twice.
    """

    class BothForms(FakeIB):
        def reqExecutions(self, execFilter: Any = None) -> Any:  # type: ignore[override]
            raise RuntimeError("This event loop is already running")

        async def reqExecutionsAsync(self, execFilter: Any = None) -> Any:
            return [_trade(perm_id=555)]

        def reqAllOpenOrders(self) -> Any:  # type: ignore[override]
            raise RuntimeError("This event loop is already running")

        async def reqAllOpenOrdersAsync(self) -> Any:
            return [_trade(perm_id=556)]

    observations = await probe(BothForms())

    executions = _by_call(observations, "IB.reqExecutions()")
    assert executions.outcome == "data", executions.raw
    assert "555" in executions.raw
    assert _by_call(observations, "IB.reqAllOpenOrders()").outcome == "data"


async def test_the_sync_form_is_used_when_there_is_no_async_variant() -> None:
    """`fills()`, `openTrades()`, `positions()` and `managedAccounts()` are
    plain accessors over ib_async's local state - no network, no `_run`, and
    no async twin. Preferring an async variant must not mean skipping them."""
    observations = await probe(FakeIB(fills=[_trade(perm_id=1)]))

    assert _by_call(observations, "IB.fills()").outcome == "data"
