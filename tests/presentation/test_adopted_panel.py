"""The adopted-positions panel appears only when it has something to say."""

from __future__ import annotations

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.oms.adopted import assess_adopted_positions
from qat.presentation.adopted_panel import AdoptedPositionsPanel


def _report(stops: dict[str, float] | None = None, quantity: float = 100):
    return assess_adopted_positions(
        adopted_baseline={"A": quantity},
        positions=[Position(symbol="A", quantity=quantity, avg_price=100.0)],
        stops=stops or {},
        equity=100_000.0,
        settings=Settings(_env_file=None, max_aggregate_risk_at_stop_pct=0.05),
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
    assert "no record of a protective stop" in panel.body.text()


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
