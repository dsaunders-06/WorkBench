"""Replay the harness against the ASX — the market this system is moving to.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_asx_replay.py --fetch
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_asx_replay.py

**RUN THROUGH POWERSHELL, NEVER BASH**, and note that this passes its own
`data_dir`: `Settings(_env_file=None).data_dir` resolves to the LIVE data
directory, and two W2 probes wrote a row for a symbol named `AAA` into the live
record on 12 August exactly that way.

## Why this exists

The harness is the asset that survives the ASX move, and until now it has only
ever run against US megacaps over a 40-session window - where it produced TEN
risk decisions in a whole run, all approvals, so **not one rail could be
exercised** and every ablation correctly reported NOT EXERCISED.

That is a statement about the window, not about the rails. This asks the same
question of the destination market, over a materially longer period:

  * **Do the rails bind on ASX data?** If they do, the ablation switch and the
    run manifest built in W2 step 6 become useful for the first time.
  * If they do not, the manifest says NOT EXERCISED and that is an honest
    answer rather than a silent zero - which is the whole reason the guard
    exists.

## What is already in place, and it is most of it

Nothing here builds ASX support; it wires up what exists.

  * `universe.MARKET_WATCHLISTS["ASX"]` - 100 megacaps, benchmark `STW.AX`
  * `market_calendar` - Australia/Sydney, 10:00-16:00, ASX holidays
  * `costs.MARKET_COST_PROFILES[("ASX", ...)]` - real fee schedules, selected
    automatically by `Settings.market="ASX"`
  * yfinance serves `.AX` tickers, so this needs no IBKR account and is not
    blocked on W1.1
  * frozen FRED history via `macro_cache`, SHARED with the ablation - without
    it the regime engine cannot fit and the rail is inert while the run still
    reports numbers

## Bars are cached and then frozen

Same rule the G1 gate follows: a research run whose inputs can move between
executions cannot be compared with the one before it, and an ablation is
nothing but that comparison. `--fetch` populates the cache; every later run
reads it and touches no network.

**yfinance is rate-limited**, so the fetch is deliberately slow and resumable -
a symbol already cached is skipped, so an interrupted fetch continues where it
stopped rather than starting again.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.history import resolve_history_source  # noqa: E402
from qat.data.macro_fred import MacroObservation  # noqa: E402
from qat.data.universe import MARKET_WATCHLISTS  # noqa: E402
from qat.domain.backtester.macro_cache import (  # noqa: E402
    DEFAULT_MACRO_CACHE,
    frozen_macro,
    macro_coverage,
)
from qat.domain.backtester.manifest import build_manifest  # noqa: E402
from qat.domain.backtester.replay_session import ReplaySession  # noqa: E402
from qat.domain.backtester.research_universe import ASX, load_bars  # noqa: E402
from qat.domain.evaluation.refusals import load_risk_decisions, summarise_refusals  # noqa: E402
from qat.domain.strategies.swing import SwingStrategy  # noqa: E402
from qat.presentation.runtime import resolve_macro_source  # noqa: E402

# The universe descriptor - bar cache, benchmark, warm bars, market - is
# shared with `run_ablation.py` via `research_universe.ASX` rather than owned
# here, so the two scripts cannot drift into two notions of "the ASX universe".
BARS_CACHE = ASX.bars_cache
BENCHMARK = ASX.benchmark
WARM_BARS = ASX.warm_bars
# A year and a half of sessions, against the US window's forty. The US run could
# not fill its book partly because it had no time to: ten decisions in forty
# sessions cannot reach a ten-position limit.
BAR_COUNT = 500


def _asx_limitations(macro: dict[str, list[MacroObservation]]) -> tuple[str, str]:
    """What this run may not be quoted as saying, beyond the six every run
    states. Recorded in the manifest rather than in a paragraph somebody has to
    remember.

    The series named in the first sentence come from the macro that was
    actually loaded, not from a copy written down separately - a config change
    (the project's next step is adding Australian series) would otherwise leave
    this string naming series the run no longer used, which is exactly the kind
    of untrue provenance record `manifest.py` exists to prevent.

    The second sentence deliberately does NOT repeat that the universe is a
    static 2026 megacap snapshot - `manifest._STATED_LIMITATIONS[0]` already
    says that on every run. Restating it here would be two wordings of one
    caveat in a record whose purpose is precision, so this names only what the
    standing one does not: the yfinance source and the absence of delisted
    names.
    """
    return (
        f"The macro series are US - {', '.join(sorted(macro))}. The regime "
        "engine therefore classifies an ASX book from US volatility, the US curve and "
        "US credit. That is what the DEPLOYED engine would do on this market, so the "
        "run is honest about the machinery; it is not evidence that those series "
        "describe the ASX.",
        "The ASX universe is fetched from yfinance, and delisted names are absent "
        "from it entirely.",
    )


def _convergence_limitation(non_monotonic_fits: int) -> tuple[str, ...]:
    """What `exercised: true` alone cannot say: the regime rail can classify
    from a fit during which the EM log-likelihood decreased between
    iterations. `hmmlearn` printed "Model is not converging." during the
    first ASX run - the classification was used exactly as the deployed
    engine would use it, and the manifest said nothing about the fit's
    quality. Empty when no refit logged the warning, so a clean run adds
    nothing to the tuple `extra_limitations` appends.
    """
    if non_monotonic_fits <= 0:
        return ()
    plural = "" if non_monotonic_fits == 1 else "s"
    return (
        f"The EM log-likelihood decreased during {non_monotonic_fits} regime "
        f"refit{plural}. The classification was still used, exactly as the deployed engine "
        "would use it, so this describes the quality of the fit and not a departure from "
        "live behaviour.",
    )


def _symbols() -> list[str]:
    asx = MARKET_WATCHLISTS["ASX"]
    wanted = set(asx["megacap"]) | set(asx["curated"]) | {BENCHMARK}
    return sorted(wanted)


async def _fetch(symbols: list[str]) -> None:
    """Populate the cache. Resumable, because yfinance rate-limits."""
    BARS_CACHE.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, market="ASX", market_data_source="yfinance")
    source = resolve_history_source(settings)
    todo = [s for s in symbols if not (BARS_CACHE / f"{s}.csv").exists()]
    print(
        f"{len(symbols)} symbols, {len(symbols) - len(todo)} already cached, {len(todo)} to fetch"
    )
    synthetic: list[str] = []
    for i, symbol in enumerate(todo, start=1):
        try:
            frame = await source.get_daily_bars(symbol, BAR_COUNT)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not end the fetch
            print(f"  [{i}/{len(todo)}] {symbol}: FAILED {type(exc).__name__}: {exc}")
            continue
        if frame is None or frame.empty:
            print(f"  [{i}/{len(todo)}] {symbol}: no bars")
            continue
        # THE GUARD THAT SHOULD HAVE EXISTED FIRST. `YFinanceHistorySource`
        # falls back to SYNTHETIC bars when a real fetch returns nothing - it
        # logs "This data is NOT real" and returns a full frame, with no
        # exception. Before `to_yfinance` was fixed, every ASX ticker went out
        # as `BHP-AX`, 404'd, and came back as 500 fabricated daily bars.
        #
        # Caching that would have produced expectancy, rail bindings and an
        # ablation verdict on invented prices, all of it plausible. A research
        # input that is silently fake is worse than no input, so it is refused
        # rather than warned about.
        if getattr(source, "last_was_synthetic", False):
            synthetic.append(symbol)
            print(f"  [{i}/{len(todo)}] {symbol}: SYNTHETIC - refused, not cached")
            continue
        frame.to_csv(BARS_CACHE / f"{symbol}.csv", index=False)
        print(f"  [{i}/{len(todo)}] {symbol}: {len(frame)} bars")
        time.sleep(0.4)

    if synthetic:
        print()
        print(f"*** {len(synthetic)} symbol(s) returned SYNTHETIC data and were NOT cached ***")
        print(f"    {', '.join(synthetic)}")
        print("    A run on fabricated prices produces figures that look entirely real.")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the harness on ASX data")
    parser.add_argument("--fetch", action="store_true", help="populate the bar cache, then stop")
    parser.add_argument("--out", default=None, help="where to write the run")
    parser.add_argument(
        "--evaluate-at",
        choices=("close", "open"),
        default="close",
        help="'open' reproduces the live frame - a complete yesterday plus one print of today",
    )
    args = parser.parse_args(argv)

    if args.fetch:
        await _fetch(_symbols())
        return 0

    bars = load_bars(ASX)
    if not bars:
        print(f"no cached bars at {BARS_CACHE}")
        print("run with --fetch first")
        return 1
    if BENCHMARK not in bars:
        print(f"benchmark {BENCHMARK} is not cached - the regime engine cannot classify without it")
        return 1

    root = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="asx-"))
    root.mkdir(parents=True, exist_ok=True)
    spans = [f.index for f in bars.values()]
    # Computed once: this same value guards macro coverage below, and printing
    # one reduction while guarding on a second, separately computed one is a
    # difference waiting to happen between the reported period and the date the
    # guard actually checked.
    first_session = min(s.min() for s in spans)
    print(f"universe   : {len(bars)} ASX symbols (benchmark {BENCHMARK})")
    print(f"period     : {first_session.date()} -> {max(s.max() for s in spans).date()}")
    print(f"warm bars  : {WARM_BARS}")
    print(f"cadence    : evaluate at the {args.evaluate_at}")
    print(f"output     : {root}")
    print()

    # Live config, for CREDENTIALS ONLY - read, never written, and never used
    # as a data_dir. NOT the `settings` built further down, which is the
    # replay's own and points at the scratch `--out` directory.
    live_config = Settings()
    macro = await frozen_macro(
        DEFAULT_MACRO_CACHE,
        # `source` is a FACTORY, so FRED is only resolved on a cache miss.
        # `series` is an ordinary argument and IS read now - which is safe,
        # because `fred_series` is a static default that touches no secret and
        # no network.
        source=lambda: resolve_macro_source(live_config),
        series=live_config.fred_series,
    )
    # THE GUARD THAT MAKES THIS WORTH DOING. Passing macro that does not reach
    # back to the first replayed session leaves the affected series constant,
    # and a constant column is the singular covariance that makes the HMM fail
    # to fit - which the run reports as REGIME ENGINE NOT CLASSIFYING while
    # producing a complete and entirely plausible set of numbers with the
    # regime rail inert. That is precisely the silent zero this harness exists
    # to refuse.
    coverage = macro_coverage(macro, first_session.to_pydatetime())
    print(f"macro      : {len(macro)} series, {sum(len(v) for v in macro.values())} observations")
    for name, count in sorted(coverage.items()):
        print(f"             {name:<10}{count:>7} observations on or before the first session")
    bare = sorted(name for name, count in coverage.items() if count == 0)
    if bare:
        print()
        verb = "has" if len(bare) == 1 else "have"
        print(f"*** {', '.join(bare)} {verb} no observation before the replay starts ***")
        print("    Those features would be CONSTANT and the regime engine could not fit.")
        return 1
    print()

    settings = Settings(
        _env_file=None,
        data_dir=str(root),  # NEVER the live directory
        market=ASX.market,  # "ASX" - selects the ASX cost profile automatically
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )
    session = ReplaySession(
        bars=bars,
        strategies=[SwingStrategy()],
        settings=settings,
        macro=macro,
        benchmark=BENCHMARK,
        warm_bars=WARM_BARS,
        evaluate_at=args.evaluate_at,
    )
    print(f"replaying {len(session.broker.session_dates)} sessions...")
    await session.run()

    manifest = build_manifest(
        data_dir=root,
        disabled=[],
        universe=sorted(bars),
        starting_equity=100_000.0,
        extra_limitations=(
            *_asx_limitations(macro),
            *_convergence_limitation(session.regime_engine.non_monotonic_fits),
        ),
    )
    manifest.write(root / "manifest.json")

    rows = load_risk_decisions(root)
    summary = summarise_refusals(rows)
    print()
    print("=== DID THE RAILS BIND? ===")
    print(summary.headline())
    print()
    for rail, count in summary.by_reason.items():
        print(f"  {rail:<38}{count:>6}")
    print()
    print(f"{'rail':<24}{'observability':<15}{'bound':>7}  exercised")
    for name, record in manifest.rails.items():
        bound = "n/a" if record.bound_count is None else str(record.bound_count)
        print(f"{name:<24}{record.observability.value:<15}{bound:>7}  {record.exercised}")

    trades = root / "closed_trades.csv"
    if trades.exists():
        with trades.open(encoding="utf-8") as handle:
            print(f"\nclosed trades: {sum(1 for _ in handle) - 1}")
    else:
        print("\nclosed trades: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
