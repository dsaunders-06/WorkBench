"""G1 — replay the live window and compare which rail bound (W2 step 5).

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\analysis\\g1\\run_g1.py

**RUN THROUGH POWERSHELL, NEVER BASH.** The credentials come from the machine's
secret store and the live data directory is sandboxed per-file under Bash - a
Bash run reads the wrong config and writes to an overlay nobody can see.

**It never writes to the live data directory.** The replay is given its own
scratch `data_dir`, because the risk engine writes `risk_decisions.csv` wherever
it is pointed - which is how a scratchpad probe put a row for a symbol named
AAA into the live record on 12 August.

## Why IEX and not SIP

The plan said SIP, and for research runs that is right: IEX sees a median 4.3%
of consolidated volume and a 3.5% narrower daily range. **But G1 is not a
research run.** It asks whether the harness reproduces decisions the live book
actually made, and the live book computed those decisions from IEX - its warm
start seeded from IEX daily bars and its ticks were IEX. Replaying SIP would
introduce differences from the FEED and score them as differences in the LOGIC,
which is the one thing this gate must not do.

## What is compared

`(symbol, day) -> the set of rails that bound`, via `refusals.rail_of`. Not the
reason text, which fragments across every distinct cent it mentions; and not
row-for-row, because live evaluates on every poll and the replay once per bar -
708 decisions in a day against at most one per symbol.

## Re-scoring without re-replaying — added 13 August

The first version discarded the harness's own decisions into a temp directory,
so **every question about the result cost a full replay**: bar fetch, FRED
history, 200 sessions. The rows are now persisted to `harness_decisions.csv`
beside the frozen input, and `--score-only` scores from them.

That matters beyond convenience. A gate whose output cannot be re-examined
without re-running it invites the re-run to be skipped and the number to be
remembered instead, which is the failure mode this project keeps finding.

    --score-only        score the stored rows; no replay, no network
    --day YYYY-MM-DD    scope the comparison to one session
    (default)           replay, store, then score the whole window

**`--day` exists because of one day in particular.** The window opens 31 July
with the book EMPTY on both sides - it is the only session where the harness
and the live book start in the same state, before live filled its book and the
position limit began dominating everything after it. Scoring it alone asks
whether the harness reproduces live when the cadence difference has not yet had
time to compound, which is a different question from the whole window's and a
fairer one to the instrument.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]
sys.path.insert(0, str(_REPO / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.broker.simulated_broker import OpeningPosition  # noqa: E402
from qat.data.history import resolve_history_source  # noqa: E402
from qat.domain.backtester.replay_session import ReplaySession  # noqa: E402
from qat.domain.evaluation.replay_agreement import Verdict, compare  # noqa: E402
from qat.domain.strategies.swing import SwingStrategy  # noqa: E402
from qat.presentation.runtime import resolve_macro_source  # noqa: E402

FROZEN_DECISIONS = _HERE / "risk_decisions.frozen.csv"
FROZEN_BOOK = _HERE / "open_position_entries.frozen.json"
BARS_CACHE = _HERE / "bars"
# The harness's own decisions, kept so the gate can be re-scored without being
# re-run. Written on every replay; read by --score-only.
HARNESS_DECISIONS = _HERE / "harness_decisions.csv"

# AAA is a test fixture symbol a scratchpad probe wrote into the live record on
# 12 August; WES.AX is an ASX ticker in a US book, provenance unknown, from
# 6 August. Both are excluded BY NAME rather than by silence - see README.md.
EXCLUDED = frozenset({"AAA", "WES.AX"})

BENCHMARK = "SPY"


def _frozen_rows() -> list[dict[str, str]]:
    with FROZEN_DECISIONS.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    """Persist the harness's decisions verbatim, columns and all.

    Empty is written as a header-less empty file rather than skipped: a missing
    file and a run that produced nothing are different facts, and --score-only
    must be able to tell them apart.
    """
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _day_of(row: dict[str, str]) -> str:
    return (row.get("timestamp") or "")[:10]


def _on_day(rows: list[dict[str, str]], day: str) -> list[dict[str, str]]:
    return [row for row in rows if _day_of(row) == day]


def _opening_book() -> dict[str, OpeningPosition]:
    """EMPTY, and that is a finding rather than an omission.

    The G1 plan said the replay must start from the book as it stood, and
    assumed that meant ten positions. Measured: the first row of the frozen
    record is `2026-07-31T13:30:10 CSCO approved`, with 32 approvals on 31 July
    alone. **The window opens with nothing held** - the book is built from
    scratch inside it, and that is exactly what produces the position-limit
    refusals that dominate the later days.

    Seeding the 12 August book would hand the replay the answer: ten positions
    it never had to earn, and a limit already binding on day one.

    The `OpeningPosition` seam stays built and stays right - a window starting
    mid-book needs it - but this window does not.
    """
    return {}


async def _bars(symbols: list[str], settings: Settings) -> dict[str, pd.DataFrame]:
    """Daily bars, cached to disk so the gate's input is frozen too.

    A gate whose input can silently change between runs is not a gate.
    """
    BARS_CACHE.mkdir(exist_ok=True)
    source = resolve_history_source(settings)
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        cached = BARS_CACHE / f"{symbol.replace('/', '-')}.csv"
        if cached.exists():
            frame = pd.read_csv(cached, parse_dates=["ts"])
        else:
            frame = await source.get_daily_bars(symbol, 200)
            if frame.empty:
                print(f"  {symbol}: NO BARS - excluded from the replay")
                continue
            frame.to_csv(cached, index=False)
        frame = frame.set_index(pd.DatetimeIndex(frame["ts"])).drop(columns=["ts"])
        out[symbol] = frame[["open", "high", "low", "close", "volume"]]
    return out


def _print_verdict(verdict: Verdict, title: str) -> None:
    print()
    print(f"=== {title} ===")
    print(
        f"symbol-days: exact {verdict.exact_days} · partial {verdict.partial_days} · "
        f"disjoint {verdict.disjoint_days} · live-only {verdict.live_only_days} · "
        f"harness-only {verdict.harness_only_days}"
    )
    print()
    print(f"{'rail':<34}{'agreed':>8}{'live only':>11}{'harness only':>14}{'rate':>8}")
    for rail in verdict.rails:
        print(
            f"{rail.rail:<34}{rail.agreed:>8}{rail.live_only:>11}"
            f"{rail.harness_only:>14}{rail.agreement_rate:>8.0%}"
        )


def _print_per_day(live: list[dict[str, str]], harness: list[dict[str, str]]) -> None:
    """One row per session, so the choice of day to examine is not arbitrary.

    The whole-window verdict pools a day where both sides start empty with days
    where live has been at its position limit since the first afternoon. Those
    are different measurements and averaging them describes neither.
    """
    days = sorted({_day_of(r) for r in live if _day_of(r)} | {_day_of(r) for r in harness})
    live_by_day = Counter(_day_of(r) for r in live)
    harness_by_day = Counter(_day_of(r) for r in harness)
    print()
    print("=== PER SESSION ===")
    print(
        f"{'day':<12}{'live rows':>10}{'harness':>9}"
        f"{'exact':>7}{'partial':>9}{'disjoint':>10}{'live only':>11}{'harn only':>11}"
    )
    for day in days:
        verdict = compare(_on_day(live, day), _on_day(harness, day), exclude=EXCLUDED)
        print(
            f"{day:<12}{live_by_day[day]:>10}{harness_by_day[day]:>9}"
            f"{verdict.exact_days:>7}{verdict.partial_days:>9}{verdict.disjoint_days:>10}"
            f"{verdict.live_only_days:>11}{verdict.harness_only_days:>11}"
        )


async def _replay() -> list[dict[str, str]]:
    settings_live = Settings()
    rows = _frozen_rows()
    symbols = sorted({r["symbol"] for r in rows} - EXCLUDED)
    wanted = sorted(set(symbols) | {BENCHMARK})
    print(f"frozen decisions : {len(rows)}")
    print(f"symbols          : {len(symbols)} (+{BENCHMARK} as benchmark)")
    print(f"excluded         : {', '.join(sorted(EXCLUDED))}")

    print("fetching daily bars (IEX, as the live book saw)...")
    bars = await _bars(wanted, settings_live)
    print(f"  got bars for {len(bars)} symbols")

    print("loading FRED history...")
    macro_source = resolve_macro_source(settings_live)
    macro = {}
    for series in settings_live.fred_series:
        macro[series] = await macro_source.fetch_series(series)
    print(f"  {len(macro)} series, {sum(len(v) for v in macro.values())} observations")

    scratch = Path(tempfile.mkdtemp(prefix="g1-"))
    # The replayed period must be the WINDOW, and the warm-up everything before
    # it. Derived from the frozen record rather than hard-coded: a fixed bar
    # count replayed five months the live book never saw, and scored every day
    # of it as a disagreement.
    window_start = pd.Timestamp(min(r["timestamp"] for r in rows)[:10], tz="UTC")
    reference = bars[BENCHMARK].index
    warm_bars = int((reference < window_start).sum())
    print(f"window starts    : {window_start.date()}  (bar {warm_bars} of {len(reference)})")
    print(f"replay data_dir  : {scratch}  (NEVER the live directory)")

    settings = Settings(
        _env_file=None,
        data_dir=str(scratch),
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
        warm_bars=warm_bars,
        opening_positions=_opening_book(),
    )
    print(f"replaying {len(session.broker.session_dates)} sessions...")
    await session.run()

    harness_rows = _read_rows(scratch / "risk_decisions.csv")
    _write_rows(HARNESS_DECISIONS, harness_rows)
    print(f"harness decisions: {len(harness_rows)}  (stored in {HARNESS_DECISIONS.name})")
    return harness_rows


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G1 - the research harness acceptance gate")
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="score the stored harness decisions without replaying (no network)",
    )
    parser.add_argument(
        "--day",
        metavar="YYYY-MM-DD",
        help="scope the comparison to one session, e.g. the empty-book day 2026-07-31",
    )
    args = parser.parse_args(argv)

    live_rows = _frozen_rows()

    if args.score_only:
        if not HARNESS_DECISIONS.exists():
            print(f"no stored harness decisions at {HARNESS_DECISIONS}")
            print("run without --score-only once to produce them")
            return 1
        harness_rows = _read_rows(HARNESS_DECISIONS)
        print(f"frozen decisions : {len(live_rows)}")
        print(f"harness decisions: {len(harness_rows)}  (stored, not replayed)")
    else:
        harness_rows = await _replay()

    _print_per_day(live_rows, harness_rows)

    if args.day:
        live_rows = _on_day(live_rows, args.day)
        harness_rows = _on_day(harness_rows, args.day)
        title = f"G1 VERDICT - {args.day} ONLY"
        print()
        print(f"scoped to {args.day}: {len(live_rows)} live rows, {len(harness_rows)} harness rows")
    else:
        title = "G1 VERDICT"

    _print_verdict(compare(live_rows, harness_rows, exclude=EXCLUDED), title)
    print()
    print(f"run at {datetime.now(UTC).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
