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
    """The cache if it exists, otherwise one fetch that is then frozen.

    Raises:
        ValueError: if the cache exists but lacks a requested series, or if a
            fetch returns nothing for one. Both refuse rather than degrade -
            see the comments at each, and note that neither writes.
    """
    cached = read_macro_cache(path)
    if cached is not None:
        # A cache built for one set of series names can predate a caller asking
        # for a different set - the project's next step is adding Australian
        # series, and today's cache keys happen to match `fred_series` only by
        # coincidence. `macro_coverage` iterates the RETURNED dict, so a series
        # requested but absent from the cache would otherwise produce no
        # coverage entry, no complaint, and a constant column nothing here
        # would ever mention.
        missing = [name for name in series if name not in cached]
        if missing:
            raise ValueError(
                f"{path} does not contain {', '.join(missing)}, which was requested. "
                "This is a frozen research input and is never fetched to fill a gap - "
                "POINT AT A SEPARATE CACHE PATH for the new set of series. Deleting "
                "this one and re-fetching would replace an input every ablation "
                "already run rests on, and the replacement would load without "
                "complaint and compare against them as though nothing had changed."
            )
        # Only what was requested, not every key the file contains. A cache
        # can hold more series than one caller asks for - `run_ablation.py`
        # and `run_asx_replay.py` share this file - and `ReplaySession`
        # derives `macro_series=tuple(self._macro)` from whatever this
        # returns, so an extra cached series would feed the regime engine a
        # series set the deployed config never asked for.
        return {name: cached[name] for name in series}
    resolved = source()
    fetched: dict[str, list[MacroObservation]] = {}
    for name in series:
        fetched[name] = await resolved.fetch_series(name)
    # A silently fake research input is worse than no input - the same
    # argument `run_asx_replay.py` makes for refusing synthetic bars. No key
    # configured degrades `resolve_macro_source` to `MockMacroSource`, whose
    # `fetch_series` still returns something (one fabricated observation), so
    # this checks for EMPTY rather than for the mock: a rate-limited real fetch
    # that comes back with nothing is exactly as dangerous to freeze.
    empty = [name for name in series if not fetched[name]]
    if empty:
        raise ValueError(
            f"Fetch for {', '.join(empty)} returned no observations. Refusing to "
            f"freeze that into {path}: a research input that is silently fake or "
            "empty is worse than no input, and path.exists() would protect the "
            "gap forever once it is written."
        )
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
