"""Cash-funded portfolio allocation and accounting tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_portfolio import (
    PortfolioInvariantError,
    PortfolioState,
    allocate_entry_batch,
    apply_dividend_cash,
    apply_fills,
    mark_to_market,
)
from qat.domain.backtester.swing_results import SimulatedFill
from qat.domain.strategies.authoritative_swing.model import (
    DecisionStatus,
    Pattern,
    PatternCandidate,
    PatternDecision,
    SetupDecision,
)
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
)


def D(value: str | int) -> Decimal:
    return Decimal(value)


COSTS = ExactCostProfile("fixture-v1", "fixture", D("0"), D("0"), "AUD", False, D("0"))
LIQUIDITY = LiquidityProfile("fixture-v1", D("1"), D("0"), D("0"))


def _candidate(symbol: str, *, quantity: int = 20) -> SetupDecision:
    pattern_candidate = PatternCandidate(
        Pattern.EMA_PULLBACK,
        f"pattern-{symbol}",
        None,
        date(2026, 1, 5),
        D("100"),
        D("95"),
        D("2"),
    )
    pattern = PatternDecision(Pattern.EMA_PULLBACK, DecisionStatus.QUALIFIED, (), pattern_candidate)
    return SetupDecision(
        "phase2-swing-v1",
        "swing-evidence-v1",
        f"decision-{symbol}",
        symbol,
        date(2026, 1, 5),
        DecisionStatus.QUALIFIED,
        (Pattern.EMA_PULLBACK,),
        (pattern,),
        D("100"),
        D("95"),
        quantity,
        quantity,
        quantity,
        (f"bar-{symbol}",),
    )


def test_oversubscribed_batch_scales_every_risk_budget_equally() -> None:
    candidates = tuple(_candidate(symbol) for symbol in ("AAA.AX", "BBB.AX", "CCC.AX"))

    allocations = allocate_entry_batch(D("3000"), candidates, COSTS, LIQUIDITY)

    assert len(allocations) == 3
    assert len({allocation.scale_factor for allocation in allocations}) == 1
    assert sum((item.reserved_cash for item in allocations), D("0")) <= D("3000")
    assert {item.quantity for item in allocations} == {10}


def test_symbol_input_order_cannot_choose_a_winner() -> None:
    candidates = tuple(_candidate(symbol) for symbol in ("CCC.AX", "AAA.AX", "BBB.AX"))
    forward = allocate_entry_batch(D("3000"), candidates, COSTS, LIQUIDITY)
    reverse = allocate_entry_batch(D("3000"), tuple(reversed(candidates)), COSTS, LIQUIDITY)

    assert forward == reverse
    assert tuple(item.symbol for item in forward) == ("AAA.AX", "BBB.AX", "CCC.AX")


def test_sub_two_share_allocations_are_removed() -> None:
    candidates = (_candidate("AAA.AX", quantity=2), _candidate("BBB.AX", quantity=2))
    assert allocate_entry_batch(D("150"), candidates, COSTS, LIQUIDITY) == ()


def test_allocation_records_structural_concentration_metrics() -> None:
    allocation = allocate_entry_batch(D("3000"), (_candidate("AAA.AX"),), COSTS, LIQUIDITY)[0]
    assert allocation.notional_exposure == D("2000")
    assert allocation.zero_price_equity_loss == D("2000") / D("3000")
    assert allocation.stop_distance == D("0.05")
    assert allocation.cost_to_risk_ratio == D("0")


def test_commission_floor_is_reserved_after_scaling() -> None:
    floor_costs = replace(COSTS, min_commission=D("6.60"))
    allocations = allocate_entry_batch(
        D("3020"),
        tuple(_candidate(symbol) for symbol in ("AAA.AX", "BBB.AX", "CCC.AX")),
        floor_costs,
        LIQUIDITY,
    )
    assert sum((item.reserved_cash for item in allocations), D("0")) <= D("3020")
    assert all(
        item.reserved_cash == D(item.quantity) * D("100") + D("6.60") for item in allocations
    )


def test_pending_purchase_reservations_reduce_available_cash() -> None:
    allocation = allocate_entry_batch(D("3000"), (_candidate("AAA.AX"),), COSTS, LIQUIDITY)[0]
    state = PortfolioState(D("3000"), D("3000"), pending_allocations=(allocation,))
    assert state.available_cash == D("1000")
    with pytest.raises(ValueError):
        PortfolioState(D("1000"), D("1000"), pending_allocations=(allocation,))


def test_fills_debit_and_credit_cash_once_without_going_negative() -> None:
    state = PortfolioState(D("1000"), D("1000"))
    buy = SimulatedFill("buy-1", "AAA.AX", date(2026, 1, 6), "buy", 5, D("100"), D("5"), "entry")
    sell = SimulatedFill("sell-1", "AAA.AX", date(2026, 1, 7), "sell", 5, D("110"), D("5"), "exit")

    after_buy = apply_fills(state, (buy,))
    after_sell = apply_fills(after_buy, (sell,))

    assert after_buy.cash == D("495")
    assert apply_fills(after_buy, (buy,)) == after_buy
    assert after_sell.cash == D("1040")
    with pytest.raises(PortfolioInvariantError):
        apply_fills(state, (replace(buy, quantity=11, event_id="too-large"),))


def test_dividend_cash_is_idempotent_and_mark_to_market_is_exact() -> None:
    state = PortfolioState(D("1000"), D("1000"), dividend_receivables=D("25"))
    settled = apply_dividend_cash(state, "div-1", D("25"))
    assert settled.cash == D("1025")
    assert settled.dividend_receivables == D("0")
    assert apply_dividend_cash(settled, "div-1", D("25")) == settled

    point = mark_to_market(settled, date(2026, 1, 7), {})
    assert point.equity == D("1025")
    assert point.position_value == D("0")
