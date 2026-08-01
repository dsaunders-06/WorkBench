"""Run Monte Carlo and walk-forward against a strategy, headless (M33).

Both have existed since M4 and have only ever been reachable by clicking
through the Workbench one symbol at a time. That is not a way to find out
whether a strategy survives contact with its own costs: it answers for one
symbol, on whatever cost model that screen happened to build, and leaves no
artefact to compare against next month.

This runs the same two functions across the whole watchlist, with the cost
model the LIVE system reasons with, and prints numbers that can be pasted into
a decision.

    python scripts/validate_strategy.py swing
    python scripts/validate_strategy.py swing --symbols 40 --simulations 5000

Costs are the point. `CostModel()` defaults `min_commission` to 0.0 so that
pre-M27 backtests keep their old numbers, and the Workbench was building it
that way - so every result this application has ever displayed was costed with
no per-transaction floor against a configured 6.60. Both models are reported
side by side here, because the gap between them IS the finding.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd  # noqa: E402

from qat.config import Settings  # noqa: E402
from qat.data.history import resolve_history_source  # noqa: E402
from qat.data.universe import resolve_watchlist  # noqa: E402
from qat.domain.backtester.costs import CostModel  # noqa: E402
from qat.domain.backtester.monte_carlo import run_monte_carlo  # noqa: E402
from qat.domain.backtester.results import Trade  # noqa: E402
from qat.domain.backtester.signal_adapter import generate_signal_series  # noqa: E402
from qat.domain.backtester.sizing import FixedFractionalSizer  # noqa: E402
from qat.domain.backtester.vectorized_engine import VectorizedBacktester  # noqa: E402
from qat.domain.backtester.walk_forward import run_walk_forward  # noqa: E402
from qat.presentation.runtime import default_strategies, resolve_fundamentals_source  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("validate")


@dataclass(slots=True)
class SymbolRun:
    symbol: str
    trades: list[Trade]
    metrics: dict[str, float]
    bars: int


async def _load(
    symbol: str, strategy, history, fundamentals_source
) -> tuple[pd.DataFrame, pd.Series] | None:
    try:
        bars = await history.get_daily_bars(symbol)
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not end the run
        logger.warning("%s: no bars (%s)", symbol, exc)
        return None
    if bars is None or len(bars) < 60:
        logger.warning("%s: only %s bars, skipping", symbol, 0 if bars is None else len(bars))
        return None
    fundamentals = await fundamentals_source.get_fundamentals(symbol)
    return bars, generate_signal_series(strategy, symbol, bars, fundamentals)


def _percent(value: float) -> str:
    return f"{value:>8.2%}"


def _report_costs(
    label: str, runs: list[SymbolRun], starting_equity: float, simulations: int
) -> None:
    trades = [t for run in runs for t in run.trades]
    print(f"\n--- {label} " + "-" * (58 - len(label)))
    if not trades:
        print("  no trades")
        return

    wins = [t for t in trades if t.pnl > 0]
    total = sum(t.pnl for t in trades)
    print(f"  symbols traded      {sum(1 for r in runs if r.trades):>8d} of {len(runs)}")
    print(f"  trades              {len(trades):>8d}")
    print(f"  win rate            {len(wins) / len(trades):>8.1%}")
    print(f"  total P&L           {total:>8,.0f}  on {starting_equity:,.0f} per symbol")
    print(f"  mean per trade      {total / len(trades):>8,.2f}")

    mc = run_monte_carlo(trades, starting_equity=starting_equity, n_simulations=simulations)
    print(f"  Monte Carlo ({simulations:,} resamples of the trade sequence)")
    print(
        f"    final equity      P5 {mc.final_equity_p5:>10,.0f}   "
        f"P50 {mc.final_equity_p50:>10,.0f}   P95 {mc.final_equity_p95:>10,.0f}"
    )
    print(
        f"    max drawdown      P5 {_percent(mc.max_drawdown_p5)}   "
        f"P50 {_percent(mc.max_drawdown_p50)}   P95 {_percent(mc.max_drawdown_p95)}"
    )
    ruin = (mc.final_equity_p5 / starting_equity) - 1.0
    print(f"    P5 outcome        {ruin:>8.2%} on starting equity")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy", help="strategy name, e.g. swing")
    parser.add_argument("--symbols", type=int, default=25, help="how many watchlist symbols")
    parser.add_argument("--simulations", type=int, default=2000)
    # The backtester gives each symbol the WHOLE account, so a position is far
    # larger than any this system takes live - and a fixed per-transaction fee
    # is trivial on a large position and ruinous on a small one. Sweeping the
    # equity is the only way to see the floor actually bite.
    parser.add_argument("--equity", type=float, default=None, help="starting equity per symbol")
    parser.add_argument("--in-sample", type=int, default=120, help="walk-forward in-sample bars")
    parser.add_argument("--out-sample", type=int, default=60, help="walk-forward out-sample bars")
    args = parser.parse_args()

    settings = Settings()
    strategy = next((s for s in default_strategies() if s.name == args.strategy), None)
    if strategy is None:
        print(f"No strategy named {args.strategy!r}")
        return 1

    history = resolve_history_source(settings)
    universe = resolve_watchlist(settings)
    symbols = list(universe)[: args.symbols]
    fundamentals_source = resolve_fundamentals_source(settings, history, universe)

    configured = CostModel.from_settings(settings)
    print(f"Strategy   {strategy.name}")
    print(f"Symbols    {len(symbols)} of {len(universe)} on the watchlist")
    print(f"History    {type(history).__name__}")
    print(
        f"Costs      configured: {configured.commission_bps:.1f}bps commission, "
        f"{configured.slippage_bps:.1f}bps slippage, {configured.min_commission:.2f} floor"
    )
    print(f"           workbench-as-was: {CostModel().min_commission:.2f} floor")

    loaded: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
    for symbol in symbols:
        result = await _load(symbol, strategy, history, fundamentals_source)
        if result is not None:
            loaded[symbol] = result
    if not loaded:
        print("\nNo symbol produced usable bars.")
        return 1

    sizer = FixedFractionalSizer(settings=settings)
    equity_kwargs = {} if args.equity is None else {"starting_equity": args.equity}
    for label, model in (
        ("costed as configured (6.60 floor)", configured),
        ("costed as the Workbench did (no floor)", CostModel()),
    ):
        engine = VectorizedBacktester(model, sizer, **equity_kwargs)
        runs = [
            SymbolRun(symbol, r.trades, r.metrics, len(bars))
            for symbol, (bars, signals) in loaded.items()
            for r in [engine.run(symbol, bars, signals)]
        ]
        _report_costs(label, runs, engine.starting_equity, args.simulations)

    # --- walk-forward, on the configured model only ---------------------------
    print("\n--- walk-forward, configured costs " + "-" * 25)
    print(f"  {args.in_sample} in-sample / {args.out_sample} out-of-sample bars per window")
    engine = VectorizedBacktester(configured, sizer, **equity_kwargs)
    sharpes: list[float] = []
    empty_windows = [0]
    per_symbol: list[tuple[str, int, float, float]] = []
    for symbol, (bars, signals) in loaded.items():
        if len(bars) < args.in_sample + args.out_sample:
            continue
        wf = run_walk_forward(
            engine,
            symbol,
            bars,
            signals,
            in_sample_bars=args.in_sample,
            out_sample_bars=args.out_sample,
        )
        if not wf.windows:
            continue
        # Only windows that actually TRADED. A window with no trades scores a
        # Sharpe of 0.0, and swing takes about one trade per symbol per year -
        # so pooling every window measures mostly silence and reports it as a
        # median of exactly zero. That is an artefact of the denominator, not
        # a finding about the strategy.
        window_sharpes = [
            w.out_sample_result.metrics.get("sharpe", 0.0)
            for w in wf.windows
            if w.out_sample_result.trades
        ]
        empty_windows[0] += len(wf.windows) - len(window_sharpes)
        if not window_sharpes:
            continue
        sharpes.extend(window_sharpes)
        per_symbol.append(
            (
                symbol,
                len(wf.windows),
                wf.metric_stability["sharpe_mean"],
                wf.metric_stability["sharpe_std"],
            )
        )

    if not sharpes:
        print("  no window had enough history - shorten --in-sample/--out-sample")
        return 0

    positive = sum(1 for s in sharpes if s > 0)
    print(f"  windows WITH trades {len(sharpes):>8d}  across {len(per_symbol)} symbols")
    print(f"  windows with none   {empty_windows[0]:>8d}  (scored 0.0, excluded)")
    print(f"  Sharpe > 0          {positive / len(sharpes):>8.1%}  ({positive} of {len(sharpes)})")
    print(f"  mean Sharpe         {statistics.mean(sharpes):>8.2f}")
    print(f"  median Sharpe       {statistics.median(sharpes):>8.2f}")
    if len(sharpes) > 1:
        print(f"  std across windows  {statistics.stdev(sharpes):>8.2f}")
    print("\n  worst five symbols by mean out-of-sample Sharpe:")
    for symbol, count, mean, std in sorted(per_symbol, key=lambda r: r[2])[:5]:
        print(f"    {symbol:<6} {count:>2d} windows   mean {mean:>6.2f}   std {std:>5.2f}")
    print("  best five:")
    for symbol, count, mean, std in sorted(per_symbol, key=lambda r: r[2], reverse=True)[:5]:
        print(f"    {symbol:<6} {count:>2d} windows   mean {mean:>6.2f}   std {std:>5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
