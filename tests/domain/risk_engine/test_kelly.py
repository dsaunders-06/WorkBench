from __future__ import annotations

import pytest

from qat.domain.risk_engine.kelly import compute_fractional_kelly, compute_kelly_fraction


def test_positive_edge_gives_positive_kelly_fraction():
    assert compute_kelly_fraction(0.6, 2.0) == pytest.approx(0.4)


def test_negative_edge_clips_to_zero():
    assert compute_kelly_fraction(0.4, 1.0) == 0.0


def test_zero_or_negative_win_loss_ratio_returns_zero():
    assert compute_kelly_fraction(0.6, 0.0) == 0.0
    assert compute_kelly_fraction(0.6, -1.0) == 0.0


def test_fractional_kelly_scales_by_fraction():
    f_star = compute_kelly_fraction(0.6, 2.0)
    assert compute_fractional_kelly(0.6, 2.0, 0.5) == pytest.approx(0.5 * f_star)


def test_fractional_kelly_zero_when_no_edge():
    assert compute_fractional_kelly(0.3, 1.0, 0.5) == 0.0
