"""Reading the M37 diagnostics, which nothing has ever read (M58).

Every closed trade records where it was taken, how far it went against before
it resolved, how far in favour it got, what ended it, what it slipped on entry
and what it cost. M37 captured all of it and stopped there - and "captured" has
been reported as "done" ever since, on the strength of a file nobody queries.

Built now, deliberately ahead of the evidence. The whole book time-stops
between 14 and 17 September, which delivers roughly ten closed trades inside
three days. Writing the analysis while that lands would mean reading the first
real evidence this system has produced through whatever could be assembled in
an afternoon.

What it answers, in the order the questions actually get asked:

* what ENDS a trade, and what each ending is worth - the exit mix is the single
  most decision-relevant thing here, because a book whose trades all die of the
  time stop is not running the strategy anybody designed;
* how much of the best price was handed back, measured on real trades rather
  than a replay;
* how near a loss the winners came, because a winner that spent its life at
  -0.9R is a different fact from one that never traded against;
* whether the regime a trade was opened in says anything about how it ended,
  which is the only way the regime gate can ever earn or lose its place;
* what entry actually slipped against the price it was sized on, which is the
  cost model's own assumption measured rather than assumed.

**It refuses to compute statistics from a thin sample**, on the same rule as
`compute_stats`: counts are always exact and always shown, averages appear only
once there are `MIN_TRADES_FOR_STATS` of them. With one closed trade on record
this section is currently a promise rather than a finding, and it says so
rather than printing a mean of one and inviting it to be read as a result.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import fmean
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    # Behind TYPE_CHECKING because importing it for real is a cycle:
    # `qat.domain.performance.__init__` imports the reporter, which imports the
    # reports module, which imports this one. It is only ever an annotation
    # here, and `from __future__ import annotations` keeps those as strings.
    #
    # The full suite passed with this as a plain import - pytest happened to
    # reach `performance` first - and it failed the moment a test imported this
    # module directly. An import order that works by luck is not a working
    # import order.
    from qat.domain.performance.trades import ClosedTrade

_UNRECORDED = "unrecorded"


def _min_trades_for_stats() -> int:
    """The shared threshold, imported at call time.

    `qat.domain.performance.__init__` imports the reporter, which imports the
    reports module, which imports this one - so taking this at module scope is
    a cycle. Deferred rather than duplicated: a second copy of the number would
    drift from the one `compute_stats` uses, and the two disagreeing about what
    counts as enough evidence is precisely the kind of quiet inconsistency this
    module exists to surface.
    """
    from qat.domain.performance.metrics import MIN_TRADES_FOR_STATS

    return MIN_TRADES_FOR_STATS


@dataclass(frozen=True, slots=True)
class ExitMix:
    """What ended trades, and what each ending was worth."""

    counts: dict[str, int]
    mean_r: dict[str, float]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True, slots=True)
class TradeDiagnostics:
    trades: int
    measurable: int
    """Trades carrying a risk-per-share, so R-denominated figures mean anything."""
    exits: ExitMix
    # Excursion. None until there are enough trades to average.
    mean_mfe_r: float | None = None
    mean_realised_r: float | None = None
    mean_given_back_r: float | None = None
    held_past_best: int = 0
    # How near a loss the winners came.
    mean_mae_r_on_winners: float | None = None
    worst_mae_r_on_winners: float | None = None
    # Regime at entry -> (count, mean R).
    by_regime: dict[str, tuple[int, float]] = field(default_factory=dict)
    # Execution reality against what sizing assumed.
    mean_entry_slippage: float | None = None
    mean_cost_share_of_risk: float | None = None
    mean_holding_days: float | None = None
    # Trades held through a scheduled earnings print, and what they were worth
    # against those that avoided one (M41).
    through_earnings: int = 0
    avoided_earnings: int = 0
    mean_r_through_earnings: float | None = None
    mean_r_avoiding_earnings: float | None = None
    unrecorded_fields: tuple[str, ...] = ()
    # Carried rather than looked up, so the summary and the section that
    # renders it cannot disagree about what counted as enough.
    min_trades: int = 5

    @property
    def sufficient(self) -> bool:
        return self.measurable >= self.min_trades


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def summarise_diagnostics(trades: list[ClosedTrade]) -> TradeDiagnostics:
    """Read what M37 has been writing.

    Every figure is guarded on the field it needs being present, because these
    are genuinely optional: a trade adopted from the broker has no regime at
    entry, and one opened before M37 has no excursion. A missing field abstains
    from its own statistic rather than defaulting to zero - a zero MAE would
    read as "never went against", which is the opposite of "not recorded".
    """
    exit_counts: Counter[str] = Counter()
    r_by_exit: dict[str, list[float]] = {}
    mfe: list[float] = []
    realised: list[float] = []
    given_back: list[float] = []
    mae_winners: list[float] = []
    r_by_regime: dict[str, list[float]] = {}
    slippage: list[float] = []
    cost_share: list[float] = []
    holding: list[float] = []
    r_through: list[float] = []
    r_avoided: list[float] = []
    held_past_best = 0
    missing: Counter[str] = Counter()

    measurable = 0
    for trade in trades:
        r = trade.r_multiple
        if r is not None:
            measurable += 1

        reason = trade.exit_reason or _UNRECORDED
        exit_counts[reason] += 1
        if trade.exit_reason is None:
            missing["exit_reason"] += 1
        if r is not None:
            r_by_exit.setdefault(reason, []).append(r)

        holding.append(trade.holding_days)

        if trade.regime_at_entry:
            if r is not None:
                r_by_regime.setdefault(trade.regime_at_entry, []).append(r)
        else:
            missing["regime_at_entry"] += 1

        if trade.entry_slippage is None:
            missing["entry_slippage"] += 1
        else:
            slippage.append(trade.entry_slippage)

        if trade.mfe_r is None:
            missing["mfe_r"] += 1
        elif r is not None:
            mfe.append(trade.mfe_r)
            realised.append(r)
            given_back.append(trade.mfe_r - r)
            # Strictly better than where it closed, so a trade that exited at
            # its own high is not counted as having given anything back.
            if trade.mfe_r > r:
                held_past_best += 1

        if trade.mae_r is None:
            missing["mae_r"] += 1
        elif r is not None and r > 0:
            mae_winners.append(trade.mae_r)

        risk = trade.risk_per_share
        if risk is not None and risk > 0 and trade.quantity > 0:
            cost_share.append(trade.costs / (risk * trade.quantity))

        # Held through a print, or not, or unknowable - three states, kept as
        # three (M41). An unknown date is not a "no": an ETF has no earnings
        # and an adopted position was never sized against a calendar.
        through = trade.held_through_earnings
        if through is None:
            missing["earnings_at_entry"] += 1
        elif r is not None:
            (r_through if through else r_avoided).append(r)

    threshold = _min_trades_for_stats()
    enough = measurable >= threshold
    return TradeDiagnostics(
        min_trades=threshold,
        trades=len(trades),
        measurable=measurable,
        exits=ExitMix(
            counts=dict(exit_counts.most_common()),
            mean_r={reason: fmean(values) for reason, values in r_by_exit.items() if values},
        ),
        mean_mfe_r=_mean(mfe) if enough else None,
        mean_realised_r=_mean(realised) if enough else None,
        mean_given_back_r=_mean(given_back) if enough else None,
        held_past_best=held_past_best,
        mean_mae_r_on_winners=_mean(mae_winners) if enough else None,
        worst_mae_r_on_winners=min(mae_winners) if mae_winners and enough else None,
        by_regime={
            regime: (len(values), fmean(values)) for regime, values in sorted(r_by_regime.items())
        },
        mean_entry_slippage=_mean(slippage) if enough else None,
        mean_cost_share_of_risk=_mean(cost_share) if enough else None,
        mean_holding_days=_mean(holding) if enough else None,
        # Counts unconditionally: "three of ten were held through a print" is
        # exact and useful long before any average is.
        through_earnings=len(r_through),
        avoided_earnings=len(r_avoided),
        mean_r_through_earnings=_mean(r_through) if enough else None,
        mean_r_avoiding_earnings=_mean(r_avoided) if enough else None,
        unrecorded_fields=tuple(sorted(missing)),
    )


def format_diagnostics_section(d: TradeDiagnostics) -> str:
    """The section as it appears in a report."""
    lines = ["### What the closed trades say", ""]

    if not d.trades:
        lines.append("No closed trades yet, so nothing to read.")
        return "\n".join(lines) + "\n"

    # Counts first and unconditionally. They are exact at any sample size, and
    # they are the part that answers "what is actually ending these trades".
    lines.append(f"{d.trades} closed trade(s), {d.measurable} with a measurable R.")
    lines.append("")
    lines.append("| Ended by | Trades | Mean R |")
    lines.append("|---|---|---|")
    for reason, count in d.exits.counts.items():
        mean = d.exits.mean_r.get(reason)
        lines.append(f"| {reason} | {count} | {'-' if mean is None else f'{mean:+.2f}'} |")
    lines.append("")

    if not d.sufficient:
        lines.append(
            f"**Averages are withheld below {d.min_trades} measurable trades.** The counts "
            "above are exact; a mean of one or two trades is noise wearing a number's clothes, and "
            "this system already has one result it would be easy to over-read."
        )
        if d.unrecorded_fields:
            lines.append("")
            lines.append("Not recorded on every trade: " + ", ".join(d.unrecorded_fields) + ".")
        return "\n".join(lines) + "\n"

    if d.mean_mfe_r is not None and d.mean_realised_r is not None:
        lines.append(
            f"**Excursion.** Reached {d.mean_mfe_r:+.2f}R at best, kept "
            f"{d.mean_realised_r:+.2f}R - giving back {d.mean_given_back_r:.2f}R. "
            f"{d.held_past_best} of {d.measurable} trades were still open after their "
            "best price."
        )
        lines.append("")

    if d.mean_mae_r_on_winners is not None:
        lines.append(
            f"**How near a loss the winners came.** Mean worst excursion on winning trades "
            f"{d.mean_mae_r_on_winners:.2f}R, deepest {d.worst_mae_r_on_winners:.2f}R. A winner "
            "that spent its life near its stop is a different fact from one that never traded "
            "against, and the average result hides it."
        )
        lines.append("")

    if d.by_regime:
        lines.append("| Regime at entry | Trades | Mean R |")
        lines.append("|---|---|---|")
        for regime, (count, mean) in d.by_regime.items():
            lines.append(f"| {regime} | {count} | {mean:+.2f} |")
        lines.append("")

    if d.through_earnings or d.avoided_earnings:
        line = (
            f"**Earnings.** {d.through_earnings} of "
            f"{d.through_earnings + d.avoided_earnings} datable trades were held through a "
            "scheduled announcement"
        )
        if d.mean_r_through_earnings is not None and d.mean_r_avoiding_earnings is not None:
            line += (
                f" - {d.mean_r_through_earnings:+.2f}R against "
                f"{d.mean_r_avoiding_earnings:+.2f}R for those that avoided one"
            )
        lines.append(line + ".")
        lines.append("")

    execution: list[str] = []
    if d.mean_entry_slippage is not None:
        execution.append(f"entry slipped {d.mean_entry_slippage:+.4f} against the sizing price")
    if d.mean_cost_share_of_risk is not None:
        execution.append(f"costs took {d.mean_cost_share_of_risk:.1%} of the risk")
    if d.mean_holding_days is not None:
        execution.append(f"held {d.mean_holding_days:.1f} days on average")
    if execution:
        lines.append("**Execution.** " + "; ".join(execution) + ".")
        lines.append("")

    if d.unrecorded_fields:
        lines.append("Not recorded on every trade: " + ", ".join(d.unrecorded_fields) + ".")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["ExitMix", "TradeDiagnostics", "format_diagnostics_section", "summarise_diagnostics"]
