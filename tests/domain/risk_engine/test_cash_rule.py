"""The no-leverage cash rule (spec M12).

Before this existed the account could be leveraged without limit: submitting
and signing off 12 orders against $100,000 of cash left the balance at
-$139,912. test_account_can_never_be_leveraged below is that exact scenario,
kept as a regression.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _returns(n: int = 30) -> pd.Series:
    return pd.Series([0.01, -0.02] * n)


def _candidate(symbol: str = "AAA", side: str = "buy", price: float = 100.0) -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        price=price,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_returns(),
    )


def _engine(**settings_kwargs: object) -> tuple[RiskEngine, Settings]:
    settings = Settings(_env_file=None, **settings_kwargs)  # type: ignore[arg-type]
    return RiskEngine(EventBus(), KillSwitch(), settings=settings), settings


def _oms(**settings_kwargs: object) -> tuple[OMS, MockBroker, Settings]:
    engine, settings = _engine(**settings_kwargs)
    broker = MockBroker(seed=1)
    return OMS(broker, engine, engine.kill_switch, max_order_notional=1_000_000.0), broker, settings


def test_buy_is_capped_at_available_cash_less_the_reserve():
    engine, settings = _engine()

    decision = engine.evaluate_order(_candidate(), 100_000.0, {}, {}, available_cash=1_000.0)

    assert decision.approved
    max_affordable = (1_000.0 - settings.min_cash_reserve) / 100.0
    assert decision.final_shares <= max_affordable
    assert decision.inputs["resized_for_cash"] is True


def test_buy_is_rejected_when_cash_affords_less_than_one_share():
    engine, _settings = _engine()

    decision = engine.evaluate_order(_candidate(), 100_000.0, {}, {}, available_cash=50.0)

    assert not decision.approved
    assert "Insufficient cash" in decision.reason


def test_the_reserve_can_never_be_set_to_zero():
    """What makes 'never fully deplete cash' structural rather than a default."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, min_cash_reserve=0.0)


def test_sell_is_never_blocked_by_the_cash_rule():
    """An exit raises cash; refusing to let the account de-risk because it is
    short of cash would be exactly backwards."""
    engine, _settings = _engine()

    decision = engine.evaluate_order(_candidate(side="sell"), 100_000.0, {}, {}, available_cash=0.0)

    assert decision.approved


def test_omitting_cash_leaves_the_check_inactive():
    """guards.py re-verifies AI recommendations without a broker; that path
    cannot place an order, so it may omit cash."""
    engine, _settings = _engine()

    decision = engine.evaluate_order(_candidate(), 100_000.0, {}, {})

    assert decision.approved
    assert "resized_for_cash" not in decision.inputs


@pytest.mark.asyncio
async def test_account_can_never_be_leveraged():
    """Regression for the measured failure: $100k cash, 12 orders, ended at
    -$139,912 with nothing blocking it."""
    oms, broker, settings = _oms()
    account = await broker.account()
    starting_cash = account.cash

    for i in range(12):
        order = await oms.submit_order(_candidate(f"S{i}"), account.net_liquidation, {}, {})
        if order.status == "pending_signoff":
            await oms.sign_off(order.order_id, operator="alice")

    final = await broker.account()
    assert final.cash > 0, "account went negative - leverage was permitted"
    assert final.cash >= settings.min_cash_reserve
    assert final.cash < starting_cash, "sanity: some orders should have gone through"


@pytest.mark.asyncio
async def test_orders_beyond_available_cash_are_rejected_not_silently_shrunk():
    oms, broker, _settings = _oms()
    account = await broker.account()
    statuses = []
    for i in range(12):
        order = await oms.submit_order(_candidate(f"S{i}"), account.net_liquidation, {}, {})
        if order.status == "pending_signoff":
            result = await oms.sign_off(order.order_id, operator="alice")
            statuses.append(result.status)
        else:
            statuses.append(order.status)

    assert "filled" in statuses
    assert "rejected" in statuses, "later orders must be refused once cash runs out"
