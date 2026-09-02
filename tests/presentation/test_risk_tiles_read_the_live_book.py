"""The VaR tiles have shown "-" since 31 August, and nothing was broken.

They read `audit_log.entries()[-1].inputs["portfolio_check"]` and returned early
when it was absent - which is every startup, because the audit log is in-memory,
and every 10-of-10 day, because the governor refuses one rail before that dict is
written. They now read the book actually held, with the last decision's figure as
a caption BENEATH, and only when there is one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from qat.config import Settings
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


def _entry(inputs: dict) -> SimpleNamespace:
    return SimpleNamespace(inputs=inputs)


def _build(qtbot, tmp_path, book_risk, audit_entries):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    runtime.book_risk_monitor = _Monitor(book_risk)
    runtime.risk_engine.audit_log._entries = list(audit_entries)
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
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
