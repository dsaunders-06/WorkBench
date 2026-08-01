"""Sizing on measured results rather than invented constants (M35).

SignalToOrderBridge passed win_rate=0.55 and win_loss_ratio=1.5 into Kelly
sizing as fixed values, described in its own docstring as "clearly documented
placeholders, not real edge estimates". Every position size this system has
ever taken traced back to those two numbers.

The care here is all in when NOT to switch. Kelly is violently sensitive to
win rate - at a 1.5 win/loss ratio, moving from 0.55 to 0.75 roughly triples
the fraction - so a strategy that opened with four winners would size up hard
on noise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.domain.performance.edge import EdgeEstimator
from qat.domain.performance.trades import ClosedTrade


class _Ledger:
    def __init__(self, trades: list[ClosedTrade]) -> None:
        self._trades = trades

    def closed_trades(self, strategy: str | None = None) -> list[ClosedTrade]:
        if strategy is None:
            return list(self._trades)
        return [t for t in self._trades if t.strategy == strategy]


def _trade(pnl: float, strategy: str = "swing", n: int = 0) -> ClosedTrade:
    """P&L is a property of the prices, so it is expressed through them."""
    return ClosedTrade(
        symbol="AAA",
        strategy=strategy,
        quantity=10.0,
        entry_price=100.0,
        exit_price=100.0 + pnl / 10.0,
        stop_price=95.0,
        opened_at=datetime.now(UTC) - timedelta(days=60 - n),
        closed_at=datetime.now(UTC) - timedelta(days=40 - n),
    )


def _book(wins: int, losses: int, win_size: float = 150.0, loss_size: float = -100.0):
    trades = [_trade(win_size, n=i) for i in range(wins)]
    trades += [_trade(loss_size, n=wins + i) for i in range(losses)]
    return _Ledger(trades)


def _settings(**overrides) -> Settings:
    base = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_no_ledger_gives_exactly_the_old_behaviour():
    edge = EdgeEstimator(None, settings=_settings()).estimate("swing")

    assert edge.source == "default"
    assert edge.win_rate == 0.55
    assert edge.win_loss_ratio == 1.5


def test_a_small_sample_does_not_move_the_size():
    """Four winners is not an edge. Under Kelly it would be a large one."""
    estimator = EdgeEstimator(_book(wins=4, losses=0), settings=_settings(edge_min_trades=20))

    edge = estimator.estimate("swing")

    assert edge.source == "default"
    assert edge.win_rate == 0.55
    assert edge.trade_count == 4


def test_a_sufficient_sample_sizes_on_what_actually_happened():
    estimator = EdgeEstimator(_book(wins=12, losses=8), settings=_settings(edge_min_trades=20))

    edge = estimator.estimate("swing")

    assert edge.source == "measured"
    assert edge.trade_count == 20
    assert edge.win_rate == pytest.approx(0.60)
    assert edge.win_loss_ratio == pytest.approx(1.5)


def test_an_implausible_win_rate_is_clamped():
    """19 wins in 20 is a sample artefact, and Kelly would size for certainty."""
    estimator = EdgeEstimator(_book(wins=19, losses=1), settings=_settings(edge_min_trades=20))

    edge = estimator.estimate("swing")

    assert edge.source == "measured"
    assert edge.win_rate == pytest.approx(0.75)  # clamped down from 0.95


def test_an_outsized_winner_does_not_become_a_payoff_profile():
    estimator = EdgeEstimator(
        _book(wins=10, losses=10, win_size=5000.0, loss_size=-100.0),
        settings=_settings(edge_min_trades=20),
    )

    edge = estimator.estimate("swing")

    assert edge.win_loss_ratio == pytest.approx(4.0)  # clamped down from 50


def test_a_book_with_no_losses_falls_back_rather_than_dividing():
    """Not a payoff ratio - a sample too kind to learn from."""
    estimator = EdgeEstimator(_book(wins=25, losses=0), settings=_settings(edge_min_trades=20))

    edge = estimator.estimate("swing")

    assert edge.source == "default"


def test_each_strategy_is_measured_on_its_own_trades():
    ledger = _Ledger(
        [_trade(150.0, strategy="swing", n=i) for i in range(12)]
        + [_trade(-100.0, strategy="swing", n=12 + i) for i in range(8)]
        + [_trade(-100.0, strategy="breakout", n=20 + i) for i in range(3)]
    )
    estimator = EdgeEstimator(ledger, settings=_settings(edge_min_trades=20))

    assert estimator.estimate("swing").source == "measured"
    assert estimator.estimate("breakout").source == "default"


def test_a_losing_strategy_sizes_itself_down():
    """The point of the loop. A strategy that has not worked must not keep
    risking what one that had would."""
    from qat.domain.risk_engine.sizing import compute_fractional_kelly

    estimator = EdgeEstimator(_book(wins=6, losses=14), settings=_settings(edge_min_trades=20))
    edge = estimator.estimate("swing")

    measured = compute_fractional_kelly(edge.win_rate, edge.win_loss_ratio, 0.5)
    default = compute_fractional_kelly(0.55, 1.5, 0.5)

    assert edge.source == "measured"
    assert measured < default
