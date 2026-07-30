"""Synthetic archetypes standing in for the paper's named historical periods
(2008, 2020, 2013 taper, 2017 low-vol) - there is no real market-data
connection yet (IBKR is M7), so these mimic each period's defining shape
rather than replaying the literal historical series."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent, MarketDataEvent, RegimeEvent
from qat.domain.regime import Regime
from qat.domain.regime_engine.engine import RegimeEngine

_ENGINE_LOGGER = "qat.domain.regime_engine.engine"


async def _run_archetype(
    closes: list[float], vix: list[float], curve: list[float], credit_spread: float = 1.0
) -> list[RegimeEvent]:
    bus = EventBus()
    received: list[RegimeEvent] = []

    async def handler(event: RegimeEvent) -> None:
        received.append(event)

    bus.subscribe(RegimeEvent, handler)
    engine = RegimeEngine(bus, benchmark_symbol="SPY", min_fit_bars=60, refit_interval_bars=20)
    await engine.start()

    start = datetime(2020, 1, 1, tzinfo=UTC)
    for i, (close, vix_level, curve_level) in enumerate(zip(closes, vix, curve, strict=True)):
        ts = start + timedelta(days=i)
        await bus.publish(MacroEvent(series="VIXCLS", value=vix_level, ts=ts))
        await bus.publish(MacroEvent(series="T10Y3M", value=curve_level, ts=ts))
        await bus.publish(MacroEvent(series="BAA10Y", value=credit_spread, ts=ts))
        await bus.publish(MarketDataEvent(symbol="SPY", price=close, volume=1_000_000.0, ts=ts))

    await engine.stop()
    return received


def _crash_archetype(
    n_calm: int,
    n_crash: int,
    calm_vix: float,
    crash_vix: float,
    curve_before: float,
    curve_during: float,
    seed: int = 0,
) -> tuple[list[float], list[float], list[float]]:
    rng = np.random.default_rng(seed)
    calm = [100.0]
    for _ in range(n_calm):
        calm.append(calm[-1] * (1 + rng.normal(0.0004, 0.003)))
    crash = [calm[-1]]
    for _ in range(n_crash):
        crash.append(crash[-1] * (1 + rng.normal(-0.02, 0.03)))
    closes = calm + crash[1:]
    vix = [calm_vix] * len(calm) + [crash_vix] * (len(crash) - 1)
    curve = [curve_before] * len(calm) + [curve_during] * (len(crash) - 1)
    return closes, vix, curve


@pytest.mark.asyncio
async def test_archetype_2008_like_crash_lands_in_stress_regimes():
    closes, vix, curve = _crash_archetype(
        n_calm=150, n_crash=60, calm_vix=14.0, crash_vix=45.0, curve_before=1.5, curve_during=-0.5
    )
    events = await _run_archetype(closes, vix, curve)

    assert events, "expected at least one RegimeEvent once enough history accumulated"
    final_label = Regime(events[-1].label)
    assert final_label in {Regime.BEAR, Regime.HIGH_VOL, Regime.RECESSION}


@pytest.mark.asyncio
async def test_archetype_2020_like_crash_lands_in_high_vol_or_bear():
    closes, vix, curve = _crash_archetype(
        n_calm=100, n_crash=25, calm_vix=13.0, crash_vix=60.0, curve_before=0.3, curve_during=0.1
    )
    events = await _run_archetype(closes, vix, curve)

    assert events
    final_label = Regime(events[-1].label)
    assert final_label in {Regime.BEAR, Regime.HIGH_VOL}


@pytest.mark.asyncio
async def test_archetype_2017_like_low_vol_bull_favours_calm_labels():
    rng = np.random.default_rng(1)
    closes = [100.0]
    for _ in range(220):
        closes.append(closes[-1] * (1 + rng.normal(0.0006, 0.0015)))
    # Small realistic jitter (real VIX/curve readings are never perfectly flat)
    # also gives the HMM's EM fit better-conditioned data - a handful of exactly
    # constant columns made convergence, and therefore the fitted result,
    # unstable across runs (see the majority-vote comment below).
    vix = [12.0 + rng.normal(0, 0.3) for _ in closes]
    curve = [1.2 + rng.normal(0, 0.03) for _ in closes]

    events = await _run_archetype(closes, vix, curve)

    assert events
    # Assert on the majority label across the run, not just the final bar: the
    # HMM clusters states relative to the fitted dataset's own distribution, so
    # even an overall-calm series has a "locally choppier" cluster, and whichever
    # bar happens to land there last can tip a single-bar assertion either way.
    # Sideways is included alongside Low-Vol/Bull/Recovery: paper §9.1 describes
    # Low-Vol as "calm, often trending" and Sideways as "no sustained trend" - a
    # gentle, quiet drift like this archetype can reasonably land on either side
    # of that line, and both are equally "calm" outcomes (neither is a stress read).
    calm_labels = {Regime.BULL, Regime.LOW_VOL, Regime.RECOVERY, Regime.SIDEWAYS}
    calm_count = sum(1 for e in events if Regime(e.label) in calm_labels)
    assert calm_count / len(events) >= 0.6


@pytest.mark.asyncio
async def test_archetype_2013_taper_like_scare_does_not_reach_recession():
    # a moderate vol/yield wobble with no real breakdown - should not be
    # mistaken for a genuine recession
    rng = np.random.default_rng(3)
    closes = [100.0]
    for _ in range(180):
        closes.append(closes[-1] * (1 + rng.normal(0.0002, 0.006)))
    vix = [16.0 + rng.normal(0, 2) for _ in closes]
    curve = [1.0 + rng.normal(0, 0.1) for _ in closes]

    events = await _run_archetype(closes, vix, curve)

    assert events
    final_label = Regime(events[-1].label)
    assert final_label != Regime.RECESSION


@pytest.mark.asyncio
async def test_hysteresis_limits_flips_over_a_simulated_month():
    rng = np.random.default_rng(2)
    closes = [100.0]
    for _ in range(150):
        closes.append(closes[-1] * (1 + rng.normal(0.0002, 0.004)))
    vix = [15.0 + rng.normal(0, 1) for _ in closes]
    curve = [1.0 + rng.normal(0, 0.05) for _ in closes]

    events = await _run_archetype(closes, vix, curve)
    last_month = events[-21:] if len(events) >= 21 else events
    flips = sum(
        1 for i in range(1, len(last_month)) if last_month[i].label != last_month[i - 1].label
    )
    assert flips <= 5


# --- Logging (M27a) -------------------------------------------------------
#
# The engine had no logger at all until M27a. On 29 July it classified the
# market as low-vol, which gated the only promoted strategy off for a full
# session, and that had to be reconstructed afterwards from a blank UI field.


@pytest.mark.asyncio
async def test_every_transition_is_logged_with_both_labels(caplog):
    closes, vix, curve = _crash_archetype(
        n_calm=150, n_crash=60, calm_vix=14.0, crash_vix=45.0, curve_before=1.5, curve_during=-0.5
    )

    with caplog.at_level(logging.INFO, logger=_ENGINE_LOGGER):
        events = await _run_archetype(closes, vix, curve)

    transitions = [
        record.getMessage() for record in caplog.records if record.getMessage().startswith("REGIME")
    ]
    labels = [event.label for event in events]
    expected = 1 + sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])

    assert len(transitions) == expected
    assert "-> " in transitions[0]
    # The consequence, not just the label: a transition decides which
    # strategies are eligible to trade at all.
    assert "skipped" in transitions[0]


@pytest.mark.asyncio
async def test_warmup_progress_is_logged_so_a_blank_regime_is_explained(caplog):
    with caplog.at_level(logging.INFO, logger=_ENGINE_LOGGER):
        events = await _run_archetype(
            closes=[100.0 + i for i in range(25)],
            vix=[14.0] * 25,
            curve=[1.5] * 25,
        )

    assert not events
    assert any("warming up" in record.getMessage() for record in caplog.records)
    assert any("20/60 bars" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_constant_macro_columns_are_named_before_they_break_the_fit(caplog):
    """The 28 July crash, diagnosed rather than raised. Fitting 60 one-minute
    bars leaves the three daily FRED columns constant across every row, which
    makes the covariance matrix singular - `startprob_ must sum to 1 (got
    nan)`. The columns that never moved are the diagnosis.

    The values here are real FRED prints (VIX 18.21, T10Y3M 0.84, BAA10Y 1.62)
    and deliberately not round numbers: sixty copies of 14.0 have a standard
    deviation of exactly 0.0, sixty copies of 18.21 have 3.5e-15, so a
    variance-based check written against round test data passes while
    reporting nothing on the live feed.
    """
    rng = np.random.default_rng(5)
    closes = [100.0]
    for _ in range(80):
        closes.append(closes[-1] * (1 + rng.normal(0.0, 0.002)))

    with caplog.at_level(logging.INFO, logger=_ENGINE_LOGGER):
        await _run_archetype(
            closes=closes,
            vix=[18.21] * len(closes),
            curve=[0.84] * len(closes),
            credit_spread=1.62,
        )

    warnings = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert warnings, "a constant macro column must be named before it breaks the fit"
    named = next(msg for msg in warnings if "never moved" in msg)
    assert "vix_level" in named
    assert "yield_curve_slope" in named
    assert "credit_spread" in named


@pytest.mark.asyncio
async def test_a_failed_fit_is_reported_and_publishes_nothing(caplog):
    bus = EventBus()
    received: list[RegimeEvent] = []

    async def handler(event: RegimeEvent) -> None:
        received.append(event)

    bus.subscribe(RegimeEvent, handler)
    engine = RegimeEngine(bus, benchmark_symbol="SPY", min_fit_bars=60, refit_interval_bars=20)

    def _explode(matrix):
        raise ValueError("startprob_ must sum to 1 (got nan)")

    engine._hmm.fit = _explode  # type: ignore[method-assign]
    await engine.start()

    start = datetime(2020, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(6)
    price = 100.0
    with caplog.at_level(logging.INFO, logger=_ENGINE_LOGGER):
        for i in range(70):
            price *= 1 + rng.normal(0.0, 0.004)
            ts = start + timedelta(days=i)
            await bus.publish(MacroEvent(series="VIXCLS", value=14.0 + i * 0.1, ts=ts))
            await bus.publish(MarketDataEvent(symbol="SPY", price=price, volume=1e6, ts=ts))
    await engine.stop()

    assert not received, "a dead classifier must not publish a regime"
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert errors, "a failed fit must be reported, not swallowed by the bus"
    assert "fit FAILED" in errors[0].getMessage()
    # The spread per feature is what identifies which column caused it.
    assert "log_return=" in errors[0].getMessage()
