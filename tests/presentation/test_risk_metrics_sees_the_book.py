"""The advisory has never seen portfolio risk, and two fields were dropped.

Measured 2 September 2026: `portfolio_check` appears in 63 of 3,596 audit rows,
because it is written one rail AFTER the governor's position-count refusal and
the book has been at 10 of 10 since 31 August. Of the 63 that DO carry one,
`var_99` and `single_name_pct` are non-null in all 63 and were discarded anyway
by a hardcoded two-name tuple.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from qat.config import Settings
from qat.data.bars import MultiSymbolAggregator
from qat.data.broker.account_poller import AccountPoller
from qat.domain.risk_engine.book_risk import BookRisk, BookRiskMonitor
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


# --- a REAL BookRiskMonitor, not a stub ----------------------------------
#
# `_Monitor` above answers `fresh()` with whatever value it was built with,
# regardless of what it is asked or when - so it cannot tell a reader that
# calls `.latest` directly (bypassing the staleness bound entirely) apart
# from one that calls `.fresh()` correctly; both just return the value. It
# also ignores whatever `now` it is called with, so a reader that hands
# `fresh()` a NAIVE `datetime.now()` instead of no argument goes undetected
# too, even though the real `BookRiskMonitor.fresh()` raises on exactly that
# (an aware `computed_at` minus a naive `now`). The tests below drive the
# real class so the age bound and the tz-aware clock both actually gate
# something, not merely a fake that happens to agree.

_NOW = datetime(2026, 9, 2, 17, 0, tzinfo=UTC)


def _monitor_holding(age: timedelta) -> BookRiskMonitor:
    monitor = BookRiskMonitor(
        # fresh() touches neither account_poller nor bars (see its own
        # docstring), so a real poller/aggregator is not needed to exercise
        # it. `cast`, not a loosened signature - BookRiskMonitor's
        # constructor keeps its concrete types deliberately.
        account_poller=cast(AccountPoller, None),
        bars=cast(MultiSymbolAggregator, None),
        settings=Settings(_env_file=None),
        clock=lambda: _NOW,
    )
    monitor.latest = _book_risk(computed_at=_NOW - age)
    return monitor


def test_a_four_hour_old_book_is_absent_not_stale():
    """A realistic stand-in for the fake `_Monitor` above: 4 hours is well
    past the 180s default bound (Settings.book_risk_max_age_seconds), so
    fresh() must return None and this measurement must not reach the model -
    not stale, not zeroed, simply absent."""
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _monitor_holding(timedelta(hours=4))

    assert risk_metrics(runtime) == {}


def test_a_measurement_inside_the_bound_still_reaches_the_model():
    """The other half of the same bound: proves the test above is gating on
    age rather than simply failing to observe a real monitor at all."""
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _monitor_holding(timedelta(seconds=30))

    metrics = risk_metrics(runtime)

    assert metrics["book_now"]["var_95"] == 0.011


def test_book_now_carries_its_own_age_in_seconds():
    """The only figure telling the model how old `book_now` is - the field
    closest to the four-hour-old-book incident above. Deleting the
    `book_now_age_seconds` assignment in risk_metrics() leaves every other
    test in this file green."""
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _Monitor(_book_risk())

    metrics = risk_metrics(runtime)

    assert "book_now_age_seconds" in metrics
    assert metrics["book_now_age_seconds"] >= 0


def test_a_non_finite_recorded_figure_never_reaches_the_model():
    """⚠️ The LAST route by which a nan or inf could reach the advisory.

    Three review rounds hardened the live path against non-finite weights,
    equity and return observations. This group was widened from two field names
    to five and never revisited, so it was filtered only on `is not None`. A
    recorded `var_95` of 0.0 alongside an `es_975` of inf is the milestone's own
    hazard - a measured zero about tail risk nobody measured - arriving through
    the group that was not hardened. `nan > limit` is also always False, so a nan
    concentration would pass every downstream comparison silently.
    """
    runtime = _runtime_with_audit_entries(
        [
            _entry(
                inputs={
                    "portfolio_check": {
                        "var_95": 0.0108,
                        "var_99": float("inf"),
                        "es_975": float("nan"),
                        "single_name_pct": float("-inf"),
                        "sector_pct": 0.125,
                    }
                }
            )
        ]
    )

    at_last_decision = risk_metrics(runtime)["at_last_decision"]

    assert at_last_decision == {"var_95": 0.0108, "sector_pct": 0.125}
    for name in ("var_99", "es_975", "single_name_pct"):
        assert name not in at_last_decision
