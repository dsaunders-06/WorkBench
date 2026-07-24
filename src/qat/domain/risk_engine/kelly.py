"""Kelly criterion sizing inputs (paper Appendix A):
f* = W - (1-W)/R  (win probability W, avg-win/avg-loss ratio R)
f  = c * f*        (fractional Kelly, c typically 1/2 or 1/4)
"""

from __future__ import annotations


def compute_kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
    """Raw Kelly fraction f*. Returns 0.0 (no bet) when the edge is
    non-positive or inputs are degenerate, rather than a negative fraction."""
    if win_loss_ratio <= 0:
        return 0.0
    f_star = win_rate - (1.0 - win_rate) / win_loss_ratio
    return max(0.0, f_star)


def compute_fractional_kelly(win_rate: float, win_loss_ratio: float, fraction: float) -> float:
    """f = c * f* - the fraction of equity actually risked (paper: half/quarter Kelly)."""
    return fraction * compute_kelly_fraction(win_rate, win_loss_ratio)
