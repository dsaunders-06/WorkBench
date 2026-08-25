"""The sector concentration rail must actually RECEIVE data (item 44).

On 25 August the live book finished 60% Financials against a configured 30%
cap, and the rail never spoke. It had not failed to bind - it was never given
anything to bind on. `signal_bridge` called `submit_order` with four positional
arguments, so `sector_by_symbol` defaulted to `None`, and nothing anywhere set
`OrderCandidate.sector`. BOTH are required by `governor.py`:

    if candidate_sector and sector_by_symbol:

so supplying either one alone leaves the rail dark while looking wired.

`risk_decisions.csv` recorded `held_in_sector_dollars: 0.0` and
`sector_pct: null` on all nine buys that day - the evidence existed from the
first trade this system ever placed, and nothing read it.

The tests below pin the WIRING. A rail's own unit tests can pass forever while
the production call site never reaches it, which is exactly what happened here,
and had happened once before at the SAME call site with `existing_returns`.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.data.sectors import SECTOR_BY_SYMBOL
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, SignalEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

# A real, mapped ASX symbol. "AAA" - the other bridge tests' fixture - is
# deliberately NOT used: it is absent from SECTOR_BY_SYMBOL, so a test built on
# it would pass with the rail still dark.
_SYMBOL = "ANZ.AX"


def _build() -> tuple[SignalToOrderBridge, OMS]:
    settings = Settings(  # type: ignore[arg-type]
        _env_file=None, data_dir=tempfile.mkdtemp(), market="ASX", apply_costs_in_paper=False
    )
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(MockBroker(seed=1), risk_engine, switch, max_order_pct_of_cash=1.0)
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    return bridge, oms


async def _feed_bars(bridge: SignalToOrderBridge, n: int = 30) -> None:
    start = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
    for step in range(n):
        await bridge._on_market_data(
            MarketDataEvent(
                symbol=_SYMBOL,
                price=100.0 + step * 0.5,
                volume=1000,
                ts=start + timedelta(seconds=step * 60),
            )
        )


@pytest.mark.asyncio
async def test_the_live_path_hands_the_governor_its_sector_data():
    """THE regression for item 44. Both halves, because either alone is inert."""
    bridge, oms = _build()
    await _feed_bars(bridge)

    seen: dict[str, object] = {}
    original = oms.submit_order

    async def _spy(candidate, equity, existing_weights, existing_returns, sector_by_symbol=None):
        seen["candidate_sector"] = candidate.sector
        seen["sector_by_symbol"] = sector_by_symbol
        return await original(
            candidate, equity, existing_weights, existing_returns, sector_by_symbol
        )

    oms.submit_order = _spy  # type: ignore[assignment]
    await bridge._on_signal(
        SignalEvent(symbol=_SYMBOL, side="buy", conviction=1.0, strategy="test")  # type: ignore[arg-type]
    )

    assert seen, "the bridge never reached submit_order - the test proves nothing"
    assert seen["candidate_sector"] == "Financials", (
        "OrderCandidate.sector was not populated; governor.py requires BOTH "
        "candidate_sector and sector_by_symbol, so the rail stays dark"
    )
    mapping = seen["sector_by_symbol"]
    assert mapping, "sector_by_symbol was not passed - this is item 44 exactly"
    assert mapping.get("ANZ.AX") == "Financials"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_an_unmapped_symbol_gets_no_sector_rather_than_a_shared_unknown():
    """`sector_for()` returns "Unknown" for anything unmapped, which would put
    every unmapped symbol in ONE bucket and have them constrain each other as
    though they were a sector. That invents a relationship rather than
    measuring one, so the live path uses the map directly and leaves an
    unmapped candidate with no sector at all - the rail simply does not apply.
    """
    assert "ZZZZ.AX" not in SECTOR_BY_SYMBOL

    bridge, oms = _build()
    start = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
    for step in range(30):
        await bridge._on_market_data(
            MarketDataEvent(
                symbol="ZZZZ.AX",
                price=100.0 + step * 0.5,
                volume=1000,
                ts=start + timedelta(seconds=step * 60),
            )
        )

    seen: dict[str, object] = {}
    original = oms.submit_order

    async def _spy(candidate, equity, existing_weights, existing_returns, sector_by_symbol=None):
        seen["candidate_sector"] = candidate.sector
        return await original(
            candidate, equity, existing_weights, existing_returns, sector_by_symbol
        )

    oms.submit_order = _spy  # type: ignore[assignment]
    await bridge._on_signal(
        SignalEvent(symbol="ZZZZ.AX", side="buy", conviction=1.0, strategy="test")  # type: ignore[arg-type]
    )

    assert seen, "the bridge never reached submit_order"
    assert seen["candidate_sector"] is None, (
        "an unmapped symbol must carry NO sector, not the shared 'Unknown' "
        "bucket - otherwise unrelated names constrain one another"
    )


def test_the_sector_cap_actually_binds_on_an_over_concentrated_book():
    """Item 44's second half: prove the rail BINDS, not merely that it is called.

    A test that only checks the argument arrives would pass against a governor
    whose sector branch was dead. This reproduces 25 August's shape - a book
    already heavy in Financials, one more Financial proposed.

    At EXACTLY the cap the governor rejects outright (`sector_affordable_shares
    < 1`), so this asserts a refusal; the partial-headroom case below is where
    M31c's trim-rather-than-refuse actually shows. Measured, not assumed - the
    first draft of this docstring said "trimmed" and was wrong.
    """
    from qat.data.broker.adapter import Position
    from qat.domain.risk_engine.governor import PortfolioGovernor

    settings = Settings(_env_file=None, market="ASX")  # type: ignore[arg-type]
    governor = PortfolioGovernor(settings=settings)

    equity = 1_000_000.0
    # Three financials already on at $100k each = $300k, exactly the 30% cap.
    held = [
        Position(symbol=s, quantity=1000.0, avg_price=100.0) for s in ("ANZ.AX", "BOQ.AX", "SUN.AX")
    ]
    prices = {p.symbol: 100.0 for p in held}
    stops = {p.symbol: 90.0 for p in held}

    decision = governor.evaluate(
        symbol="IAG.AX",
        price=100.0,
        proposed_shares=1000.0,
        stop_price=90.0,
        positions=held,
        stops=stops,
        equity=equity,
        prices=prices,
        candidate_sector="Financials",
        sector_by_symbol=SECTOR_BY_SYMBOL,
    )

    assert decision.max_shares < 1000.0, (
        "the sector cap did not bind: 30% of $1,000,000 is $300,000 and the "
        "book already holds exactly that in Financials, so a fourth must not "
        "be sized in full"
    )


def test_the_same_book_in_four_DIFFERENT_sectors_is_not_trimmed():
    """The falsifier. If the test above passed because of some OTHER cap, it
    would pass here too - and this must not trim, because sector is the only
    thing that differs.
    """
    from qat.data.broker.adapter import Position
    from qat.domain.risk_engine.governor import PortfolioGovernor

    settings = Settings(_env_file=None, market="ASX")  # type: ignore[arg-type]
    governor = PortfolioGovernor(settings=settings)

    # Same sizes, same equity, same everything - four distinct sectors.
    held = [
        Position(symbol=s, quantity=1000.0, avg_price=100.0) for s in ("ANZ.AX", "CSL.AX", "BHP.AX")
    ]
    prices = {p.symbol: 100.0 for p in held}
    stops = {p.symbol: 90.0 for p in held}

    decision = governor.evaluate(
        symbol="WOW.AX",
        price=100.0,
        proposed_shares=1000.0,
        stop_price=90.0,
        positions=held,
        stops=stops,
        equity=1_000_000.0,
        prices=prices,
        candidate_sector=SECTOR_BY_SYMBOL["WOW.AX"],
        sector_by_symbol=SECTOR_BY_SYMBOL,
    )

    sectors_held = {SECTOR_BY_SYMBOL[p.symbol] for p in held}
    assert SECTOR_BY_SYMBOL["WOW.AX"] not in sectors_held, "fixture is not diversified"
    assert decision.max_shares >= 1000.0, (
        "a diversified book was trimmed, so the previous test's trim may not "
        "have come from the SECTOR cap at all"
    )


def test_partial_sector_headroom_TRIMS_rather_than_refusing():
    """M31c's actual behaviour, and the reason the cap trims at all: refusing
    at the cap "would silently stop a strategy trading a sector it is already
    in rather than letting it take a smaller position".
    """
    from qat.data.broker.adapter import Position
    from qat.domain.risk_engine.governor import PortfolioGovernor

    settings = Settings(_env_file=None, market="ASX")  # type: ignore[arg-type]
    governor = PortfolioGovernor(settings=settings)

    # $250k of Financials against a $300k cap: $50k of headroom, so a $100k
    # proposal must come back at about half, not zero and not in full.
    held = [
        Position(symbol="ANZ.AX", quantity=1000.0, avg_price=100.0),
        Position(symbol="BOQ.AX", quantity=1000.0, avg_price=100.0),
        Position(symbol="SUN.AX", quantity=500.0, avg_price=100.0),
    ]
    prices = {p.symbol: 100.0 for p in held}
    stops = {p.symbol: 90.0 for p in held}

    decision = governor.evaluate(
        symbol="IAG.AX",
        price=100.0,
        proposed_shares=1000.0,
        stop_price=90.0,
        positions=held,
        stops=stops,
        equity=1_000_000.0,
        prices=prices,
        candidate_sector="Financials",
        sector_by_symbol=SECTOR_BY_SYMBOL,
    )

    assert decision.allowed, "partial headroom must trim, not refuse"
    assert 0 < decision.max_shares <= 500.0, (
        f"expected a trim to the $50,000 of remaining sector headroom, "
        f"got {decision.max_shares}"
    )
