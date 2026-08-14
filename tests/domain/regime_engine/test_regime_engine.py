"""Synthetic archetypes standing in for the paper's named historical periods
(2008, 2020, 2013 taper, 2017 low-vol) - there is no real market-data
connection yet (IBKR is M7), so these mimic each period's defining shape
rather than replaying the literal historical series."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from qat.data.macro_fred import MacroHistory, MacroObservation
from qat.domain.bus import EventBus
from qat.domain.events import (
    MacroEvent,
    MarketDataEvent,
    RegimeEvent,
    RegimeHealthEvent,
)
from qat.domain.regime import Regime
from qat.domain.regime_engine.engine import RegimeEngine
from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES

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
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("REGIME ") and " -> " in record.getMessage()
    ]
    labels = [event.label for event in events]
    expected = 1 + sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])

    assert len(transitions) == expected
    assert "-> " in transitions[0]
    # The consequence, stated accurately (M57c). This previously asserted that
    # the line said strategies excluding the label "are now skipped" - which
    # pinned the pre-M27b mechanism into a test and is why the wrong message
    # survived the change to mass-based gating. The label governs SIZE; the
    # distribution governs eligibility.
    assert "exposure scalar" in transitions[0]
    assert "MASS" in transitions[0]
    assert (
        "skipped" not in transitions[0]
    ), "the label does not skip strategies - probability mass decides eligibility"


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


# --- Warm-start seeding (M27a) --------------------------------------------


def _daily_bars(days: int, seed: int = 11, start_price: float = 500.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    first = datetime(2026, 1, 2, 4, 0, tzinfo=UTC)  # Alpaca stamps daily bars at 04:00 UTC
    rows = []
    price = start_price
    for i in range(days):
        price *= 1 + rng.normal(0.0005, 0.01)
        rows.append(
            {
                "ts": first + timedelta(days=i),
                "open": price * 0.995,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1_000_000.0,
            }
        )
    return pd.DataFrame(rows)


def _macro_history(days: int) -> MacroHistory:
    """Real FRED shape: a daily reading per series that actually moves."""
    rng = np.random.default_rng(3)
    first = datetime(2026, 1, 1, tzinfo=UTC)
    observations = {}
    for series, level, scale in (
        ("VIXCLS", 18.0, 1.5),
        ("T10Y3M", 0.84, 0.05),
        ("BAA10Y", 1.62, 0.03),
    ):
        observations[series] = [
            MacroObservation(
                series=series,
                ts=first + timedelta(days=i),
                value=float(level + rng.normal(0, scale)),
            )
            for i in range(days)
        ]
    return MacroHistory(observations)


def test_seeding_makes_the_macro_columns_vary_across_rows():
    """The point of the as-of join. Paired with one constant value the three
    macro columns do not move, and a constant column is the singular covariance
    matrix that crashed the fit on 28 July."""
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")

    rows = engine.seed(_daily_bars(300), _macro_history(400))

    assert rows == 300
    matrix = engine._feature_builder.feature_matrix()
    for column in ("vix_level", "yield_curve_slope", "credit_spread"):
        index = FEATURE_NAMES.index(column)
        assert matrix[:, index].max() > matrix[:, index].min(), f"{column} never moved"


def test_seeding_pairs_each_bar_with_the_reading_current_on_its_own_date():
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    bars = _daily_bars(3)
    history = MacroHistory(
        {
            "VIXCLS": [
                MacroObservation(series="VIXCLS", ts=datetime(2026, 1, 2, tzinfo=UTC), value=14.0),
                MacroObservation(series="VIXCLS", ts=datetime(2026, 1, 4, tzinfo=UTC), value=25.0),
            ]
        }
    )

    engine.seed(bars, history)

    vix = engine._feature_builder.feature_matrix()[:, FEATURE_NAMES.index("vix_level")]
    # Bars are 2, 3 and 4 January: the 3rd carries the 2nd's reading forward,
    # and no bar sees a value published after it.
    assert list(vix) == [14.0, 14.0, 25.0]


@pytest.mark.asyncio
async def test_a_seeded_engine_classifies_on_the_first_live_bar():
    """Unseeded, a daily-bar regime engine needs min_fit_bars of *sessions* -
    about three months - before it can publish anything at all."""
    bus = EventBus()
    received: list[RegimeEvent] = []

    async def handler(event: RegimeEvent) -> None:
        received.append(event)

    bus.subscribe(RegimeEvent, handler)
    engine = RegimeEngine(bus, benchmark_symbol="SPY")
    bars = _daily_bars(300)
    engine.seed(bars, _macro_history(400))

    next_day = pd.Timestamp(bars["ts"].iloc[-1]).to_pydatetime() + timedelta(days=1)
    await engine.start()
    await bus.publish(MarketDataEvent(symbol="SPY", price=505.0, volume=1e6, ts=next_day))
    await engine.stop()

    assert len(received) == 1
    assert received[0].label in {regime.value for regime in Regime}


def test_breadth_is_seeded_only_from_symbols_covering_every_benchmark_date():
    """RegimeFeatureBuilder silently ignores a breadth symbol whose history is
    not exactly as long as the benchmark's, so a symbol short one day would
    vanish from breadth for the whole run."""
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    bars = _daily_bars(80)

    engine.seed(
        bars,
        _macro_history(200),
        {
            "AAPL": _daily_bars(80, seed=2),
            "MSFT": _daily_bars(80, seed=4),
            "SHORT": _daily_bars(40),
        },
    )

    breadth = engine._feature_builder.feature_matrix()[:, FEATURE_NAMES.index("breadth")]
    assert breadth.max() > breadth.min(), "breadth never moved despite two aligned symbols"


@pytest.mark.asyncio
async def test_a_session_of_ticks_adds_one_row_not_one_per_tick():
    """Otherwise the seeding is pointless: 390 intraday rows a day would swamp
    300 seeded daily ones inside a single session, restoring the very
    timeframe mismatch M27a exists to remove."""
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    bars = _daily_bars(120)
    engine.seed(bars, _macro_history(200))
    before = len(engine._feature_builder.feature_matrix())

    day = pd.Timestamp(bars["ts"].iloc[-1]).to_pydatetime() + timedelta(days=1, hours=9)
    for minute in range(390):
        await engine._on_market_data(
            MarketDataEvent(
                symbol="SPY",
                price=500.0 + minute * 0.01,
                volume=1e6,
                ts=day + timedelta(minutes=minute),
            )
        )

    matrix = engine._feature_builder.feature_matrix()
    assert len(matrix) == before + 1
    # The row tracks the session rather than freezing at its first tick.
    assert engine._benchmark_closes[-1] == pytest.approx(500.0 + 389 * 0.01)


@pytest.mark.asyncio
async def test_a_tick_inside_the_last_seeded_day_does_not_add_a_row():
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    bars = _daily_bars(120)
    engine.seed(bars, _macro_history(200))
    before = len(engine._feature_builder.feature_matrix())

    last_day = pd.Timestamp(bars["ts"].iloc[-1]).to_pydatetime()
    await engine._on_market_data(
        MarketDataEvent(symbol="SPY", price=999.0, volume=1e6, ts=last_day + timedelta(hours=10))
    )

    assert len(engine._feature_builder.feature_matrix()) == before
    assert engine._benchmark_closes[-1] == pytest.approx(999.0)


@pytest.mark.asyncio
async def test_seeding_refuses_after_a_bar_has_been_recorded():
    """Seeded rows appended after live ones would place months-old history
    after today, and the HMM fits the sequence in order."""
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    await engine._on_market_data(
        MarketDataEvent(symbol="SPY", price=500.0, volume=1.0, ts=datetime.now(UTC))
    )

    with pytest.raises(RuntimeError, match="before any bar"):
        engine.seed(_daily_bars(10), _macro_history(20))


# --- Health reporting (M27a item 4) ---------------------------------------


@pytest.mark.asyncio
async def test_a_failed_fit_reports_the_engine_as_down():
    """StrategyEngine falls open to its default regime, so a crashed
    classifier keeps the app trading with the gate silently disabled."""
    bus = EventBus()
    health: list[RegimeHealthEvent] = []

    async def handler(event: RegimeHealthEvent) -> None:
        health.append(event)

    bus.subscribe(RegimeHealthEvent, handler)
    engine = RegimeEngine(bus, benchmark_symbol="SPY")
    engine.seed(_daily_bars(120), _macro_history(200))
    engine._hmm.fit = _explode  # type: ignore[method-assign]
    await engine.start()

    await bus.publish(MarketDataEvent(symbol="SPY", price=500.0, volume=1e6, ts=datetime.now(UTC)))
    await engine.stop()

    assert health, "a dead classifier published nothing about being dead"
    assert health[-1].healthy is False
    assert "fit failed" in health[-1].reason


def _explode(matrix):
    raise ValueError("startprob_ must sum to 1 (got nan)")


@pytest.mark.asyncio
async def test_health_is_published_on_change_not_on_every_bar():
    """A classifier that is down stays down for every bar of the session, and
    a banner repainted identically four hundred times is one nobody reads."""
    bus = EventBus()
    health: list[RegimeHealthEvent] = []

    async def handler(event: RegimeHealthEvent) -> None:
        health.append(event)

    bus.subscribe(RegimeHealthEvent, handler)
    engine = RegimeEngine(bus, benchmark_symbol="SPY")
    bars = _daily_bars(300)
    engine.seed(bars, _macro_history(400))
    await engine.start()

    last = pd.Timestamp(bars["ts"].iloc[-1]).to_pydatetime()
    for day in range(1, 6):
        await bus.publish(
            MarketDataEvent(
                symbol="SPY", price=500.0 + day, volume=1e6, ts=last + timedelta(days=day)
            )
        )
    await engine.stop()

    assert len(health) == 1
    assert health[0].healthy is True


# --- Non-convergent fits (recording, not deciding) -------------------------
#
# `hmmlearn` printed "Model is not converging." during the ASX run. The fit
# still produced a classification and was still used, exactly as today - this
# only records that it happened, so a manifest built from the run can say so.


def _fit_matrix() -> np.ndarray:
    return np.zeros((10, len(FEATURE_NAMES)))


def test_non_convergent_fits_stays_zero_while_every_fit_converges():
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    engine._hmm.fit = lambda matrix: setattr(engine._hmm, "_converged", True)  # type: ignore[method-assign]

    assert engine._fit(_fit_matrix()) is True
    assert engine._fit(_fit_matrix()) is True
    assert engine.non_convergent_fits == 0


def test_non_convergent_fits_increments_once_per_refit_that_did_not_converge():
    """A fake `RegimeHMM`, per the brief - real non-convergent data is slow to
    construct and flaky to keep that way across hmmlearn versions."""
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    engine._hmm.fit = lambda matrix: setattr(engine._hmm, "_converged", False)  # type: ignore[method-assign]

    assert engine._fit(_fit_matrix()) is True, "still used, exactly as today"
    assert engine.non_convergent_fits == 1

    assert engine._fit(_fit_matrix()) is True
    assert engine.non_convergent_fits == 2


def test_a_failed_fit_does_not_count_as_non_convergent():
    """A fit that raises never reached `converged` at all - that is a
    different failure, already reported by `_report_health`, and must not be
    folded into a count that means "succeeded but was not confident"."""
    engine = RegimeEngine(EventBus(), benchmark_symbol="SPY")
    engine._hmm.fit = _explode  # type: ignore[method-assign]

    assert engine._fit(_fit_matrix()) is False
    assert engine.non_convergent_fits == 0
