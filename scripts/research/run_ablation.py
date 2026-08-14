"""Run the harness twice - all rails on, then one rail off - and compare.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_ablation.py --rail cost_to_risk
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_ablation.py --list

**RUN THROUGH POWERSHELL, NEVER BASH.** The Bash sandbox is per-file and covers
writes as well as reads, so a run from there can read a frozen bar cache and
write results into an overlay nobody can see.

**It passes its own `data_dir`, and that is not optional.**
`Settings(_env_file=None).data_dir` resolves to the LIVE data directory;
`conftest` protects tests and a script run outside pytest has no such
protection. Two W2 probes wrote a row for a symbol named `AAA` into the live
record on 12 August exactly this way.

## What it will tell you, and what it will not

Every run emits a manifest recording which rails were on, how often each bound,
whether G1 ever validated that rail against the live book, the fill model, the
universe and the code commit. The comparison then leads with a GUARD rather
than a number: if the rail never bound in the baseline there was nothing for its
removal to change, and the difference is suppressed entirely rather than printed
as a zero beside a caveat.

**Expect `--rail position_limit` to report NOT EXERCISED on the G1 universe.**
That is the accepted fidelity limit of 13 August doing its job: live evaluates
every 60 seconds against a forming bar and filled its book on day one, the
replay evaluates once per closed bar and never reaches ten positions. A rail
that never binds cannot be ablated, and saying so is the correct answer rather
than a failure of this script.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.macro_fred import MacroObservation  # noqa: E402
from qat.domain.backtester.ablation import RAILS, REGIME_RAIL, ablated_settings  # noqa: E402
from qat.domain.backtester.macro_cache import DEFAULT_MACRO_CACHE, frozen_macro  # noqa: E402
from qat.domain.backtester.manifest import build_manifest  # noqa: E402
from qat.domain.backtester.replay_session import ReplaySession  # noqa: E402
from qat.domain.backtester.run_comparison import compare_runs  # noqa: E402
from qat.domain.strategies.swing import SwingStrategy  # noqa: E402
from qat.presentation.runtime import resolve_macro_source  # noqa: E402

# The gate's own frozen cache, so an ablation and G1 rest on identical inputs.
# A research run that fetched its own bars could differ from the gate for a
# reason that has nothing to do with the rail under test.
BARS_CACHE = _REPO / "scripts" / "analysis" / "g1" / "bars"
BENCHMARK = "SPY"
WARM_BARS = 120


def _cached_bars() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for path in sorted(BARS_CACHE.glob("*.csv")):
        frame = pd.read_csv(path, parse_dates=["ts"])
        frame = frame.set_index(pd.DatetimeIndex(frame["ts"])).drop(columns=["ts"])
        # `run_g1.py` writes `symbol.replace('/', '-')`, and no symbol in this
        # universe contains a slash - BRK.B is stored as `BRK.B.csv` - so the
        # stem is the symbol unchanged.
        out[path.stem] = frame[["open", "high", "low", "close", "volume"]]
    return out


async def _one(
    directory: Path,
    disabled: list[str],
    bars: dict[str, pd.DataFrame],
    macro: dict[str, list[MacroObservation]],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    base = Settings(
        _env_file=None,
        data_dir=str(directory),  # NEVER the live directory
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )
    session = ReplaySession(
        bars=bars,
        strategies=[SwingStrategy()],
        settings=ablated_settings(base, disabled),
        macro=macro,
        benchmark=BENCHMARK,
        warm_bars=WARM_BARS,
        # The regime gate has no Settings knob - ablating it means the engine
        # never publishes, so the exposure scalar holds its 1.0 default.
        start_regime=REGIME_RAIL not in disabled,
    )
    await session.run()
    build_manifest(
        data_dir=directory,
        disabled=disabled,
        universe=sorted(bars),
        starting_equity=100_000.0,
    ).write(directory / "manifest.json")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ablate one rail and compare two runs")
    parser.add_argument("--rail", help="the rail to switch off")
    parser.add_argument("--out", default=None, help="where to write both runs")
    parser.add_argument("--list", action="store_true", help="list the ablatable rails and exit")
    args = parser.parse_args(argv)

    if args.list:
        for name in [*sorted(RAILS), REGIME_RAIL]:
            print(name)
        return 0
    if not args.rail:
        parser.error("--rail is required (or --list)")

    if not BARS_CACHE.exists():
        print(f"no bar cache at {BARS_CACHE}")
        print("run scripts/analysis/g1/run_g1.py once to populate it")
        return 1

    root = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="ablation-"))
    bars = _cached_bars()
    macro = await frozen_macro(
        DEFAULT_MACRO_CACHE,
        # Live config for CREDENTIALS ONLY, and only on a cache miss - nothing
        # is written to the live data directory and the cache is already there.
        source=lambda: resolve_macro_source(Settings()),
        series=Settings().fred_series,
    )
    print(f"universe   : {len(bars)} symbols from the G1 cache")
    print(f"macro      : {len(macro)} series, {sum(len(v) for v in macro.values())} observations")
    print(f"warm bars  : {WARM_BARS}")
    print(f"output     : {root}")
    print()

    print("baseline (all rails on)...")
    await _one(root / "baseline", [], bars, macro)
    print(f"ablated ({args.rail} off)...")
    await _one(root / "ablated", [args.rail], bars, macro)

    print()
    print(compare_runs(root / "baseline", root / "ablated", args.rail))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
