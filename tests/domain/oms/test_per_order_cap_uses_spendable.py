"""The per-order cap keys off SPENDABLE cash, not raw cash (item 22).

Operator finding, 24 August, agreed and deferred to after the session.

M138's cap used `account.cash`, which ignores `min_cash_reserve` - money this
application has already declared unspendable. That made a THIRD basis for one
question: the no-leverage rail computes `available_cash - min_cash_reserve`
(`engine.py:242`), the Balances panel calls `spendable_cash(...)`, and the cap
used neither.

⚠️ **The failure that bites is not the arithmetic.** At today's $1,000 reserve
the two differ by $100 on a $100k order. But as cash approaches the reserve they
diverge without limit, and **a cap on raw cash can authorise an order the
no-leverage rail then refuses** - one rail permitting what another forbids. The
reserve exists to be raised; at $50,000 they part company properly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountBalances
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _FixedCashBroker(MockBroker):
    """A broker whose cash we control, so the OMS path is actually driven.

    ⚠️ The first version of these tests asserted on `AccountBalances.spendable_cash`
    directly - which already worked - so two of three passed against the defect
    and could not fail for it. Driving `submit_order` is the only thing that
    exercises the cap.
    """

    def __init__(self, cash: float) -> None:
        super().__init__(seed=1)
        self._fixed_cash = cash

    async def account(self):
        return AccountBalances(equity=self._fixed_cash, cash=self._fixed_cash)


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


async def _notional(reserve: float, cash: float, price: float = 100.0) -> float:
    """What the OMS actually authorised, in dollars.

    ⚠️ The notional, not a share count. `OrderCandidate` carries no quantity -
    the SIZER decides shares from ATR and edge, and the cap only trims what it
    proposes. Asserting an exact share count would pin the sizer's arithmetic
    rather than the cap's, and would break for reasons that have nothing to do
    with item 22.
    """
    settings = Settings(_env_file=None, min_cash_reserve=reserve)
    switch = KillSwitch()
    engine = RiskEngine(EventBus(), switch, settings=settings)
    oms = OMS(_FixedCashBroker(cash), engine, switch, settings=settings)
    oms.max_order_pct_of_cash = 0.10
    order = await oms.submit_order(
        OrderCandidate(
            symbol="BHP.AX",
            side="buy",
            price=price,
            atr=2.0,
            win_rate=0.6,
            win_loss_ratio=2.0,
            candidate_returns=_flat_returns(),
        ),
        cash,
        {},
        {},
    )
    return order.quantity * price


@pytest.mark.asyncio
async def test_nothing_is_authorised_beyond_a_share_of_SPENDABLE_cash() -> None:
    """The invariant item 22 is about. A $40,000 reserve on $100,000 cash leaves
    $60,000 spendable, so the ceiling is $6,000 - not the $10,000 a raw-cash cap
    would allow."""
    cash, reserve = 100_000.0, 40_000.0

    notional = await _notional(reserve, cash)

    assert notional <= 0.10 * (cash - reserve) + 1e-6, (
        f"authorised {notional:,.0f} against a spendable ceiling of "
        f"{0.10 * (cash - reserve):,.0f} - the cap is still keyed off RAW cash, and the "
        f"reserve this application declared unspendable was spent (item 22)"
    )


@pytest.mark.asyncio
async def test_the_two_rails_cannot_disagree_when_cash_nears_the_reserve() -> None:
    """⚠️ THE FAILURE THAT ACTUALLY BITES. Cash 55,000 against a 50,000 reserve
    leaves 5,000 spendable. A cap on RAW cash authorises up to 5,500 - more than
    the no-leverage rail permits - so one rail says yes to an order the other
    refuses. The gap grows without limit as cash approaches the reserve."""
    cash, reserve = 55_000.0, 50_000.0

    notional = await _notional(reserve, cash)

    assert (
        notional <= 0.10 * (cash - reserve) + 1e-6
    ), f"authorised {notional:,.0f} when only {cash - reserve:,.0f} is spendable"


def test_the_cap_uses_the_shared_definition_not_a_third_one() -> None:
    """⚠️ Read from source. Item 22's point is ONE definition with three
    readers, so what matters is that the cap CALLS the shared rule rather than
    recomputing `cash - reserve` itself - a fourth basis would pass every
    behavioural test above while reintroducing exactly the defect.

    The shared rule is `spendable_from`, a free function: the broker returns an
    `AccountSummary`, which does not carry `AccountBalances.spendable_cash`, so
    extracting the rule was the only way for both to read one definition.
    `spendable_cash` now delegates to it.
    """
    from pathlib import Path

    import qat

    root = Path(qat.__file__).parent
    oms_source = (root / "domain" / "oms" / "oms.py").read_text(encoding="utf-8")
    adapter_source = (root / "data" / "broker" / "adapter.py").read_text(encoding="utf-8")

    assert "spendable_from(" in oms_source, (
        "oms.py does not call the shared spendable rule, so the per-order cap is a "
        "third definition of what a buy may spend (item 22)"
    )
    assert (
        "max_order_pct_of_cash * account.cash" not in oms_source
    ), "the cap still multiplies RAW cash"
    assert "return spendable_from(self.cash, min_cash_reserve)" in adapter_source, (
        "AccountBalances.spendable_cash no longer delegates, so there are two "
        "definitions again - which is what item 22 was about"
    )
