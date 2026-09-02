"""The advisory has never seen portfolio risk, and two fields were dropped.

Measured 2 September 2026: `portfolio_check` appears in 63 of 3,596 audit rows,
because it is written one rail AFTER the governor's position-count refusal and
the book has been at 10 of 10 since 31 August. Of the 63 that DO carry one,
`var_99` and `single_name_pct` are non-null in all 63 and were discarded anyway
by a hardcoded two-name tuple.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from qat.domain.risk_engine.book_risk import BookRisk
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
        "at_last_decision": {
            "var_95": 0.0108,
            "var_99": 0.0148,
            "es_975": 0.0166,
            "single_name_pct": 0.125,
            "sector_pct": 0.125,
        }
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

    assert "sector_pct" not in risk_metrics(runtime)["at_last_decision"]
    assert risk_metrics(runtime)["at_last_decision"]["var_99"] == 0.0148


def _book_risk(**overrides) -> BookRisk:
    base = dict(
        computed_at=datetime(2026, 9, 2, 17, 0, tzinfo=UTC),
        symbols=10,
        observations=299,
        var_95=0.011,
        var_99=0.015,
        es_975=0.017,
        single_name_pct=0.12,
        sector_pct=0.15,
        notes=(),
    )
    base.update(overrides)
    return BookRisk(**base)


class _Monitor:
    def __init__(self, value):
        self._value = value

    def fresh(self, now=None):
        return self._value


def test_a_fresh_book_measurement_reaches_the_model():
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _Monitor(_book_risk())

    metrics = risk_metrics(runtime)

    assert metrics["book_now"]["var_95"] == 0.011
    assert metrics["book_now"]["single_name_pct"] == 0.12
    assert "at_last_decision" not in metrics
    assert "book_now_notes" not in metrics


def test_a_stale_book_measurement_is_absent_not_stale():
    """fresh() already returns None past the bound; risk_metrics must not
    reach around it to self.latest."""
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _Monitor(None)

    assert risk_metrics(runtime) == {}


def test_notes_travel_with_the_measurement():
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _Monitor(
        _book_risk(var_95=None, var_99=None, es_975=None, notes=("only 4 observations",))
    )

    metrics = risk_metrics(runtime)

    assert "var_95" not in metrics["book_now"]
    assert metrics["book_now_notes"] == ["only 4 observations"]


def test_both_groups_when_both_exist():
    runtime = _runtime_with_audit_entries(
        [_entry(inputs={"portfolio_check": {"var_95": 0.02, "es_975": 0.03}})]
    )
    runtime.book_risk_monitor = _Monitor(_book_risk())

    metrics = risk_metrics(runtime)

    assert metrics["book_now"]["var_95"] == 0.011
    assert metrics["at_last_decision"] == {"var_95": 0.02, "es_975": 0.03}


def test_neither_group_is_still_an_empty_dict():
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = None

    assert risk_metrics(runtime) == {}
