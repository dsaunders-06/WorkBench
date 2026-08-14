"""Did the rail help? - asked of two runs of the harness (W2 step 6).

IT LEADS WITH A GUARD RATHER THAN A NUMBER, and that is the whole design. If
the rail did not bind in the BASELINE run, there was nothing for its removal to
change, and any difference between the two arms is noise wearing the rail's
name. The figure is suppressed entirely rather than printed as a zero beside a
caveat: a zero gets quoted and a caveat does not.

Four ways a comparison can be meaningless, and each says which:

* **NOT EXERCISED** - the rail can be seen, and never bound. Ablating it
  measured nothing. On the G1 window the position limit is exactly this, which
  is the accepted fidelity limit doing its job rather than a failure.
* **NOT OBSERVABLE** - the rail refuses where nothing is audited, so the record
  cannot say whether it bound. Different from zero, which would assert that it
  did not.
* **STILL ENABLED** - the ablated arm did not actually have the rail off. Cheap
  to cause by passing the wrong directory, and invisible in the output unless
  something checks.
* **UNKNOWN RAIL** - named rather than guessed at.

The claim is scoped in the report itself. As of 13 August no rail has a
validated live agreement rate, so a difference measured here says what a rail
costs THIS INSTRUMENT - never what it costs the live book.
"""

from __future__ import annotations

import csv
import textwrap
from pathlib import Path

from qat.domain.backtester.manifest import Observability, RailRecord, RunManifest, read_manifest

# Wrapped to a width a terminal shows without folding. Rendered rather than
# assumed: the first version emitted the scope note and every guard body as one
# unbroken line, which every test passed straight through.
_WIDTH = 78

_SCOPE = (
    "Measured inside the harness. No rail has a validated live agreement rate, so this is "
    "what the rail costs THIS INSTRUMENT, not what it costs the live book."
)


def _trades(directory: Path) -> list[dict[str, str]]:
    path = directory / "closed_trades.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _r_multiples(rows: list[dict[str, str]]) -> list[float]:
    """Only the trades that carry one. A lot opened before this system knew its
    stop has no R, and counting it as zero would drag every mean toward it."""
    out: list[float] = []
    for row in rows:
        raw = (row.get("r_multiple") or "").strip()
        if not raw:
            continue
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _arm(name: str, manifest: RunManifest, rows: list[dict[str, str]]) -> str:
    r_values = _r_multiples(rows)
    if not r_values:
        return f"{name:<10}{len(rows):>7} trades        no R-multiples recorded"
    wins = sum(1 for r in r_values if r > 0)
    total = sum(r_values)
    return (
        f"{name:<10}{len(rows):>7} trades"
        f"{wins / len(r_values):>7.0%} win"
        f"{total / len(r_values):>+8.2f}R mean"
        f"{total:>9.2f}R total"
        f"   [{manifest.code_commit}{'*' if manifest.code_dirty else ''}]"
    )


def _wrap(text: str) -> str:
    return textwrap.fill(text, width=_WIDTH)


def _blocked(rail: str, headline: str, body: list[str]) -> str:
    """A headline, a blank line, then the paragraphs - so the reason a
    comparison was refused is the first thing read and the argument for it does
    not run into it."""
    wrapped = [_wrap(paragraph) if paragraph else "" for paragraph in body]
    return "\n\n".join([f"=== {rail} ===", headline, *wrapped]).rstrip()


def _guard(rail: str, record: RailRecord, ablated: RailRecord) -> str | None:
    """The reason this comparison cannot be read, or None if it can."""
    if ablated.enabled:
        return _blocked(
            rail,
            f"STILL ENABLED - {rail} is not disabled in the ablated run.",
            [
                "Both arms ran the same configuration, so any difference between them is "
                "noise. Check that the ablated directory is the one produced with this "
                "rail switched off.",
            ],
        )
    if record.observability is Observability.UNOBSERVABLE:
        return _blocked(
            rail,
            f"NOT OBSERVABLE - the audit trail cannot say whether {rail} bound.",
            [
                "This rail refuses where nothing is written to risk_decisions.csv, so its "
                "binding count is unknown rather than zero. A difference between these two "
                "arms may be real, and this record cannot attribute it.",
            ],
        )
    if not record.exercised:
        return _blocked(
            rail,
            f"NOT EXERCISED - {rail} never bound in the baseline run.",
            [
                "This comparison measures nothing about that rail.",
                "Ablating a rail that never binds cannot produce evidence about it: there "
                "was nothing for its removal to change, so any difference between the arms "
                "belongs to something else. Either the window never reaches the condition "
                "the rail governs, or the harness cannot reach it by construction - the "
                "position limit is the known case of the second.",
            ],
        )
    return None


def compare_runs(baseline_dir: Path, ablated_dir: Path, rail: str) -> str:
    baseline = read_manifest(baseline_dir / "manifest.json")
    ablated = read_manifest(ablated_dir / "manifest.json")

    record = baseline.rails.get(rail)
    ablated_record = ablated.rails.get(rail)
    if record is None or ablated_record is None:
        known = ", ".join(sorted(baseline.rails))
        return _blocked(
            rail,
            f"{rail!r} is not a rail these manifests know.",
            [f"Known rails: {known}."],
        )

    blocked = _guard(rail, record, ablated_record)
    if blocked is not None:
        return blocked

    lines = [
        f"=== {rail} ===",
        "",
        _arm("baseline", baseline, _trades(baseline_dir)),
        _arm("ablated", ablated, _trades(ablated_dir)),
        "",
        f"{rail} bound {record.bound_count} time(s) in the baseline "
        f"({record.observability.value}).",
        f"Live agreement for this rail: {record.live_agreement}.",
    ]
    if record.caveat:
        lines.append(_wrap(f"Caveat: neutralising this rail is imperfect - it {record.caveat}."))
    lines += ["", _wrap(_SCOPE)]
    return "\n".join(lines)
