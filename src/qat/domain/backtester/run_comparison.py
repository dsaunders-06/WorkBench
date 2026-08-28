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
from collections.abc import Sequence
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


_REGIME_PATH = "regime_path.csv"
_REGIME_FIELDS = ("ts", "label", "exposure_scalar")


def write_regime_path(directory: Path, rows: Sequence[tuple[str, str, float]]) -> None:
    """One bar, one row: what the regime engine PUBLISHED during a run.

    ⚠️ `risk_decisions.csv` cannot serve this. It carries `regime_label` only on
    bars where a decision happened, so "the label never differed" would be
    indistinguishable from "no decisions happened" - which is the blindness
    `compare_runs` exists to refuse.

    One writer and one reader, used by the harness AND its tests: a test that
    re-implements the format is a second definition of it, and two definitions
    drift.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / _REGIME_PATH).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_REGIME_FIELDS)
        writer.writerows(rows)


def read_regime_path(directory: Path) -> list[tuple[str, str, float]]:
    """The regime path, or `[]` when the run wrote none.

    Empty is a legitimate outcome, not an error: an arm that never started the
    regime engine - `--rail regime_gate`'s ablated side - publishes nothing.
    """
    path = directory / _REGIME_PATH
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [(r["ts"], r["label"], float(r["exposure_scalar"])) for r in reader]


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


def _equity_line(name: str, manifest: RunManifest) -> str:
    if manifest.terminal_equity is None:
        return f"{name:<10}terminal equity not recorded by this run"
    return f"{name:<10}{manifest.terminal_equity:>14,.2f}"


def compare_feature_runs(baseline_dir: Path, ablated_dir: Path, feature: str) -> str:
    """Did the regime feature help? - asked of two runs of the harness.

    ⚠️ **The headline is TERMINAL EQUITY, not R.** `_arm` reports trades, win%
    and R-multiple, all scale-free. A regime feature moves the exposure scalar,
    which moves position SIZE - so a feature that halved every position leaves
    every figure the rail report prints identical. The trades block is kept
    BENEATH the equity, because a changed trade SET is a different fact from a
    changed size and both are worth seeing.

    Guard-first, like `compare_runs`: if the label never differed there was
    nothing to change.
    """
    baseline = read_manifest(baseline_dir / "manifest.json")
    ablated = read_manifest(ablated_dir / "manifest.json")

    if ablated.regime_features is not None and feature in ablated.regime_features:
        return _blocked(
            feature,
            f"STILL ENABLED - {feature!r} is in the ablated arm's own feature list.",
            [
                "The two arms are not baseline-and-ablated. This is cheap to cause by "
                "passing the wrong directory and invisible unless something checks, so "
                "the comparison is refused rather than reported.",
            ],
        )

    base_path = read_regime_path(baseline_dir)
    abl_path = read_regime_path(ablated_dir)

    if len(base_path) != len(abl_path):
        return _blocked(
            feature,
            f"NOT COMPARABLE - the arms published {len(base_path)} and {len(abl_path)} "
            f"regime bars.",
            [
                "Paths of different lengths cannot be compared bar for bar. Zipping them "
                "would silently pair one arm's day against the other's next day - the "
                "calendar-slip failure of 26 August with a different cause.",
            ],
        )

    differing = [
        (b[0], b[1], a[1]) for b, a in zip(base_path, abl_path, strict=True) if b[1] != a[1]
    ]
    window = (
        f"{base_path[0][0][:10]} to {base_path[-1][0][:10]}" if base_path else "no bars published"
    )

    if not differing:
        return _blocked(
            feature,
            f"NOT EXERCISED - the regime label was identical on all {len(base_path)} bars.",
            [
                f"Removing {feature!r} contributes nothing to the label over this window, "
                f"so any difference between the arms is noise wearing its name and is "
                f"suppressed rather than printed as a zero.",
                "⚠️ That is an ANSWER, not a failed run: a column the label does not "
                "depend on is a column to propose removing, recorded with its numbers.",
                f"Window: {window}.",
            ],
        )

    # ⚠️ HOW CONTESTABLE THE LABEL WAS, printed beside how often it moved -
    # because the second cannot be read without the first (28 August). Measured
    # on two disjoint windows: an EARLIER one that was 78% bear with 3
    # transitions, and a LATER one with six labels and 8. The same three
    # features scored 16-21% on the monotone window and 56-73% on the diverse
    # one. A label that barely moves cannot be moved by removing a feature, so
    # a bare percentage measures the WINDOW as much as the column.
    counts: dict[str, int] = {}
    for _ts, label, _scalar in base_path:
        counts[label] = counts.get(label, 0) + 1
    transitions = sum(1 for a, b in zip(base_path, base_path[1:], strict=False) if a[1] != b[1])
    spread = ", ".join(
        f"{name} {n / len(base_path):.0%}"
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )

    lines = [
        f"=== feature: {feature} ===",
        "",
        "TERMINAL EQUITY - the only figure a feature can move, because it moves SIZE:",
        _equity_line("baseline", baseline),
        _equity_line("ablated", ablated),
    ]
    if baseline.terminal_equity is not None and ablated.terminal_equity is not None:
        delta = ablated.terminal_equity - baseline.terminal_equity
        lines.append(f"{'delta':<10}{delta:>+14,.2f}")
    lines += [
        "",
        f"The label differed on {len(differing)} of {len(base_path)} bars "
        f"({len(differing) / len(base_path):.0%}).",
        f"Window: {window}.",
        "",
        _wrap(
            f"⚠️ The baseline label was {spread} across {transitions} transition(s). A "
            f"window whose label barely moves cannot have it moved by removing a column, "
            f"so the percentage above measures how CONTESTABLE this window was as much as "
            f"how influential the feature is. Compare only against another feature on the "
            f"SAME window, and replicate on a disjoint one before acting."
        ),
        "",
        "Trades - a changed SET, which is a different fact from a changed size:",
        _arm("baseline", baseline, _trades(baseline_dir)),
        _arm("ablated", ablated, _trades(ablated_dir)),
        "",
        _wrap(_SCOPE),
    ]
    return "\n".join(lines)
