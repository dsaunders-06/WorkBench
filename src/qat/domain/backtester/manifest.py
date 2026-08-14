"""What a run may and may not be quoted as saying (W2 step 6).

A result whose provenance is not recorded is a result nobody can reproduce, and
this project's argument throughout is that figures must be derived rather than
remembered.

Three fields carry the scoping the operator approved on 13 August, after G1
showed that NO RAIL HAS A VALIDATED AGREEMENT RATE against the live book:

* `bound_count` - how often the rail bound in THIS run, derived from the run's
  own `risk_decisions.csv` through the existing `refusals.rail_of`. Never a
  private copy of that classifier: two derivations of "which rail bound" would
  eventually disagree, and an operator reading one while the other produced the
  number would have no way to tell which was right.
* `exercised` - whether the rail bound at all. A rail that never bound reports
  NOT EXERCISED, never "no difference".
* `live_agreement` - read from the verdict `run_g1.py` writes, not typed.

## Three observabilities, not two

The plan for this module assumed every rail either bound or did not. It does
not survive contact with the code:

* **REFUSAL** - the rail writes a row to `risk_decisions.csv` naming itself.
  Eight rails do, and `rail_of` already knows their wording.
* **SCALAR** - the rail never refuses, it multiplies SIZE. The regime gate and
  the earnings trim are of this kind, and their binding is visible in the
  decision's `inputs` rather than in its reason.
* **UNOBSERVABLE** - the rail refuses somewhere that writes no audit row at
  all. `SignalToOrderBridge._submit_entry` turns down an entry over the weekly
  churn cap with a `logger.info` and a bare `return`; the minimum hold and the
  time stop block exits the same way.

The distinction is not pedantry. Reporting an unobservable rail as "not
exercised" asserts it did not bind, when the truth is that this ledger cannot
say - which is the corporate-actions failure of 12 August in miniature, where a
swallowed query made blindness indistinguishable from a quiet book.

## A fourth gap: rails this table does not model at all

The three observabilities above assume every refusal belongs to one of the
rails in `[*RAILS, REGIME_RAIL]`. It does not: `refusals._PATTERNS`
recognises materially more labels than that static list names, and any of
them can write refusals into `risk_decisions.csv` while having no row in the
table at all. Found by running the ASX replay, where the cash floor
(`min_cash_reserve` - deliberately not ablatable, see its field in
`config.py`, where `gt=0` is what makes it structural) refused 15 candidates
and left no trace anywhere in `manifest.json`.

`unmodelled_refusals` closes that gap by reporting, rather than by extending
the static list: every `rail_of` label this run saw refuse that no rail in
the table claims. A rail this table does not model still binds, and silence
about it reads as absence - the same failure the `Observability` argument
exists to prevent, one level up.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from qat.domain.backtester.ablation import IMPERFECT, RAILS, REGIME_RAIL
from qat.domain.evaluation.refusals import load_risk_decisions, rail_of
from qat.version import _git

_G1_VERDICT = (
    Path(__file__).resolve().parents[4] / "scripts" / "analysis" / "g1" / "g1_verdict.json"
)


class Observability(StrEnum):
    """How, or whether, this run can see the rail bind."""

    REFUSAL = "refusal"
    SCALAR = "scalar"
    UNOBSERVABLE = "unobservable"


# The ablation name on the left, `refusals.rail_of`'s label on the right. Two
# vocabularies meet here and nowhere else: one names a config knob, the other
# names what an operator calls the rail on a report.
_REFUSAL_LABELS: dict[str, str] = {
    "position_limit": "Position limit",
    "aggregate_risk_cap": "Aggregate risk-at-stop cap",
    "single_name_cap": "Single-name concentration cap",
    "sector_cap": "Sector concentration cap",
    "correlated_cluster": "Correlated-cluster cap",
    "gap_risk": "Gap-risk budget",
    "portfolio_es": "Portfolio ES limit",
    "cost_to_risk": "Cost-to-risk (trade too small)",
}

# Rails that multiply size instead of refusing. The key is the field
# `RiskEngine.evaluate_order` writes into a decision's `inputs`.
_SCALAR_INPUTS: dict[str, str] = {
    REGIME_RAIL: "regime_scalar",
    "earnings_trim": "earnings_event_scalar",
}

# Rails that refuse where nothing is audited, with the reason stated rather than
# left for a reader to discover.
_UNOBSERVABLE: dict[str, str] = {
    "churn_cap": (
        "SignalToOrderBridge._submit_entry logs and returns without writing a risk decision"
    ),
    "minimum_hold": "blocks an exit inside the bridge; no risk decision is written",
    "time_stop": "an exit trigger rather than a refusal; it produces no risk decision",
}

_FILL_MODEL: dict[str, object] = {
    "stop_wins_ambiguous_bar": True,
    "gap_through_stop": "open",
    "gap_through_target": "target",
    "entry": "next_open",
    "stop_can_fire_on_entry_bar": True,
}

_STATED_LIMITATIONS: tuple[str, ...] = (
    "Survivorship: the universe is a static 2026 megacap snapshot, not "
    "point-in-time index membership.",
    "The earnings rail is inert - NullEarningsCalendar, so M57's trim never fires "
    "and some entries are sized LARGER than live would size them.",
    "The fill model is pessimistic, so expectancy is a floor rather than an estimate.",
    "Daily bars only. Entry timing and fill rate are out of reach.",
    "The regime rail is nearly constant on daily bars - hysteresis and a 20-bar "
    "refit make it far stickier than live's intraday reclassification, which "
    "held one label across the whole G1 window against live's 0.4/0.7/1.0.",
    "No rail has a validated live agreement rate, so a difference measured here "
    "is what a rail costs THIS INSTRUMENT, not what it costs the live book.",
)


@dataclass(frozen=True, slots=True)
class RailRecord:
    enabled: bool
    observability: Observability
    # None when the rail is UNOBSERVABLE - "this ledger cannot say" rather than
    # zero, which would read as "it did not bind".
    bound_count: int | None
    exercised: bool
    live_agreement: str
    caveat: str | None = None


@dataclass(frozen=True, slots=True)
class RunManifest:
    created_at: str
    code_commit: str
    code_dirty: bool
    rails: dict[str, RailRecord]
    universe: tuple[str, ...]
    starting_equity: float
    fill_model: dict[str, object] = field(default_factory=lambda: dict(_FILL_MODEL))
    # Refusals `risk_decisions.csv` recorded for a `rail_of` label that no rail
    # in `rails` claims - see the module docstring. `None` draws the same
    # distinction `RailRecord.bound_count` draws for an UNOBSERVABLE rail:
    # "this manifest cannot say" rather than zero. `{}` is checked and clean -
    # a run with nothing unmodelled says so rather than omitting the field.
    # `build_manifest` always sets a real dict, possibly empty; only a
    # manifest written before this field existed reads back as `None`.
    unmodelled_refusals: dict[str, int] | None = field(default=None)
    stated_limitations: tuple[str, ...] = _STATED_LIMITATIONS

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")


def read_manifest(path: Path) -> RunManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw_unmodelled = raw.get("unmodelled_refusals")
    return RunManifest(
        created_at=raw["created_at"],
        code_commit=raw["code_commit"],
        code_dirty=raw["code_dirty"],
        rails={
            name: RailRecord(
                enabled=record["enabled"],
                observability=Observability(record["observability"]),
                bound_count=record["bound_count"],
                exercised=record["exercised"],
                live_agreement=record["live_agreement"],
                caveat=record["caveat"],
            )
            for name, record in raw["rails"].items()
        },
        universe=tuple(raw["universe"]),
        starting_equity=float(raw["starting_equity"]),
        fill_model=raw["fill_model"],
        # `.get(...)`, not `raw[...]`: a manifest written before this field
        # existed must still load. Its absence reads as `None` - "not
        # recorded" - rather than `{}`, which would assert "checked and
        # clean" about a manifest that never checked. Same idiom as
        # `RailRecord.bound_count`.
        unmodelled_refusals=dict(raw_unmodelled) if raw_unmodelled is not None else None,
        stated_limitations=tuple(raw["stated_limitations"]),
    )


def _commit() -> tuple[str, bool]:
    """The commit, and whether the tree was dirty.

    Uses `version._git`, which already exists and already handles every failure
    mode this needs - no git on PATH, not a repository, a git that hangs - and
    already carries the security review for running it. A second subprocess
    helper here would be a second thing to keep in step, in a module written to
    argue that figures should be derived once rather than restated.

    Unknown rather than raising: a manifest is provenance, and failing to
    produce one must never destroy a run that has already happened. An unknown
    commit reads as DIRTY, because it cannot be shown otherwise and provenance
    should fail towards doubt.
    """
    head = _git("rev-parse", "--short", "HEAD")
    if head is None:
        return "unknown", True
    # `_git` returns None for empty output, which is exactly what a clean tree
    # produces - so None here means clean rather than failed.
    return head, _git("status", "--porcelain") is not None


def _live_agreement() -> dict[str, str]:
    """G1's per-rail verdict, keyed by `rail_of` label.

    The COUNT is carried alongside the rate deliberately: 0% over one
    symbol-day and 0% over thirty-seven are different facts, and the position
    limit is the second.
    """
    if not _G1_VERDICT.exists():
        return {}
    try:
        raw = json.loads(_G1_VERDICT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        label: f"{record['rate']:.0%} over {record['considered']} symbol-day(s)"
        for label, record in (raw.get("rails") or {}).items()
    }


def _refusal_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if str(row.get("approved", "")).strip().lower() == "true":
            continue
        # Matching `refusals.summarise_refusals`, which also skips a blank
        # reason, deliberately: this module's whole argument is that one fact
        # should have one derivation, and the two must not visibly disagree
        # about what counts as a refusal (finding 6).
        reason = (row.get("reason") or "").strip()
        if not reason:
            continue
        label = rail_of(reason)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _scalar_count(rows: list[dict[str, str]], key: str) -> int:
    """Decisions where this size multiplier actually bit.

    A scalar of 1.0 is the rail present and NOT binding, which is exactly the
    distinction `exercised` exists to draw - the regime rail sat at 1.0 for the
    entire G1 window while nothing was wrong with it except that it was inert.
    """
    bound = 0
    for row in rows:
        try:
            inputs = json.loads(row.get("inputs") or "{}")
        except ValueError:
            continue
        value = inputs.get(key)
        if value is None:
            continue
        try:
            if abs(float(value) - 1.0) > 1e-9:
                bound += 1
        except (TypeError, ValueError):
            continue
    return bound


def build_manifest(
    *,
    data_dir: Path,
    disabled: Sequence[str],
    universe: Sequence[str],
    starting_equity: float,
    extra_limitations: Sequence[str] = (),
) -> RunManifest:
    rows = load_risk_decisions(data_dir)
    refusals = _refusal_counts(rows)
    agreement = _live_agreement()
    disabled_set = set(disabled)

    rails: dict[str, RailRecord] = {}
    # Labels the loop below actually claimed, accumulated as it runs rather
    # than read back from `_REFUSAL_LABELS.values()` afterwards. If a rail is
    # ever removed from `RAILS` while its `_REFUSAL_LABELS` entry survives,
    # this loop simply never visits it - so a set built from what the loop
    # claimed excludes it too, correctly, where a set built from the static
    # mapping would not (finding 2).
    claimed_labels: set[str] = set()
    for name in [*RAILS, REGIME_RAIL]:
        if name in _UNOBSERVABLE:
            observability = Observability.UNOBSERVABLE
            count: int | None = None
            exercised = False
            label = None
        elif name in _SCALAR_INPUTS:
            observability = Observability.SCALAR
            count = _scalar_count(rows, _SCALAR_INPUTS[name])
            exercised = count > 0
            label = None
        else:
            observability = Observability.REFUSAL
            label = _REFUSAL_LABELS[name]
            count = refusals.get(label, 0)
            exercised = count > 0
        if label is not None:
            claimed_labels.add(label)
        rails[name] = RailRecord(
            enabled=name not in disabled_set,
            observability=observability,
            bound_count=count,
            exercised=exercised,
            live_agreement=agreement.get(label, "unvalidated") if label else "unvalidated",
            caveat=IMPERFECT.get(name),
        )

    # Every label `rail_of` produced for a real refusal, minus the ones a rail
    # in the table above actually claimed - not `_REFUSAL_LABELS.values()`,
    # which names what the static mapping COULD claim regardless of whether
    # the loop above ever ran for it. Anything not claimed - including
    # UNCLASSIFIED, under whatever name `rail_of._leading_clause` gave it -
    # belongs here.
    unmodelled = {label: count for label, count in refusals.items() if label not in claimed_labels}

    commit, dirty = _commit()
    return RunManifest(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        code_commit=commit,
        code_dirty=dirty,
        rails=rails,
        universe=tuple(universe),
        starting_equity=starting_equity,
        unmodelled_refusals=unmodelled,
        # APPENDED, never replacing: the six module-level limitations hold for
        # every run, and a caller adding one must not be able to drop them.
        stated_limitations=(*_STATED_LIMITATIONS, *extra_limitations),
    )
