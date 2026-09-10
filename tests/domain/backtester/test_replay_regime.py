"""The regime is measured, not defaulted (W2 step 4).

The engine's own warning is the assertion. Every replay before this printed:

    Gating 1 strategies on the sideways DEFAULT - the regime engine has
    published nothing. Strategies are being permitted or refused without any
    reading of the market

which is the state this step exists to end.
"""

from __future__ import annotations

import logging
import math

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.macro_fred import MacroObservation
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy

DAYS = 220
INDEX = pd.date_range("2026-01-05", periods=DAYS, freq="B", tz="UTC")

# The five series config.py actually requests. All US, which is why the ASX
# port has to re-source them rather than carry them across.
SERIES = ("DGS3MO", "DGS10", "T10Y3M", "VIXCLS", "BAA10Y")


def _bars(dip_index: int | None = None, phase: float = 0.0, swing: float = 0.0) -> pd.DataFrame:
    """A trend with a per-symbol wobble.

    The wobble is not decoration. BREADTH - how many names are above their own
    average - is one of the six regime features, and symbols that move
    identically leave it CONSTANT. The engine says so itself: "Regime features
    that never moved across 81 bars: breadth. A constant column makes the
    covariance matrix singular and can stop the fit converging." A first
    version of this fixture gave every symbol the same path and the posterior
    failed on every bar, which looked like a harness defect and was not.
    """
    closes = [100.0 + i * 0.5 + swing * math.sin((i + phase) / 11.0) for i in range(DAYS)]
    if dip_index is not None:
        closes[dip_index] -= 10.0
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.5 for c in closes],
            "low": [c - 1.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * DAYS,
        },
        index=INDEX,
    )


def _macro() -> dict[str, list[MacroObservation]]:
    """Five series that genuinely VARY across rows.

    Constant columns are the singular covariance matrix that made the HMM fit
    return NaN on 28 July. A fixture of flat series would reproduce that
    failure and look like a harness bug.
    """
    out: dict[str, list[MacroObservation]] = {}
    for offset, series in enumerate(SERIES):
        out[series] = [
            MacroObservation(
                series=series,
                ts=ts.to_pydatetime(),
                value=2.0 + offset + math.sin((i + offset * 7) / 9.0),
            )
            for i, ts in enumerate(INDEX)
        ]
    return out


def _session(tmp_path) -> ReplaySession:
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )
    return ReplaySession(
        bars={
            "SPY": _bars(swing=2.0),
            "AAA": _bars(dip_index=150, phase=17.0, swing=6.0),
            "BBB": _bars(phase=33.0, swing=9.0),
        },
        strategies=[SwingStrategy()],
        settings=settings,
        macro=_macro(),
        benchmark="SPY",
        warm_bars=80,
    )


@pytest.mark.asyncio
async def test_the_regime_is_measured_rather_than_defaulted(tmp_path, caplog):
    session = _session(tmp_path)

    # INFO, not WARNING: the sideways-default message is a warning but the one
    # that supersedes it - "gating now uses the classified regime" - is an INFO,
    # so capturing at WARNING sees only the complaint and never the resolution.
    with caplog.at_level(logging.INFO):
        await session.run()

    assert session.regime_engine._hmm.is_fitted, "the HMM never fitted, so nothing was measured"
    assert (
        "Strategy gating now uses the classified regime" in caplog.text
    ), "the sideways default was never superseded, so nothing read the market"
    # ONCE, on the first replayed bar, and no more. The regime for bar N is
    # published during bar N's dispatch, so consumers have no regime until N+1 -
    # a one-bar lag the live system has too, not a harness artefact. An
    # assertion of "never" would be asserting something untrue of production.
    #
    # ⚠️ THE WORDING CHANGED ON 10 SEPTEMBER and so did what it means. This
    # counted "sideways DEFAULT", from a message saying strategies were being
    # GATED on that default. They are now REFUSED instead, so the lag is one bar
    # of no entries rather than one bar of trading on an unread market.
    assert caplog.text.count("NO ENTRIES until the regime engine publishes") == 1


@pytest.mark.asyncio
async def test_the_macro_columns_keep_moving_after_the_seed(tmp_path):
    """Seeding fills the matrix to the boundary; without daily macro the FRED
    columns freeze, and a constant column across a decade is the singular
    covariance that returned NaN on 28 July."""
    session = _session(tmp_path)

    await session.run()

    matrix = session.regime_engine._feature_builder.feature_matrix()
    assert len(matrix) > 80, "the matrix must grow through the replayed period"
    vix_column = matrix[:, 2]
    assert vix_column.std() > 0.0, "a frozen VIX column is the singular-covariance failure"


@pytest.mark.asyncio
async def test_a_regime_was_published_to_the_strategy_engine(tmp_path):
    """The gate is only real if the label reaches the thing that gates."""
    session = _session(tmp_path)

    await session.run()

    assert session.engine._current_regime is not None
    assert session.regime_engine._current_boundary is not None
