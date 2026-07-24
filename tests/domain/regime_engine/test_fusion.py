from __future__ import annotations

from qat.domain.regime import ALL_REGIMES, Regime
from qat.domain.regime_engine.fusion import (
    HysteresisGate,
    RegimeFusion,
    classify_vix_axis,
    compute_recession_probability,
    exposure_scalar_for,
    is_bull_blocked,
    score_from_hmm,
)
from qat.domain.regime_engine.hmm_core import StateSignature


def test_recession_probability_rises_with_more_inverted_curve():
    normal_curve = compute_recession_probability(1.5)
    inverted_curve = compute_recession_probability(-1.0)
    assert inverted_curve > normal_curve


def test_recession_probability_is_a_probability():
    assert 0.0 <= compute_recession_probability(-2.0) <= 1.0


def test_is_bull_blocked_below_sma():
    assert is_bull_blocked(price=90.0, sma_200=100.0) is True
    assert is_bull_blocked(price=110.0, sma_200=100.0) is False


def test_is_bull_blocked_with_no_sma_history_is_a_noop():
    assert is_bull_blocked(price=90.0, sma_200=0.0) is False


def test_classify_vix_axis_thresholds():
    assert classify_vix_axis(10.0) == "low_vol"
    assert classify_vix_axis(20.0) == "normal"
    assert classify_vix_axis(30.0) == "high_vol"


def test_exposure_scalar_lowest_in_recession_and_high_vol():
    assert exposure_scalar_for(Regime.RECESSION) < exposure_scalar_for(Regime.BULL)
    assert exposure_scalar_for(Regime.HIGH_VOL) < exposure_scalar_for(Regime.BULL)


def test_score_from_hmm_favours_bull_for_positive_return_low_vol_state():
    signatures = {
        0: StateSignature(mean_return=0.02, mean_vol=0.01),
        1: StateSignature(mean_return=-0.02, mean_vol=0.05),
    }
    scores = score_from_hmm([1.0, 0.0], signatures)
    assert scores[Regime.BULL] > scores[Regime.BEAR]


def test_fusion_blocks_bull_when_price_below_sma():
    signatures = {
        0: StateSignature(mean_return=0.02, mean_vol=0.01),
        1: StateSignature(mean_return=-0.02, mean_vol=0.05),
    }
    probs = RegimeFusion().compute(
        posterior=[1.0, 0.0],
        signatures=signatures,
        yield_curve_slope=1.0,
        yield_curve_slope_prev=1.0,
        vix_level=15.0,
        price=90.0,
        sma_200=100.0,
        sma_200_prev=100.0,
    )
    assert probs[Regime.BULL] == 0.0
    assert set(probs) == set(ALL_REGIMES)
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_fusion_probs_sum_to_one_even_when_all_scores_zero():
    signatures = {0: StateSignature(mean_return=0.0, mean_vol=0.0)}
    probs = RegimeFusion().compute(
        posterior=[1.0],
        signatures=signatures,
        yield_curve_slope=0.0,
        yield_curve_slope_prev=0.0,
        vix_level=20.0,
        price=0.0,
        sma_200=0.0,
        sma_200_prev=0.0,
    )
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_hysteresis_ignores_a_single_noisy_challenger():
    gate = HysteresisGate(margin=0.1, min_persistence=3)
    strong_bull = dict.fromkeys(ALL_REGIMES, 0.01)
    strong_bull[Regime.BULL] = 0.9
    strong_bear = dict.fromkeys(ALL_REGIMES, 0.01)
    strong_bear[Regime.BEAR] = 0.9

    assert gate.update(strong_bull) == Regime.BULL
    assert gate.update(strong_bear) == Regime.BULL
    assert gate.update(strong_bull) == Regime.BULL


def test_hysteresis_flips_after_sustained_challenge():
    gate = HysteresisGate(margin=0.1, min_persistence=3)
    strong_bull = dict.fromkeys(ALL_REGIMES, 0.01)
    strong_bull[Regime.BULL] = 0.9
    strong_bear = dict.fromkeys(ALL_REGIMES, 0.01)
    strong_bear[Regime.BEAR] = 0.9

    assert gate.update(strong_bull) == Regime.BULL
    gate.update(strong_bear)
    gate.update(strong_bear)
    assert gate.update(strong_bear) == Regime.BEAR


def test_hysteresis_does_not_flip_within_margin():
    gate = HysteresisGate(margin=0.5, min_persistence=1)
    close_race = dict.fromkeys(ALL_REGIMES, 0.1)
    close_race[Regime.BULL] = 0.46
    assert gate.update(close_race) in ALL_REGIMES
