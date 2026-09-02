"""The advisory has never seen portfolio risk, and two fields were dropped.

Measured 2 September 2026: `portfolio_check` appears in 63 of 3,596 audit rows,
because it is written one rail AFTER the governor's position-count refusal and
the book has been at 10 of 10 since 31 August. Of the 63 that DO carry one,
`var_99` and `single_name_pct` are non-null in all 63 and were discarded anyway
by a hardcoded two-name tuple.
"""

from __future__ import annotations

from types import SimpleNamespace

from qat.presentation.advisory_account import risk_metrics


def _entry(inputs: dict) -> SimpleNamespace:
    return SimpleNamespace(inputs=inputs)


def _runtime_with_audit_entries(entries: list) -> SimpleNamespace:
    return SimpleNamespace(
        risk_engine=SimpleNamespace(audit_log=SimpleNamespace(entries=lambda: entries)),
        book_risk_monitor=None,
    )


def test_risk_metrics_returns_every_field_the_check_recorded():
    """var_99 and single_name_pct are non-null in 63 of 63 recorded rows and
    were dropped anyway by a hardcoded two-name tuple."""
    runtime = _runtime_with_audit_entries(
        [
            _entry(
                inputs={
                    "portfolio_check": {
                        "var_95": 0.0108,
                        "var_99": 0.0148,
                        "es_975": 0.0166,
                        "single_name_pct": 0.125,
                        "sector_pct": 0.125,
                    }
                }
            )
        ]
    )

    assert risk_metrics(runtime) == {
        "var_95": 0.0108,
        "var_99": 0.0148,
        "es_975": 0.0166,
        "single_name_pct": 0.125,
        "sector_pct": 0.125,
    }


def test_risk_metrics_omits_sector_pct_when_the_check_did_not_record_one():
    """sector_pct is null in 60 of 63 rows. Absent is omitted, not zeroed."""
    runtime = _runtime_with_audit_entries(
        [
            _entry(
                inputs={
                    "portfolio_check": {
                        "var_95": 0.0108,
                        "var_99": 0.0148,
                        "es_975": 0.0166,
                        "single_name_pct": 0.125,
                        "sector_pct": None,
                    }
                }
            )
        ]
    )

    assert "sector_pct" not in risk_metrics(runtime)
    assert risk_metrics(runtime)["var_99"] == 0.0148
