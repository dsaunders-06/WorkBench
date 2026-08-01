"""Portfolio-level exposure caps (spec M15).

Per-trade risk limits bound one trade and say nothing about ten trades each
individually within budget. These cover the three things that closes: an
aggregate risk-at-stop cap, a concurrent-position count, and - the one that
actually bit in the reference implementation - counting pending orders as
committed exposure.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.governor import PortfolioGovernor
from qat.domain.risk_engine.kill_switch import KillSwitch

EQUITY = 100_000.0


def _settings(**overrides) -> Settings:
    # Concentration and the gap budget are relaxed by default so these tests
    # isolate the aggregate risk-at-stop cap they were written for. Both have
    # their own tests below.
    base = {
        "_env_file": None,
        "max_aggregate_risk_at_stop_pct": 0.05,
        "max_single_name_concentration_pct": 1.0,
        "max_gap_risk_at_shock_pct": 1.0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _position(symbol: str, quantity: float = 100.0, price: float = 100.0) -> Position:
    return Position(symbol=symbol, quantity=quantity, avg_price=price)


def _pending(
    symbol: str, quantity: float = 100.0, price: float = 100.0, stop: float | None = 95.0
) -> Order:
    return Order(
        symbol=symbol,
        side="buy",
        quantity=quantity,
        order_id=f"pending-{symbol}",
        status="pending_signoff",
        reference_price=price,
        stop_price=stop,
    )


# --- Measurement --------------------------------------------------------------


def test_risk_at_stop_is_the_sum_of_each_positions_risk():
    governor = PortfolioGovernor(_settings())
    positions = [_position("A"), _position("B")]
    stops = {"A": 95.0, "B": 90.0}

    snap = governor.snapshot(positions, stops, EQUITY)

    # A: 100 x (100-95) = 500; B: 100 x (100-90) = 1000
    assert snap.risk_at_stop_dollars == pytest.approx(1500.0)
    assert snap.risk_at_stop_pct == pytest.approx(0.015)
    assert snap.position_count == 2


def test_a_position_with_no_known_stop_risks_its_whole_value():
    """Unknown protection is treated as no protection. Assuming a stop exists
    would understate risk by exactly the amount that is unknown - which is the
    situation for every position adopted from a previous session."""
    governor = PortfolioGovernor(_settings())
    snap = governor.snapshot([_position("A")], stops={}, equity=EQUITY)
    assert snap.risk_at_stop_dollars == pytest.approx(10_000.0)


def test_a_stop_above_the_price_is_not_treated_as_protection():
    governor = PortfolioGovernor(_settings())
    snap = governor.snapshot([_position("A")], stops={"A": 150.0}, equity=EQUITY)
    assert snap.risk_at_stop_dollars == pytest.approx(10_000.0)


def test_pending_buys_count_as_committed_exposure():
    """The bug this exists to prevent: a governor that only sees filled
    positions approves a tenth candidate while nine sit in the blotter."""
    governor = PortfolioGovernor(_settings())
    with_pending = governor.snapshot([], {}, EQUITY, pending_orders=[_pending("A")])
    assert with_pending.position_count == 1
    assert with_pending.risk_at_stop_dollars == pytest.approx(500.0)


def test_pending_sells_do_not_create_headroom_before_they_fill():
    """Counting a reduction that has not happened would let new risk in against
    headroom that does not exist yet."""
    governor = PortfolioGovernor(_settings())
    sell = Order(
        symbol="A",
        side="sell",
        quantity=100.0,
        order_id="x",
        status="pending_signoff",
        reference_price=100.0,
    )
    snap = governor.snapshot([_position("A")], {"A": 95.0}, EQUITY, pending_orders=[sell])
    assert snap.risk_at_stop_dollars == pytest.approx(500.0)


def test_a_symbol_held_and_pending_counts_as_one_position():
    governor = PortfolioGovernor(_settings())
    snap = governor.snapshot([_position("A")], {"A": 95.0}, EQUITY, pending_orders=[_pending("A")])
    assert snap.position_count == 1


# --- Gating -------------------------------------------------------------------


def test_a_candidate_within_every_cap_is_allowed():
    governor = PortfolioGovernor(_settings())
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=[],
        stops={},
        equity=EQUITY,
    )
    assert decision.allowed is True
    assert decision.max_shares == 10.0


def test_the_position_count_cap_blocks_a_new_name():
    governor = PortfolioGovernor(_settings(max_concurrent_positions=2))
    positions = [_position("A"), _position("B")]
    decision = governor.evaluate(
        "C",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 99.0, "B": 99.0},
        equity=EQUITY,
    )
    assert decision.allowed is False
    assert "position limit" in decision.reason


def test_the_position_count_cap_does_not_block_adding_to_a_held_name():
    """The cap bounds how thinly the portfolio is spread, not position size -
    that is the single-name concentration check's job."""
    governor = PortfolioGovernor(_settings(max_concurrent_positions=2))
    positions = [_position("A"), _position("B")]
    decision = governor.evaluate(
        "A",
        price=100.0,
        proposed_shares=10.0,
        stop_price=99.0,
        positions=positions,
        stops={"A": 99.0, "B": 99.0},
        equity=EQUITY,
    )
    assert decision.allowed is True


def test_an_over_cap_portfolio_blocks_new_risk_entirely():
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=200.0)]  # no stop -> 20,000 at risk
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={},
        equity=EQUITY,
    )
    assert decision.allowed is False
    assert "aggregate risk-at-stop" in decision.reason


def test_a_candidate_is_trimmed_to_the_remaining_headroom():
    """Graceful degradation: trim to what fits rather than rejecting outright."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=800.0)]  # 800 x 5 = 4,000 of the 5,000 cap
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=1000.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 95.0},
        equity=EQUITY,
    )
    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(200.0)  # 1,000 headroom / 5 per share
    assert "trimmed" in decision.reason


def test_headroom_too_small_for_one_share_is_rejected():
    """999.5 x 5 = 4,997.50 of the 5,000 cap, leaving $2.50 - half a share's
    worth of risk. A fractional share of headroom is not a trade."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=999.5)]
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 95.0},
        equity=EQUITY,
    )
    assert decision.allowed is False
    assert "headroom" in decision.reason


def test_exactly_one_share_of_headroom_is_allowed_and_trimmed_to_it():
    """The boundary the previous test sits just past."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=999.0)]
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 95.0},
        equity=EQUITY,
    )
    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(1.0)


@pytest.mark.parametrize("equity", [0.0, -5.0])
def test_non_positive_equity_is_rejected(equity):
    governor = PortfolioGovernor(_settings())
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=[],
        stops={},
        equity=equity,
    )
    assert decision.allowed is False


# --- De-levering --------------------------------------------------------------


def test_no_delever_when_within_cap():
    governor = PortfolioGovernor(_settings())
    assert governor.delever_fraction([_position("A")], {"A": 99.0}, EQUITY) == 0.0


def test_the_delever_fraction_lands_under_the_cap_not_on_it():
    """Landing exactly on the boundary would re-trigger the sweep from ordinary
    price movement alone on the next check."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=2000.0)]  # 2000 x 5 = 10,000 vs a 5,000 cap
    stops = {"A": 95.0}

    fraction = governor.delever_fraction(positions, stops, EQUITY)

    assert 0.0 < fraction < 1.0
    remaining = [_position("A", quantity=2000.0 * (1 - fraction))]
    after = governor.snapshot(remaining, stops, EQUITY)
    assert after.risk_at_stop_pct < 0.05
    assert after.risk_at_stop_pct == pytest.approx(0.05 * 0.9, rel=1e-6)


def test_proportional_trimming_scales_the_whole_sum_by_the_same_fraction():
    """The reason a proportional trim needs no ranking: aggregate risk is a
    linear sum, so one fraction hits the target exactly."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=1000.0), _position("B", quantity=1500.0)]
    stops = {"A": 95.0, "B": 90.0}

    fraction = governor.delever_fraction(positions, stops, EQUITY)
    trimmed = [
        _position("A", quantity=1000.0 * (1 - fraction)),
        _position("B", quantity=1500.0 * (1 - fraction)),
    ]

    after = governor.snapshot(trimmed, stops, EQUITY)
    assert after.risk_at_stop_pct == pytest.approx(0.05 * 0.9, rel=1e-6)


# --- Integration through the risk engine --------------------------------------


def _candidate(symbol: str = "AAA") -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
    )


@pytest.mark.asyncio
async def test_the_governor_gates_orders_through_the_oms_path():
    """OMS supplies the portfolio state itself, so no caller can bypass the cap
    by omitting an argument - the same reasoning as the cash check."""
    settings = _settings(max_concurrent_positions=3)
    engine = RiskEngine(EventBus(), KillSwitch(), settings=settings)
    oms = OMS(MockBroker(seed=1), engine, engine.kill_switch, max_order_notional=1_000_000.0)

    accepted = []
    for i in range(12):
        order = await oms.submit_order(_candidate(f"S{i}"), EQUITY, {}, {})
        if order.status == "pending_signoff":
            accepted.append(order)

    assert len(accepted) <= 3, "the position cap must bound pending orders too"


@pytest.mark.asyncio
async def test_every_approved_buy_carries_a_protective_stop():
    """A stop that exists only as a sizing assumption protects nothing - so the
    sizing stop is attached as a real bracket when the strategy proposes none."""
    engine = RiskEngine(EventBus(), KillSwitch(), settings=_settings())
    oms = OMS(MockBroker(seed=1), engine, engine.kill_switch, max_order_notional=1_000_000.0)

    order = await oms.submit_order(_candidate(), EQUITY, {}, {})

    assert order.status == "pending_signoff"
    assert order.stop_price is not None
    assert order.stop_price < 100.0
    assert order.is_bracket is True


# --- Single-name concentration and gap risk (M30) --------------------------


def test_a_concentrated_candidate_is_trimmed_not_refused():
    """The whole reason the cap could be lowered. 1% risk over a ~5% stop
    sizes a position at about 20% of equity, so under the old reject semantics
    a 15% cap would have refused every swing trade outright rather than making
    it smaller."""
    governor = PortfolioGovernor(settings=_settings(max_single_name_concentration_pct=0.15))

    decision = governor.evaluate(
        symbol="AAA",
        price=100.0,
        proposed_shares=200.0,  # $20,000 = 20% of equity
        stop_price=95.0,
        positions=[],
        stops={},
        equity=EQUITY,
    )

    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(150.0)  # trimmed to $15,000
    assert "single-name" in decision.reason


def test_concentration_counts_what_is_already_held_in_that_name():
    governor = PortfolioGovernor(settings=_settings(max_single_name_concentration_pct=0.15))

    decision = governor.evaluate(
        symbol="AAA",
        price=100.0,
        proposed_shares=100.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
    )

    # $10,000 held against a $15,000 cap leaves room for 50 shares, not 100.
    assert decision.max_shares == pytest.approx(50.0)


def test_the_gap_budget_limits_total_overnight_notional():
    """Every other figure here means "if the stop fills". A gap opens through
    it, so the shock applies to notional and gets its own budget."""
    governor = PortfolioGovernor(
        settings=_settings(
            max_single_name_concentration_pct=1.0,
            gap_shock_pct=0.06,
            max_gap_risk_at_shock_pct=0.05,
        )
    )

    # 5% of equity budget / 6% shock = $83,333 of permitted gross exposure.
    decision = governor.evaluate(
        symbol="AAA",
        price=100.0,
        proposed_shares=1_000.0,  # asking for $100,000
        stop_price=95.0,
        positions=[],
        stops={},
        equity=EQUITY,
    )

    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(833.3333, rel=1e-4)
    assert "overnight-gap" in decision.reason


def test_a_full_book_refuses_a_new_position_on_gap_risk_alone():
    governor = PortfolioGovernor(
        settings=_settings(
            max_single_name_concentration_pct=1.0,
            gap_shock_pct=0.06,
            max_gap_risk_at_shock_pct=0.05,
        )
    )

    decision = governor.evaluate(
        symbol="NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=[Position(symbol="OLD", quantity=900.0, avg_price=100.0)],
        stops={"OLD": 95.0},
        equity=EQUITY,
        prices={"OLD": 100.0},
    )

    assert decision.allowed is False
    assert "overnight gap" in decision.reason


# --- Sector concentration (M31c) -------------------------------------------


def test_a_sector_that_is_already_full_trims_the_candidate():
    """Sector got the same treatment single-name got in M30, and for the same
    reason: PortfolioRiskChecker tests it as a pass/fail, so lowering the cap
    to 30% under reject semantics would refuse the third position in a sector
    outright rather than sizing it down."""
    governor = PortfolioGovernor(settings=_settings(max_sector_concentration_pct=0.30))

    decision = governor.evaluate(
        symbol="CCC",
        price=100.0,
        proposed_shares=150.0,  # $15,000 wanted
        stop_price=95.0,
        positions=[
            Position(symbol="AAA", quantity=100.0, avg_price=100.0),
            Position(symbol="BBB", quantity=100.0, avg_price=100.0),
        ],
        stops={"AAA": 95.0, "BBB": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0, "BBB": 100.0},
        candidate_sector="Financials",
        sector_by_symbol={"AAA": "Financials", "BBB": "Financials", "CCC": "Financials"},
    )

    # $20,000 of Financials held against a $30,000 cap leaves $10,000.
    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(100.0)
    assert "Financials sector" in decision.reason


def test_holdings_in_other_sectors_do_not_count_against_this_one():
    governor = PortfolioGovernor(settings=_settings(max_sector_concentration_pct=0.30))

    decision = governor.evaluate(
        symbol="CCC",
        price=100.0,
        proposed_shares=150.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=250.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        candidate_sector="Financials",
        sector_by_symbol={"AAA": "Energy", "CCC": "Financials"},
    )

    assert decision.max_shares == pytest.approx(150.0)
    assert decision.reason == "within portfolio limits"


def test_a_pending_buy_in_the_sector_counts_before_it_fills():
    """The same trap the position cap had: an unfilled order is committed
    exposure, and a sector cap that only sees fills will approve a third name
    while the second sits in the blotter."""
    governor = PortfolioGovernor(settings=_settings(max_sector_concentration_pct=0.30))

    decision = governor.evaluate(
        symbol="CCC",
        price=100.0,
        proposed_shares=150.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        pending_orders=[_pending("BBB", quantity=100.0, price=100.0)],
        candidate_sector="Financials",
        sector_by_symbol={"AAA": "Financials", "BBB": "Financials", "CCC": "Financials"},
    )

    assert decision.max_shares == pytest.approx(100.0)


def test_a_sector_at_its_cap_rejects_rather_than_sizing_to_nothing():
    governor = PortfolioGovernor(settings=_settings(max_sector_concentration_pct=0.30))

    decision = governor.evaluate(
        symbol="CCC",
        price=100.0,
        proposed_shares=100.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=300.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        candidate_sector="Financials",
        sector_by_symbol={"AAA": "Financials", "CCC": "Financials"},
    )

    assert decision.allowed is False
    assert "sector cap" in decision.reason


def test_an_unclassified_candidate_is_not_gated_by_sector():
    """Sector is only known for symbols in the instrument map. A candidate
    without one must not be trimmed against a sector nobody assigned it to."""
    governor = PortfolioGovernor(settings=_settings(max_sector_concentration_pct=0.30))

    decision = governor.evaluate(
        symbol="CCC",
        price=100.0,
        proposed_shares=150.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=300.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        candidate_sector=None,
        sector_by_symbol={"AAA": "Financials"},
    )

    assert decision.max_shares == pytest.approx(150.0)


# --- Correlated-cluster concentration (M33) ----------------------------------


def _returns(seed: int, n: int = 60, common: pd.Series | None = None, weight: float = 0.0):
    """A return series, optionally sharing `weight` of a common factor - which
    is what makes two names correlated without being the same name."""
    rng = pd.Series(
        [((seed * 7919 + i * 104729) % 1000 - 500) / 10000.0 for i in range(n)],
        index=pd.RangeIndex(n),
    )
    if common is None:
        return rng
    return weight * common + (1.0 - weight) * rng


def test_names_that_move_together_are_capped_as_one_cluster():
    """Single-name bounds one ticker and sector bounds one label. Neither
    catches several names that simply move together, which is one position
    taken several times with none of the diversification the count implies."""
    governor = PortfolioGovernor(
        settings=_settings(max_correlated_cluster_pct=0.30, max_sector_concentration_pct=1.0)
    )
    common = _returns(1)
    existing = {"AAA": _returns(2, common=common, weight=0.98)}
    candidate = _returns(3, common=common, weight=0.98)

    decision = governor.evaluate(
        symbol="BBB",
        price=100.0,
        proposed_shares=250.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        candidate_returns=candidate,
        existing_returns=existing,
    )

    # $10,000 of the cluster held against a $30,000 cap leaves 200 shares.
    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(200.0)
    assert "correlated-cluster" in decision.reason


def test_an_uncorrelated_holding_is_not_in_the_cluster():
    governor = PortfolioGovernor(settings=_settings(max_correlated_cluster_pct=0.30))
    existing = {"AAA": _returns(2)}

    decision = governor.evaluate(
        symbol="BBB",
        price=100.0,
        proposed_shares=250.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        candidate_returns=_returns(3),
        existing_returns=existing,
    )

    assert decision.max_shares == pytest.approx(250.0)
    assert "correlated-cluster" not in decision.reason


def test_too_little_overlap_is_not_treated_as_correlated():
    """Correlation on a handful of shared observations is noise, and trimming a
    real position on the strength of it is worse than not measuring."""
    governor = PortfolioGovernor(settings=_settings(max_correlated_cluster_pct=0.30))
    common = _returns(1, n=8)
    existing = {"AAA": _returns(2, n=8, common=common, weight=0.99)}

    decision = governor.evaluate(
        symbol="BBB",
        price=100.0,
        proposed_shares=250.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        candidate_returns=_returns(3, n=8, common=common, weight=0.99),
        existing_returns=existing,
    )

    assert decision.max_shares == pytest.approx(250.0)


def test_a_symbol_with_no_history_is_not_assumed_correlated():
    """The opposite of the unknown-stop rule, deliberately. An unknown stop
    costs size; an unknown correlation would refuse every symbol the app has
    no history for, which is every new one."""
    governor = PortfolioGovernor(settings=_settings(max_correlated_cluster_pct=0.30))

    decision = governor.evaluate(
        symbol="BBB",
        price=100.0,
        proposed_shares=250.0,
        stop_price=95.0,
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        stops={"AAA": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0},
        candidate_returns=_returns(3),
        existing_returns={},
    )

    assert decision.max_shares == pytest.approx(250.0)


def test_a_full_cluster_rejects_rather_than_sizing_to_nothing():
    governor = PortfolioGovernor(
        settings=_settings(max_correlated_cluster_pct=0.30, max_sector_concentration_pct=1.0)
    )
    common = _returns(1)

    decision = governor.evaluate(
        symbol="DDD",
        price=100.0,
        proposed_shares=100.0,
        stop_price=95.0,
        positions=[
            Position(symbol="AAA", quantity=100.0, avg_price=100.0),
            Position(symbol="BBB", quantity=100.0, avg_price=100.0),
            Position(symbol="CCC", quantity=100.0, avg_price=100.0),
        ],
        stops={"AAA": 95.0, "BBB": 95.0, "CCC": 95.0},
        equity=EQUITY,
        prices={"AAA": 100.0, "BBB": 100.0, "CCC": 100.0},
        candidate_returns=_returns(9, common=common, weight=0.98),
        existing_returns={
            "AAA": _returns(2, common=common, weight=0.98),
            "BBB": _returns(4, common=common, weight=0.98),
            "CCC": _returns(6, common=common, weight=0.98),
        },
    )

    assert decision.allowed is False
    assert "cluster cap" in decision.reason
