"""Turning one rail off, and refusing to pretend when it cannot be (W2 step 6).

A rail is disabled by setting its existing `Settings` value beyond reach, so the
shipped `RiskEngine` and `PortfolioGovernor` run exactly as they trade. The
alternative - threading a rail set through the decision path with `if enabled`
guards - would make "off" genuinely off and would put new branches inside the
code the validation freeze exists to hold still.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.ablation import RAILS, UnablatableRail, ablated_settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.evaluation.refusals import load_risk_decisions, rail_of
from qat.domain.strategies.swing import SwingStrategy


def _base(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=str(tmp_path))


def test_every_neutral_value_survives_its_own_validator(tmp_path: Path):
    """A neutral value outside a field's bounds would raise at construction and
    make that rail silently unablatable - so this constructs every one rather
    than trusting the table's comment."""
    for rail in RAILS:
        settings = ablated_settings(_base(tmp_path), [rail])
        assert isinstance(settings, Settings)


def test_the_overrides_actually_reach_the_settings(tmp_path: Path):
    settings = ablated_settings(_base(tmp_path), ["position_limit"])

    assert settings.max_concurrent_positions >= 10_000


def test_disabling_nothing_changes_nothing(tmp_path: Path):
    base = _base(tmp_path)

    settings = ablated_settings(base, [])

    assert settings.max_concurrent_positions == base.max_concurrent_positions
    assert settings.max_cost_to_risk_pct == base.max_cost_to_risk_pct


def test_an_unknown_rail_is_refused_not_ignored(tmp_path: Path):
    """Running a baseline twice and reporting no difference is
    indistinguishable from a rail that costs nothing, which is the failure this
    whole design is shaped to avoid."""
    with pytest.raises(UnablatableRail, match="not ablatable"):
        ablated_settings(_base(tmp_path), ["a rail nobody has written"])


def test_the_cost_flag_is_refused_by_name(tmp_path: Path):
    """`apply_costs_in_paper` gates the cost RAIL and, separately, whether
    TradeLedger charges costs into recorded P&L. Using it would disable the rail
    AND make every trade free, so the no-rail arm would win for a reason having
    nothing to do with the rail - a confound invisible in the output."""
    with pytest.raises(UnablatableRail, match="two consumers"):
        ablated_settings(_base(tmp_path), ["apply_costs_in_paper"])


def test_the_regime_rail_is_accepted_but_changes_no_setting(tmp_path: Path):
    """It has no knob - it arrives as RegimeEvent.exposure_scalar - so ablating
    it is the caller not starting the regime engine. Accepted here so one list
    can name every rail."""
    base = _base(tmp_path)

    settings = ablated_settings(base, ["regime_gate"])

    assert settings.max_concurrent_positions == base.max_concurrent_positions


# --- the test that separates a mapping from a working switch ----------------


def _dipping(seed: float, dip_at: int, days: int = 160) -> pd.DataFrame:
    """The proven shape: an uptrend with one pullback-and-reclaim.

    The dip is computed rather than tuned - swing needs `prior_close <=
    prior_fast` then `last_close > last_fast`, and an EMA20 lags a +0.5/day
    trend by about 4.75, so a shallower dip never reaches the average and no
    entry fires at all.

    `dip_at` STAGGERS the symbols, and it has to. Dipping them all on the same
    bar makes them signal in one pass before any has filled, and all three were
    approved even at a one-position limit - so the fixture proved nothing about
    the rail. Staggered, the first is HELD by the time the second signals, which
    is also the shape the live record takes.
    """
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [seed + i * 0.5 for i in range(days)]
    closes[dip_at] -= 10.0
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.5 for c in closes],
            "low": [c - 1.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        },
        index=index,
    )


async def _rails_that_bound(directory: Path, limit: int) -> set[str]:
    directory.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        data_dir=str(directory),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
        max_concurrent_positions=limit,
    )
    session = ReplaySession(
        bars={
            name: _dipping(100.0 + i * 40, dip_at=dip)
            for i, (name, dip) in enumerate([("AAA", 128), ("BBB", 138), ("CCC", 148)])
        },
        strategies=[SwingStrategy()],
        settings=settings,
        warm_bars=60,
    )
    await session.run()
    return {
        rail_of(row["reason"])
        for row in load_risk_decisions(directory)
        if str(row["approved"]).strip().lower() == "false"
    }


@pytest.mark.asyncio
async def test_the_position_limit_binds_at_one_and_not_at_the_neutral_value(tmp_path: Path):
    """The mapping is EXERCISED, not asserted.

    A neutral value that failed to neutralise would otherwise surface as a quiet
    zero in an ablation result - which reads as "this rail costs nothing" and is
    the exact confusion the manifest's `exercised` field exists to prevent.
    """
    bound = await _rails_that_bound(tmp_path / "on", 1)
    neutral = int(RAILS["position_limit"]["max_concurrent_positions"])
    free = await _rails_that_bound(tmp_path / "off", neutral)

    assert "Position limit" in bound, "the fixture never reached the limit, so it proves nothing"
    assert "Position limit" not in free
