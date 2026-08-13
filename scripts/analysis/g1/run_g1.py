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
"""

from __future__ import annotations

import asyncio
import csv
import sys
import tempfile
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
from qat.domain.evaluation.replay_agreement import compare  # noqa: E402
from qat.domain.strategies.swing import SwingStrategy  # noqa: E402
from qat.presentation.runtime import resolve_macro_source  # noqa: E402

FROZEN_DECISIONS = _HERE / "risk_decisions.frozen.csv"
FROZEN_BOOK = _HERE / "open_position_entries.frozen.json"
BARS_CACHE = _HERE / "bars"

# AAA is a test fixture symbol a scratchpad probe wrote into the live record on
# 12 August; WES.AX is an ASX ticker in a US book, provenance unknown, from
# 6 August. Both are excluded BY NAME rather than by silence - see README.md.
EXCLUDED = frozenset({"AAA", "WES.AX"})

BENCHMARK = "SPY"


def _frozen_rows() -> list[dict[str, str]]:
    with FROZEN_DECISIONS.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


async def main() -> int:
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

    produced = scratch / "risk_decisions.csv"
    harness_rows: list[dict[str, str]] = []
    if produced.exists():
        with produced.open(encoding="utf-8") as handle:
            harness_rows = list(csv.DictReader(handle))
    print(f"harness decisions: {len(harness_rows)}")

    verdict = compare(rows, harness_rows, exclude=EXCLUDED)
    print()
    print("=== G1 VERDICT ===")
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
    print()
    print(f"run at {datetime.now(UTC).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
