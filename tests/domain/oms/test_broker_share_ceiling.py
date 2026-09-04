"""The sizer proposed 790 shares against a broker that refuses above 500.

TWS enforces a Precautionary Settings size limit that is NOT exposed through the
API - verified 3 September: no method on `IB` and no name in `ib_async` mentions
preset, precaution, limit, config or setting. So the app must be told it, and the
broker's own rejection audits what it was told.

Defaults to None - no ceiling - because a fresh install must not silently enforce
a limit belonging to one particular TWS instance.

⚠️ THESE TESTS ASSERT A RELATIONSHIP, NOT A SHARE COUNT. `OrderCandidate` carries
no quantity: the SIZER decides shares from ATR and edge, and a ceiling only trims
what it proposes. Pinning "790 becomes 500" would pin the sizer's arithmetic and
break for reasons that have nothing to do with this ceiling - the same trap
`test_per_order_cap_uses_spendable.py` records for the cash cap.
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

# Large enough that the per-order CASH cap never binds, so any trim observed
# here is the share ceiling and not the other rail wearing its coat.
_CASH = 100_000_000.0
_PRICE = 1.0


class _RichBroker(MockBroker):
    def __init__(self) -> None:
        super().__init__(seed=1)

    async def account(self) -> AccountBalances:
        return AccountBalances(equity=_CASH, cash=_CASH)


def _flat_returns(n: int = 30) -> pd.Series:
    return pd.Series([0.001] * n, index=pd.date_range("2024-01-01", periods=n))


async def _quantity(ceiling: int | None) -> float:
    """What the OMS actually authorised, driving the real sizing path."""
    settings = Settings(_env_file=None, broker_max_order_shares=ceiling)
    switch = KillSwitch()
    engine = RiskEngine(EventBus(), switch, settings=settings)
    oms = OMS(_RichBroker(), engine, switch, settings=settings)
    order = await oms.submit_order(
        OrderCandidate(
            symbol="BHP.AX",
            side="buy",
            price=_PRICE,
            atr=0.02,
            win_rate=0.6,
            win_loss_ratio=2.0,
            candidate_returns=_flat_returns(),
        ),
        _CASH,
        {},
        {},
    )
    return order.quantity


def test_the_ceiling_defaults_to_unset() -> None:
    """⚠️ A default of 500 would silently enforce one TWS instance's config on
    every install."""
    assert Settings(_env_file=None).broker_max_order_shares is None


@pytest.mark.asyncio
async def test_an_order_above_the_ceiling_is_trimmed_to_it() -> None:
    unceilinged = await _quantity(None)
    ceiling = int(unceilinged // 2)
    assert ceiling >= 1, "the fixture must propose enough shares for a ceiling to bind"

    assert await _quantity(ceiling) == float(ceiling)


@pytest.mark.asyncio
async def test_an_order_below_the_ceiling_is_untouched() -> None:
    unceilinged = await _quantity(None)
    ceiling = int(unceilinged * 2) + 1

    assert await _quantity(ceiling) == unceilinged


@pytest.mark.asyncio
async def test_no_ceiling_means_no_trim() -> None:
    """The default path. Nothing an unconfigured install does may change."""
    assert await _quantity(None) > 0


def test_a_ceiling_of_zero_is_refused_by_config() -> None:
    """⚠️ Zero would refuse every order silently rather than say so. `gt=0`
    makes it a startup error instead of a book that never opens a position."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, broker_max_order_shares=0)
