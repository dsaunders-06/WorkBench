"""The adopted-positions panel appears only when it has something to say."""

from __future__ import annotations

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.oms.adopted import assess_adopted_positions
from qat.presentation.adopted_panel import AdoptedPositionsPanel


def _report(
    stops: dict[str, float] | None = None,
    quantity: float = 100,
    opened_by_this_app: set[str] | None = None,
):
    return assess_adopted_positions(
        adopted_baseline={"A": quantity},
        positions=[Position(symbol="A", quantity=quantity, avg_price=100.0)],
        stops=stops or {},
        equity=100_000.0,
        settings=Settings(_env_file=None, max_aggregate_risk_at_stop_pct=0.05),
        opened_by_this_app=opened_by_this_app,
    )


def test_panel_is_hidden_when_nothing_was_adopted(qtbot):
    """A panel that is always there and usually empty stops being read."""
    panel = AdoptedPositionsPanel()
    qtbot.addWidget(panel)

    panel.update_from(None)

    assert not panel.isVisibleTo(panel.parentWidget() or panel)


def test_panel_names_the_blocked_state(qtbot):
    panel = AdoptedPositionsPanel()
    qtbot.addWidget(panel)

    panel.update_from(_report())

    assert panel.isVisibleTo(panel)
    assert "refused" in panel.headline.text()
    assert "10.00%" in panel.headline.text()  # $10,000 of a $100,000 account
    assert "5.00% cap" in panel.headline.text()
    # Names the position that is actually naked, rather than describing every
    # adopted holding that way as it did before stops were read at adoption.
    assert "No stop is resting for A " in panel.body.text()


def test_panel_stays_quieter_when_the_cap_is_not_breached(qtbot):
    """Amber for "deal with this", red for "nothing new is opening"."""
    panel = AdoptedPositionsPanel()
    qtbot.addWidget(panel)

    panel.update_from(_report(quantity=10))
    quiet_style = panel.headline.styleSheet()

    panel.update_from(_report())
    loud_style = panel.headline.styleSheet()

    assert quiet_style != loud_style
    assert "refused" not in _report(quantity=10).headline()


def test_panel_disappears_once_the_positions_are_dealt_with(qtbot):
    """The warning must not outlive the condition."""
    panel = AdoptedPositionsPanel()
    qtbot.addWidget(panel)
    panel.update_from(_report())
    assert panel.isVisibleTo(panel)

    panel.update_from(
        assess_adopted_positions(
            adopted_baseline={"A": 100.0},
            positions=[],
            stops={},
            equity=100_000.0,
            settings=Settings(_env_file=None),
        )
    )

    assert not panel.isVisibleTo(panel.parentWidget() or panel)


# --- A restart is not a surprise (M33e) ---------------------------------------


def test_the_banner_says_resumed_when_this_app_opened_them(qtbot):
    """It read "6 positions not opened by this app ... this application did not
    choose them" for six positions swing had opened the day before. The banner
    is styled as a warning, so firing it on every restart for the app's own
    positions is how an operator learns to ignore the case it exists for."""
    panel = AdoptedPositionsPanel()
    qtbot.addWidget(panel)

    panel.update_from(_report(stops={"A": 95.0}, opened_by_this_app={"A"}))

    assert "resumed after restart" in panel.headline.text()
    assert "not opened by this app" not in panel.headline.text()
    assert "did not choose them" not in panel.body.text()


def test_a_genuinely_foreign_holding_still_reads_as_one(qtbot):
    """The case the banner exists for, unchanged."""
    panel = AdoptedPositionsPanel()
    qtbot.addWidget(panel)

    panel.update_from(_report(stops={"A": 95.0}, opened_by_this_app=set()))

    assert "not opened by this app" in panel.headline.text()
    assert "did not choose them" in panel.body.text()


def test_a_mixed_book_names_both(qtbot):
    report = assess_adopted_positions(
        adopted_baseline={"A": 100, "B": 100},
        positions=[
            Position(symbol="A", quantity=100, avg_price=100.0),
            Position(symbol="B", quantity=100, avg_price=100.0),
        ],
        stops={"A": 95.0, "B": 95.0},
        equity=100_000.0,
        settings=Settings(_env_file=None, max_aggregate_risk_at_stop_pct=0.05),
        opened_by_this_app={"A"},
    )

    assert "1 position not opened by this app" in report.headline()
    assert "1 resumed after restart" in report.headline()
