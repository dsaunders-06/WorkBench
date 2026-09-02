"""The VaR tiles have shown "-" since 31 August, and nothing was broken.

They read `audit_log.entries()[-1].inputs["portfolio_check"]` and returned early
when it was absent - which is every startup, because the audit log is in-memory,
and every 10-of-10 day, because the governor refuses one rail before that dict is
written. They now read the book actually held, with the last decision's figure as
a caption BENEATH, and only when there is one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.config import Settings
from qat.domain.risk_engine.audit import RiskDecision
from qat.domain.risk_engine.book_risk import BookRisk
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _book_risk(**overrides) -> BookRisk:
    base = dict(
        computed_at=datetime.now(UTC),
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
    name = "book-risk-monitor"

    def __init__(self, value):
        self._value = value

    def fresh(self, now=None):
        return self._value


def _entry(inputs: dict) -> RiskDecision:
    """A real `RiskDecision` (audit.py:48-59), not a bare `SimpleNamespace`.

    `_entries` is annotated `list[RiskDecision]` (audit.py:70), and
    `refresh_refusals` - which every `_on_timer_tick` also drives - reads
    `.symbol`/`.approved`/`.reason` off each entry. A `SimpleNamespace` with
    only `.inputs` violates that type and crashes the first stray timer tick
    that reaches a later test; a real dataclass costs nothing extra here and
    cannot drift from what the container actually holds.
    """
    return RiskDecision(
        symbol="TEST",
        approved=True,
        final_shares=0.0,
        reason="test fixture",
        inputs=inputs,
    )


def _build(qtbot, tmp_path, book_risk, audit_entries):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    runtime.book_risk_monitor = _Monitor(book_risk)
    runtime.risk_engine.audit_log._entries = list(audit_entries)
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    # Most tests here drive the refresh by calling it directly, never by
    # waiting on this screen's own 2s QTimer - so stop it. Left running, it
    # can survive past this test: __init__ subscribes a bound method on
    # runtime.bus, which is a strong reference back to this screen, forming a
    # cycle with screen.runtime that only the cyclic GC (not refcounting)
    # breaks - and the shared QApplication event loop is process-wide, so an
    # un-stopped timer can fire during a LATER, unrelated test. `_entry` now
    # builds real `RiskDecision` rows, so a stray tick would no longer crash
    # on a missing `.symbol` - but stopping the timer is what stops a LATER
    # test's assertions from racing a tick this test never asked for, which a
    # correctly-typed fixture alone does not fix.
    screen._timer.stop()
    return screen


def test_live_value_is_the_headline_and_the_decision_is_the_caption(qtbot, tmp_path):
    console = _build(
        qtbot,
        tmp_path,
        _book_risk(),
        [
            _entry(
                {
                    "portfolio_check": {
                        "var_95": 0.02,
                        "var_99": 0.03,
                        "es_975": 0.04,
                        "single_name_pct": 0.05,
                    }
                }
            )
        ],
    )

    console._refresh_risk_tiles()

    assert console.var95_tile._value.text() == "1.10%"
    assert "2.00%" in console.var95_tile._caption.text()


def test_no_decision_means_no_caption_at_all(qtbot, tmp_path):
    """The common case: the audit log is in-memory and empty at every startup."""
    console = _build(qtbot, tmp_path, _book_risk(), [])

    console._refresh_risk_tiles()

    assert console.var95_tile._value.text() == "1.10%"
    assert console.var95_tile._caption.isVisibleTo(console.var95_tile) is False


def test_no_live_measurement_shows_a_dash_not_a_zero(qtbot, tmp_path):
    console = _build(qtbot, tmp_path, None, [])

    console._refresh_risk_tiles()

    assert console.var95_tile._value.text() == "-"


def test_the_concentration_tile_is_relabelled(qtbot, tmp_path):
    """⚠️ The decision path's single_name_pct is the CANDIDATE's; the live one
    is the largest in the book. One label over two meanings invites a reader to
    treat a coincidence as agreement."""
    console = _build(qtbot, tmp_path, _book_risk(), [])

    assert "Largest single name" in console.concentration_tile._label.text()


def test_the_concentration_captions_candidate_qualifier_survives(qtbot, tmp_path):
    """ "candidate at last decision" is the wording that carries the whole
    distinction this tile was relabelled for (book_risk.py:141-144): the
    decision path's single_name_pct is the CANDIDATE's, the live figure above
    it is the largest already in the book. A plain `set_caption(_caption(...))`
    - dropping the qualifier - leaves every other test in this file green,
    because none of them read the caption text closely enough to notice."""
    console = _build(
        qtbot,
        tmp_path,
        _book_risk(),
        [_entry({"portfolio_check": {"single_name_pct": 0.05}})],
    )

    console._refresh_risk_tiles()

    assert "candidate at last decision" in console.concentration_tile._caption.text()


def test_a_partial_decision_omits_the_caption_for_the_missing_field_only(qtbot, tmp_path):
    """`portfolio_check` dicts are routinely partial - the governor's rails
    write fields in sequence and one can refuse before a later field is set
    (test_risk_metrics_sees_the_book.py exercises the identical shape for
    `sector_pct`). A field the decision did not record must leave that tile's
    caption ABSENT, never a dash: `_caption`'s `value is None` branch
    (risk_console.py:593-594) is the one line deciding that, and mutating it
    to return a dash instead of None left every test green before this one."""
    console = _build(
        qtbot,
        tmp_path,
        _book_risk(),
        [
            _entry(
                {
                    "portfolio_check": {
                        "var_95": 0.02,
                        "var_99": None,
                        "es_975": 0.04,
                        "single_name_pct": 0.05,
                    }
                }
            )
        ],
    )

    console._refresh_risk_tiles()

    assert console.var99_tile._caption.text() != "-"
    assert console.var99_tile._caption.isVisibleTo(console.var99_tile) is False
    # The rest of the decision is present and must still show through - this
    # is a MISSING field, not a wholesale absence of the decision.
    assert "2.00%" in console.var95_tile._caption.text()


def test_on_timer_tick_populates_all_four_tiles_from_the_live_book(qtbot, tmp_path):
    """`_refresh_risk_tiles` has exactly one call site: `_on_timer_tick`
    (risk_console.py:294). Nothing else pins it, and construction alone never
    populates the tiles - `KpiTile` defaults to "-" and `RiskConsoleScreen.
    __init__` never calls `_refresh_risk_tiles` itself. Delete that line in a
    future refactor and all four tiles return to "-" forever, silently, with
    every OTHER test in this file still green, because `_build`'s helper (and
    every test above) drives `_refresh_risk_tiles()` directly rather than
    through the timer's own handler.

    This test goes through `_on_timer_tick` instead - ticking the handler
    the timer is wired to, never the 2s QTimer itself - which is the one path
    that would notice the call site going missing. `_on_timer_tick` also
    drives `refresh_refusals`, `_refresh_anomalies`, `_refresh_correlation_
    table` and `refresh_binding_pairs`; `_build`'s real `Runtime.build_demo`
    runtime and real `RiskDecision` audit rows (see `_entry`) are what let
    all four run cleanly, the same fixture shape
    test_risk_console_kill_switch.py's own `_on_timer_tick` test already
    relies on.
    """
    console = _build(
        qtbot,
        tmp_path,
        _book_risk(),
        [
            _entry(
                {
                    "portfolio_check": {
                        "var_95": 0.02,
                        "var_99": 0.03,
                        "es_975": 0.04,
                        "single_name_pct": 0.05,
                    }
                }
            )
        ],
    )
    # Not populated yet - proves the assertions below exercise the tick
    # itself rather than something construction already did.
    for tile in (
        console.var95_tile,
        console.var99_tile,
        console.es_tile,
        console.concentration_tile,
    ):
        assert tile._value.text() == "-"

    console._on_timer_tick()

    assert console.var95_tile._value.text() == "1.10%"
    assert console.var99_tile._value.text() == "1.50%"
    assert "1.70%" in console.es_tile._value.text()
    assert console.concentration_tile._value.text() == "12.00%"
