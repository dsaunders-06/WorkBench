"""FRED history, fetched once and then frozen on disk.

Frozen for the reason the bars are: a research run whose inputs can move
between executions cannot be compared with the one before it, and an ablation
is nothing but a comparison of two runs.

**Shared rather than owned by a runner.** `run_ablation.py` held this
privately, so `run_asx_replay.py` passed no macro at all - and WITHOUT MACRO
THE REGIME ENGINE CANNOT FIT. `vix_level`, `yield_curve_slope` and
`credit_spread` stay constant, a constant column makes the covariance matrix
singular, and the run reports "REGIME ENGINE NOT CLASSIFYING (HMM fit failed)"
while producing an entirely plausible set of numbers with one rail inert.

The source is INJECTED. `resolve_macro_source` lives in
`qat.presentation.runtime` because it reads a stored secret, and a domain
module importing presentation would invert the layering to save one argument.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from qat.data.macro_fred import MacroDataSource, MacroObservation

# Beside the G1 bars, and shared with the ablation deliberately: FRED is not a
# market, so one frozen history serves the US gate and the ASX replay both, and
# a second copy is a second thing that can be re-fetched by accident. Same
# repo-relative shape as `manifest._G1_VERDICT`.
DEFAULT_MACRO_CACHE = (
    Path(__file__).resolve().parents[4] / "scripts" / "analysis" / "g1" / "macro.json"
)


def read_macro_cache(path: Path) -> dict[str, list[MacroObservation]] | None:
    """The frozen history, or None when there is none.

    None rather than an empty dict: absent means "fetch it" and empty means "a
    fetch returned nothing", and collapsing them would silently re-fetch a
    frozen input.
    """
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        series: [
            MacroObservation(
                series=series, ts=datetime.fromisoformat(row["ts"]), value=row["value"]
            )
            for row in rows
        ]
        for series, rows in raw.items()
    }


def write_macro_cache(path: Path, macro: dict[str, list[MacroObservation]]) -> None:
    """Byte-compatible with the cache `run_ablation.py` wrote before this module
    existed - the existing `macro.json` is an input to every ablation already
    run, and rewriting it would invalidate the comparisons that rest on it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                series: [{"ts": o.ts.isoformat(), "value": o.value} for o in observations]
                for series, observations in macro.items()
            }
        ),
        encoding="utf-8",
    )


async def frozen_macro(
    path: Path,
    *,
    source: Callable[[], MacroDataSource],
    series: Sequence[str],
) -> dict[str, list[MacroObservation]]:
    """The cache if it exists, otherwise one fetch that is then frozen."""
    cached = read_macro_cache(path)
    if cached is not None:
        return cached
    resolved = source()
    fetched: dict[str, list[MacroObservation]] = {}
    for name in series:
        fetched[name] = await resolved.fetch_series(name)
    write_macro_cache(path, fetched)
    return fetched


def macro_coverage(macro: dict[str, list[MacroObservation]], as_of: datetime) -> dict[str, int]:
    """Observations at or before `as_of`, per series.

    The same predicate `ReplayMacroSource` filters on, asked ahead of the run
    rather than discovered from a fit failure afterwards. A zero here means the
    warm start will pair every bar with nothing for that series.
    """
    return {
        name: sum(1 for o in observations if o.ts <= as_of) for name, observations in macro.items()
    }
