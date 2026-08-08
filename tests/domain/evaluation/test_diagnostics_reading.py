"""Reading the M37 diagnostics (M58).

M37 captured excursion, regime-at-entry, slippage, exit reason and costs on
every closed trade, and nothing has ever read any of it. These pin the two
properties that decide whether this section is worth having: it answers the
questions in the order they get asked, and it refuses to average a sample too
thin to mean anything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.domain.evaluation.diagnostics import (
    format_diagnostics_section,
    summarise_diagnostics,
)
from qat.domain.performance.metrics import MIN_TRADES_FOR_STATS
from qat.domain.performance.trades import ClosedTrade

_BASE = datetime(2026, 8, 1, 14, 0, tzinfo=UTC)


def _trade(
    *,
    pnl_per_share: float = 10.0,
    stop_distance: float = 5.0,
    exit_reason: str | None = "stop",
    regime: str | None = "bull",
    best: float | None = None,
    worst: float | None = None,
    reference: float | None = None,
    days: float = 3.0,
    entry_cost: float = 0.0,
    exit_cost: float = 0.0,
    quantity: float = 10.0,
) -> ClosedTrade:
    entry = 100.0
    return ClosedTrade(
        symbol="AAA",
        strategy="swing",
        quantity=quantity,
        entry_price=entry,
        exit_price=entry + pnl_per_share,
        stop_price=entry - stop_distance if stop_distance else None,
        opened_at=_BASE,
        closed_at=_BASE + timedelta(days=days),
        entry_cost=entry_cost,
        exit_cost=exit_cost,
        exit_reason=exit_reason,
        regime_at_entry=regime,
        best_price=best,
        worst_price=worst,
        reference_price=reference,
    )


def _enough(**kwargs) -> list[ClosedTrade]:
    return [_trade(**kwargs) for _ in range(MIN_TRADES_FOR_STATS)]


def test_no_trades_reads_as_nothing_to_read():
    section = format_diagnostics_section(summarise_diagnostics([]))
    assert "No closed trades yet" in section


def test_the_exit_mix_is_exact_at_any_sample_size():
    """The counts are the part that answers "what is actually ending these
    trades", and a count of one is still a fact."""
    summary = summarise_diagnostics([_trade(exit_reason="stop", pnl_per_share=-5.0)])

    assert summary.exits.counts == {"stop": 1}
    assert summary.exits.total == 1

    section = format_diagnostics_section(summary)
    assert "| stop | 1 |" in section


def test_averages_are_withheld_below_the_threshold():
    """The live case today: one closed trade. A mean of one invites being read
    as a result, and this system has exactly one result it would be easy to
    over-read."""
    summary = summarise_diagnostics([_trade(best=112.0, worst=98.0)])

    assert summary.sufficient is False
    assert summary.mean_mfe_r is None
    assert summary.mean_given_back_r is None

    section = format_diagnostics_section(summary)
    assert "Averages are withheld" in section
    assert "Excursion" not in section


def test_averages_appear_once_the_sample_is_large_enough():
    summary = summarise_diagnostics(_enough(best=112.0, worst=98.0))

    assert summary.sufficient is True
    assert summary.mean_mfe_r is not None
    section = format_diagnostics_section(summary)
    assert "Excursion" in section


def test_give_back_is_the_gap_between_the_best_price_and_the_close():
    """The finding that shaped the whole exit discussion, measured on real
    trades rather than on a replay."""
    # Entry 100, stop 95 so R = 5. Best 115 = +3R. Closed +10 = +2R.
    summary = summarise_diagnostics(_enough(pnl_per_share=10.0, best=115.0))

    assert summary.mean_mfe_r == 3.0
    assert summary.mean_realised_r == 2.0
    assert summary.mean_given_back_r == 1.0
    assert summary.held_past_best == MIN_TRADES_FOR_STATS


def test_a_trade_that_closed_at_its_own_high_gave_nothing_back():
    """Otherwise "held past its best" counts every trade that ever existed."""
    summary = summarise_diagnostics(_enough(pnl_per_share=10.0, best=110.0))

    assert summary.mean_given_back_r == 0.0
    assert summary.held_past_best == 0


def test_winners_are_measured_for_how_near_a_loss_they_came():
    """A winner that spent its life at -0.9R is a different fact from one that
    never traded against, and the average result hides it entirely."""
    summary = summarise_diagnostics(_enough(pnl_per_share=10.0, worst=95.5))

    assert summary.mean_mae_r_on_winners is not None
    assert summary.mean_mae_r_on_winners < 0
    section = format_diagnostics_section(summary)
    assert "near a loss the winners came" in section


def test_a_missing_field_abstains_rather_than_counting_as_zero():
    """A zero MAE would read as "never went against", which is the opposite of
    "not recorded" - and it would drag every average toward zero."""
    summary = summarise_diagnostics(_enough(best=None, worst=None, reference=None))

    assert summary.mean_mfe_r is None
    assert summary.mean_mae_r_on_winners is None
    assert summary.mean_entry_slippage is None
    assert "mfe_r" in summary.unrecorded_fields
    assert "mae_r" in summary.unrecorded_fields
    assert "entry_slippage" in summary.unrecorded_fields


def test_an_unstopped_trade_is_excluded_from_r_not_counted_as_breakeven():
    trades = _enough() + [_trade(stop_distance=0.0)]
    summary = summarise_diagnostics(trades)

    assert summary.trades == MIN_TRADES_FOR_STATS + 1
    assert summary.measurable == MIN_TRADES_FOR_STATS


def test_outcomes_are_grouped_by_the_regime_they_were_opened_in():
    """The only way the regime gate can ever earn or lose its place."""
    trades = [_trade(regime="bull", pnl_per_share=10.0) for _ in range(3)]
    trades += [_trade(regime="high_vol", pnl_per_share=-5.0) for _ in range(2)]

    summary = summarise_diagnostics(trades)

    assert summary.by_regime["bull"] == (3, 2.0)
    assert summary.by_regime["high_vol"] == (2, -1.0)


def test_an_adopted_trade_with_no_regime_is_not_invented_a_regime():
    summary = summarise_diagnostics(_enough(regime=None))

    assert summary.by_regime == {}
    assert "regime_at_entry" in summary.unrecorded_fields


def test_costs_are_reported_as_a_share_of_the_risk_taken():
    """The number the sizing argument turned on: a round trip against what was
    actually put at hazard, not against notional."""
    # R = 5 per share on 10 shares = $50 at risk. $5 of costs is 10% of that.
    summary = summarise_diagnostics(_enough(entry_cost=2.5, exit_cost=2.5))

    assert summary.mean_cost_share_of_risk == 0.10


def test_an_unrecorded_exit_reason_is_named_rather_than_dropped():
    summary = summarise_diagnostics([_trade(exit_reason=None)])

    assert "unrecorded" in summary.exits.counts
    assert "exit_reason" in summary.unrecorded_fields
