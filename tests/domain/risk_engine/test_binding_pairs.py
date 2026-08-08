"""Which held pairs are actually at or above the cluster threshold.

The Risk Console's correlation table correlates ~60 intraday TICK samples -
about the last hour. The rail that enforces the limit correlates 60 DAILY bars,
about three months, a window M58b chose deliberately after finding that 300 bars
hid a genuinely correlated pair. So the table an operator reads to understand
the correlation limit was not showing the correlation that enforces it.

This exposes the rail's own answer rather than letting a screen compute a second
one. Two derivations of "are these correlated" would eventually disagree, and
the operator would have no way to tell which was binding.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.risk_engine.governor import PortfolioGovernor


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def _series(values: list[float], start: str = "2026-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=index)


def _wave(n: int, phase: float = 0.0, noise: float = 0.0, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    return [
        float(np.sin(i / 3.0 + phase) + (rng.normal(0, noise) if noise else 0.0)) for i in range(n)
    ]


def test_a_correlated_pair_is_reported_with_its_coefficient() -> None:
    governor = PortfolioGovernor(settings=_settings())
    moves = _wave(80)
    returns = {"AMAT": _series(moves), "AMD": _series(moves)}

    pairs = governor.binding_pairs(returns)

    assert len(pairs) == 1
    left, right, corr = pairs[0]
    assert {left, right} == {"AMAT", "AMD"}
    assert corr > 0.99


def test_an_uncorrelated_pair_is_not_reported() -> None:
    governor = PortfolioGovernor(settings=_settings())
    returns = {
        "AMAT": _series(_wave(80, seed=1, noise=1.0)),
        "JNJ": _series(_wave(80, phase=1.7, seed=2, noise=1.0)),
    }

    assert governor.binding_pairs(returns) == []


def test_a_pair_below_the_threshold_is_not_binding() -> None:
    """0.70 is the cap's threshold, and the rail's test is `>=`."""
    governor = PortfolioGovernor(settings=_settings(correlation_cluster_threshold=0.99))
    moves = _wave(80, noise=0.35, seed=3)
    shifted = _wave(80, phase=0.9, noise=0.35, seed=4)

    assert governor.binding_pairs({"A": _series(moves), "B": _series(shifted)}) == []


def test_too_little_overlap_is_skipped_rather_than_counted() -> None:
    """The rail's rule: correlation on a handful of shared observations is
    noise, and treating noise as "these move together" would trim real
    positions for no reason. Unmeasurable is NOT binding."""
    governor = PortfolioGovernor(settings=_settings())
    moves = _wave(80)
    returns = {
        "AMAT": _series(moves),
        # Overlaps by only a few days.
        "AMD": _series(moves[:5], start="2026-03-18"),
    }

    assert governor.binding_pairs(returns) == []


def test_it_measures_over_the_rail_s_window_not_the_whole_series() -> None:
    """M58b's finding, as a test. AMAT and AMD score 0.79 over sixty days and
    0.58 over three hundred - the long window averages away precisely the
    co-movement the rail exists to catch. The screen must inherit the short
    window, or it would show the number that hid the pair."""
    governor = PortfolioGovernor(settings=_settings(correlation_window_bars=60))
    # Uncorrelated for a long stretch, tightly correlated over the recent 60.
    early_a, early_b = _wave(200, seed=5, noise=1.2), _wave(200, seed=6, noise=1.2)
    recent = _wave(60, seed=7)
    returns = {
        "AMAT": _series(early_a + recent),
        "AMD": _series(early_b + recent),
    }

    pairs = governor.binding_pairs(returns)

    assert [p[0] for p in pairs] == ["AMAT"]
    assert pairs[0][2] > 0.9


def test_only_held_symbols_are_considered_when_positions_are_given() -> None:
    """A watchlist symbol the book does not hold cannot breach a cluster cap on
    holdings."""
    governor = PortfolioGovernor(settings=_settings())
    moves = _wave(80)
    returns = {"AMAT": _series(moves), "AMD": _series(moves), "SPY": _series(moves)}
    positions = [
        Position(symbol="AMAT", quantity=7, avg_price=540.0),
        Position(symbol="AMD", quantity=7, avg_price=510.0),
    ]

    pairs = governor.binding_pairs(returns, positions=positions)

    assert len(pairs) == 1
    assert {pairs[0][0], pairs[0][1]} == {"AMAT", "AMD"}


def test_each_pair_is_reported_once() -> None:
    """A B and B A are the same pair. Reporting both would double every
    cluster on screen."""
    governor = PortfolioGovernor(settings=_settings())
    moves = _wave(80)
    returns = {sym: _series(moves) for sym in ("A", "B", "C")}

    pairs = governor.binding_pairs(returns)

    assert len(pairs) == 3  # AB, AC, BC
    assert len({frozenset((a, b)) for a, b, _ in pairs}) == 3


def test_the_strongest_pair_comes_first() -> None:
    """The operator wants the binding one, not an alphabetical list."""
    governor = PortfolioGovernor(settings=_settings(correlation_cluster_threshold=0.5))
    tight = _wave(80)
    looser = [v + n for v, n in zip(tight, _wave(80, phase=0.4, seed=9), strict=True)]
    returns = {"A": _series(tight), "B": _series(tight), "C": _series(looser)}

    pairs = governor.binding_pairs(returns)

    assert [p[2] for p in pairs] == sorted((p[2] for p in pairs), reverse=True)
