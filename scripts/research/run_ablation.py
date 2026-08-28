"""Run the harness twice - all rails on, then one rail off - and compare.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_ablation.py --rail cost_to_risk
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_ablation.py --list
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_ablation.py --market ASX --list

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
from qat.domain.backtester.ablation import (  # noqa: E402
    RAILS,
    REGIME_RAIL,
    ablated_settings,
    feature_settings,
)
from qat.domain.backtester.macro_cache import DEFAULT_MACRO_CACHE, frozen_macro  # noqa: E402
from qat.domain.backtester.manifest import build_manifest  # noqa: E402
from qat.domain.backtester.replay_session import ReplaySession  # noqa: E402
from qat.domain.backtester.research_universe import (  # noqa: E402
    UNIVERSES,
    ResearchUniverse,
    load_bars,
)
from qat.domain.backtester.run_comparison import (  # noqa: E402
    compare_runs,
    write_regime_path,
)
from qat.domain.events import RegimeEvent  # noqa: E402
from qat.domain.strategies.swing import SwingStrategy  # noqa: E402
from qat.presentation.runtime import resolve_macro_source  # noqa: E402


async def _one(
    directory: Path,
    disabled: list[str],
    universe: ResearchUniverse,
    bars: dict[str, pd.DataFrame],
    macro: dict[str, list[MacroObservation]],
    feature: str | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    base = Settings(
        _env_file=None,
        data_dir=str(directory),  # NEVER the live directory
        market=universe.market,
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )
    if feature is not None:
        base = feature_settings(base, [feature])
    session = ReplaySession(
        bars=bars,
        strategies=[SwingStrategy()],
        settings=ablated_settings(base, disabled),
        macro=macro,
        benchmark=universe.benchmark,
        warm_bars=universe.warm_bars,
        # The regime gate has no Settings knob - ablating it means the engine
        # never publishes, so the exposure scalar holds its 1.0 default.
        start_regime=REGIME_RAIL not in disabled,
    )
    # The harness LISTENS to an event the app already publishes - no change to
    # the trading path, the same seam `start_regime` already uses. Subscribed
    # before `run` so the first classification is not missed.
    regime_rows: list[tuple[str, str, float]] = []

    async def _record_regime(event: RegimeEvent) -> None:
        regime_rows.append((event.ts.isoformat(), event.label, event.exposure_scalar))

    session.bus.subscribe(RegimeEvent, _record_regime)

    await session.run()

    write_regime_path(directory, regime_rows)
    account = await session.broker.get_account()
    build_manifest(
        data_dir=directory,
        disabled=disabled,
        universe=sorted(bars),
        starting_equity=100_000.0,
        terminal_equity=float(account.net_liquidation),
        disabled_feature=feature,
        regime_features=base.regime_features,
    ).write(directory / "manifest.json")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ablate one rail and compare two runs")
    parser.add_argument("--rail", help="the rail to switch off")
    parser.add_argument("--out", default=None, help="where to write both runs")
    parser.add_argument("--list", action="store_true", help="list the ablatable rails and exit")
    parser.add_argument(
        "--market",
        choices=sorted(UNIVERSES),
        default="US",
        help="which universe to replay: US (G1 megacaps, the default - every "
        "existing invocation) or ASX",
    )
    args = parser.parse_args(argv)

    if args.list:
        for name in [*sorted(RAILS), REGIME_RAIL]:
            print(name)
        return 0
    if not args.rail:
        parser.error("--rail is required (or --list)")

    universe = UNIVERSES[args.market]
    if not universe.bars_cache.exists():
        print(f"no bar cache at {universe.bars_cache}")
        if universe.market == "US":
            print("run scripts/analysis/g1/run_g1.py once to populate it")
        else:
            print("run scripts/research/run_asx_replay.py --fetch once to populate it")
        return 1

    root = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="ablation-"))
    bars = load_bars(universe)
    # Live config, for CREDENTIALS ONLY - read, never written, and never used
    # as a data_dir. One instance, because two reads of the same config to fill
    # two arguments of one call is a difference waiting to happen.
    live_config = Settings()
    macro = await frozen_macro(
        DEFAULT_MACRO_CACHE,
        # `source` is a FACTORY, so FRED is only resolved on a cache miss.
        # `series` is an ordinary argument and IS read now - which is safe,
        # because `fred_series` is a static default that touches no secret and
        # no network. Said precisely because the first draft of this comment
        # claimed the whole call was deferred, and half of it is not.
        source=lambda: resolve_macro_source(live_config),
        series=live_config.fred_series,
    )
    print(f"universe   : {len(bars)} {universe.market} symbols ({universe.bars_cache.name})")
    print(f"macro      : {len(macro)} series, {sum(len(v) for v in macro.values())} observations")
    print(f"warm bars  : {universe.warm_bars}")
    print(f"output     : {root}")
    print()

    print("baseline (all rails on)...")
    await _one(root / "baseline", [], universe, bars, macro)
    print(f"ablated ({args.rail} off)...")
    await _one(root / "ablated", [args.rail], universe, bars, macro)

    print()
    print(compare_runs(root / "baseline", root / "ablated", args.rail))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
