"""What a run may and may not be quoted as saying (W2 step 6).

A result whose provenance is not recorded is a result nobody can reproduce, and
this project's argument throughout is that figures must be derived rather than
remembered.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from qat.domain.backtester.manifest import (
    _STATED_LIMITATIONS,
    Observability,
    build_manifest,
    read_manifest,
)

_FIELDS = ["timestamp", "symbol", "approved", "final_shares", "stop_price", "reason", "inputs"]


def _decisions(directory: Path, rows: list[dict[str, object]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "risk_decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": "2026-07-31T15:00:00+00:00",
                    "symbol": "AAA",
                    "approved": row.get("approved", "False"),
                    "final_shares": "0.0",
                    "stop_price": "",
                    "reason": row.get("reason", ""),
                    "inputs": json.dumps(row.get("inputs", {})),
                }
            )


def _manifest(directory: Path, disabled: list[str] | None = None):
    return build_manifest(
        data_dir=directory,
        disabled=disabled or [],
        universe=["AAA"],
        starting_equity=100_000.0,
    )


def test_a_rail_that_bound_is_counted(tmp_path: Path):
    _decisions(
        tmp_path,
        [{"reason": "already at the 10-position limit (10 held or pending)"}] * 3,
    )

    manifest = _manifest(tmp_path)

    assert manifest.rails["position_limit"].bound_count == 3
    assert manifest.rails["position_limit"].exercised is True


def test_a_rail_that_never_bound_reports_not_exercised(tmp_path: Path):
    """Never "no difference". A zero gets quoted and a caveat does not."""
    _decisions(tmp_path, [{"reason": "already at the 10-position limit (10 held or pending)"}])

    manifest = _manifest(tmp_path)

    assert manifest.rails["sector_cap"].bound_count == 0
    assert manifest.rails["sector_cap"].exercised is False
    assert manifest.rails["sector_cap"].observability is Observability.REFUSAL


def test_a_rail_the_audit_trail_cannot_see_says_so(tmp_path: Path):
    """The churn cap refuses inside `_submit_entry` with a log line and a bare
    return - no risk decision is written at all. Reporting it as "not exercised"
    would claim it did not bind, when the truth is that this ledger cannot say.

    That is the corporate-actions failure of 12 August in miniature: a monitor
    that swallowed a query made blindness indistinguishable from a quiet book.
    """
    _decisions(tmp_path, [])

    manifest = _manifest(tmp_path)

    for rail in ("churn_cap", "minimum_hold", "time_stop"):
        assert manifest.rails[rail].observability is Observability.UNOBSERVABLE
        assert manifest.rails[rail].bound_count is None
        assert manifest.rails[rail].exercised is False


def test_a_scalar_rail_is_counted_from_the_inputs_not_from_a_refusal(tmp_path: Path):
    """The regime gate never refuses - it multiplies size. Its binding is a
    scalar below 1.0, which the audit trail does record."""
    _decisions(
        tmp_path,
        [
            {"approved": "True", "reason": "approved", "inputs": {"regime_scalar": 0.4}},
            {"approved": "True", "reason": "approved", "inputs": {"regime_scalar": 1.0}},
            {"approved": "True", "reason": "approved", "inputs": {"regime_scalar": 0.7}},
        ],
    )

    manifest = _manifest(tmp_path)

    assert manifest.rails["regime_gate"].observability is Observability.SCALAR
    assert manifest.rails["regime_gate"].bound_count == 2, "1.0 is the rail not binding"
    assert manifest.rails["regime_gate"].exercised is True


def test_a_disabled_rail_is_recorded_as_disabled(tmp_path: Path):
    _decisions(tmp_path, [])

    manifest = _manifest(tmp_path, disabled=["cost_to_risk"])

    assert manifest.rails["cost_to_risk"].enabled is False
    assert manifest.rails["position_limit"].enabled is True


def test_the_imperfect_rails_carry_their_caveat(tmp_path: Path):
    _decisions(tmp_path, [])

    manifest = _manifest(tmp_path, disabled=["cost_to_risk"])

    assert "1R" in (manifest.rails["cost_to_risk"].caveat or "")
    assert manifest.rails["position_limit"].caveat is None


def test_live_agreement_is_read_from_the_gate_not_typed(tmp_path: Path):
    """Derived. Four hand-maintained counts in this project were wrong inside
    three days."""
    _decisions(tmp_path, [])

    manifest = _manifest(tmp_path)

    agreement = manifest.rails["position_limit"].live_agreement
    assert "37" in agreement, "the count matters as much as the rate - 0% over 1 is not 0% over 37"
    assert manifest.rails["sector_cap"].live_agreement == "unvalidated"


def test_it_round_trips(tmp_path: Path):
    _decisions(
        tmp_path,
        [{"reason": "aggregate risk-at-stop 5.01% is at or above the 5.00% cap"}],
    )
    manifest = _manifest(tmp_path)

    manifest.write(tmp_path / "manifest.json")
    again = read_manifest(tmp_path / "manifest.json")

    assert again.rails["aggregate_risk_cap"].bound_count == 1
    assert again.rails["churn_cap"].bound_count is None
    assert again.rails["churn_cap"].observability is Observability.UNOBSERVABLE
    assert again.starting_equity == 100_000.0
    assert again.code_commit


def test_a_refusal_outside_the_modelled_rails_is_reported_as_unmodelled(tmp_path: Path):
    """Found by running the ASX replay: the cash floor refused 15 candidates,
    `rail_of` labels it `Cash floor`, and no ablatable rail claims that label -
    `min_cash_reserve` is deliberately not in `RAILS` (config.py:416-421). A
    rail the ledger saw bind must not vanish from the manifest entirely."""
    _decisions(
        tmp_path,
        [
            {
                "reason": (
                    "Insufficient cash: $500.00 available less $1,000.00 reserve "
                    "affords no shares at $50.00"
                )
            }
        ]
        * 15,
    )

    manifest = _manifest(tmp_path)

    assert manifest.unmodelled_refusals == {"Cash floor": 15}
    assert "Cash floor" not in manifest.rails


def test_unmodelled_refusals_is_empty_when_every_refusal_is_a_modelled_rail(tmp_path: Path):
    _decisions(
        tmp_path,
        [{"reason": "already at the 10-position limit (10 held or pending)"}],
    )

    manifest = _manifest(tmp_path)

    assert manifest.unmodelled_refusals == {}


def test_approvals_do_not_contribute_to_unmodelled_refusals(tmp_path: Path):
    _decisions(
        tmp_path,
        [{"approved": "True", "reason": "approved", "inputs": {"regime_scalar": 1.0}}],
    )

    manifest = _manifest(tmp_path)

    assert manifest.unmodelled_refusals == {}


def test_unmodelled_refusals_round_trips(tmp_path: Path):
    _decisions(
        tmp_path,
        [
            {
                "reason": (
                    "Insufficient cash: $500.00 available less $1,000.00 reserve "
                    "affords no shares at $50.00"
                )
            }
        ]
        * 15,
    )
    manifest = _manifest(tmp_path)

    manifest.write(tmp_path / "manifest.json")
    again = read_manifest(tmp_path / "manifest.json")

    assert again.unmodelled_refusals == {"Cash floor": 15}


def test_the_manifest_names_the_fill_model_and_the_limitations(tmp_path: Path):
    """Stated on every run, not buried in a footnote."""
    _decisions(tmp_path, [])

    manifest = _manifest(tmp_path)

    assert manifest.fill_model["stop_wins_ambiguous_bar"] is True
    assert manifest.fill_model["entry"] == "next_open"
    assert any("survivorship" in limit.lower() for limit in manifest.stated_limitations)
    assert any("earnings" in limit.lower() for limit in manifest.stated_limitations)
    assert any("regime" in limit.lower() for limit in manifest.stated_limitations)


def test_extra_limitations_are_appended_to_the_stated_ones(tmp_path: Path) -> None:
    """A run knows things the module cannot - the ASX replay's macro is US, and
    the manifest is where that is recorded rather than remembered."""
    manifest = build_manifest(
        data_dir=tmp_path,
        disabled=[],
        universe=["BHP.AX"],
        starting_equity=100_000.0,
        extra_limitations=("The macro series are US.",),
    )

    assert manifest.stated_limitations[-1] == "The macro series are US."
    assert len(manifest.stated_limitations) == len(_STATED_LIMITATIONS) + 1


def test_the_default_limitations_are_unchanged_when_none_are_added(tmp_path: Path) -> None:
    manifest = build_manifest(
        data_dir=tmp_path, disabled=[], universe=["BHP.AX"], starting_equity=100_000.0
    )

    assert manifest.stated_limitations == _STATED_LIMITATIONS
