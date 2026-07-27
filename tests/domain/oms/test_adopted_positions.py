"""Adopted positions must explain themselves (spec M25).

The condition these tests describe actually happened: seven positions adopted
from a paper account put aggregate risk-at-stop at 30% against a 5% cap, every
new entry was refused for the whole session, and nothing anywhere said why.
The blocking was correct. The silence was the defect.
"""

from __future__ import annotations

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.oms.adopted import assess_adopted_positions
from qat.domain.risk_engine.governor import PortfolioGovernor


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_no_adopted_positions_is_no_report() -> None:
    """The normal case says nothing at all.

    An empty report rather than None would push the "is this worth showing?"
    decision onto every caller, and a panel that renders when there is nothing
    to say is one the operator learns to ignore.
    """
    assert (
        assess_adopted_positions(
            adopted_baseline={},
            positions=[Position(symbol="AAPL", quantity=10, avg_price=100.0)],
            stops={},
            equity=100_000.0,
            settings=_settings(),
        )
        is None
    )


def test_unstopped_adopted_positions_count_at_full_value() -> None:
    """The arithmetic that produced 30% against a 5% cap."""
    positions = [Position(symbol=sym, quantity=100, avg_price=100.0) for sym in ("A", "B", "C")]
    report = assess_adopted_positions(
        adopted_baseline={"A": 100.0, "B": 100.0, "C": 100.0},
        positions=positions,
        stops={},
        equity=100_000.0,
        settings=_settings(max_aggregate_risk_at_stop_pct=0.05),
    )

    assert report is not None
    assert report.count == 3
    assert len(report.unprotected) == 3
    # Three positions at $10,000 each, none protected, all of it at risk.
    assert report.adopted_risk_dollars == 30_000.0
    assert report.adopted_risk_pct == 0.30
    assert report.blocking
    assert "new entries are being refused" in report.headline()
    assert "close them" in report.explanation()


def test_the_reported_figure_is_the_one_that_blocks() -> None:
    """Reuse, not reimplementation.

    If this module computed risk-at-stop its own way, the panel and the
    governor could drift and the operator would be reading an explanation of a
    decision that was made on different numbers.
    """
    settings = _settings(max_aggregate_risk_at_stop_pct=0.05)
    positions = [Position(symbol="A", quantity=100, avg_price=100.0)]
    report = assess_adopted_positions(
        adopted_baseline={"A": 100.0},
        positions=positions,
        stops={},
        equity=100_000.0,
        settings=settings,
    )
    governor_view = PortfolioGovernor(settings).snapshot(
        positions=positions, stops={}, equity=100_000.0
    )

    assert report is not None
    assert report.risk_at_stop_dollars == governor_view.risk_at_stop_dollars
    assert report.risk_at_stop_pct == governor_view.risk_at_stop_pct


def test_a_stop_reduces_the_counted_risk_to_the_distance_down_to_it() -> None:
    """One of the two ways out the explanation offers, and it works."""
    report = assess_adopted_positions(
        adopted_baseline={"A": 100.0},
        positions=[Position(symbol="A", quantity=100, avg_price=100.0)],
        stops={"A": 90.0},
        equity=100_000.0,
        settings=_settings(max_aggregate_risk_at_stop_pct=0.05),
    )

    assert report is not None
    assert report.unprotected == ()
    assert report.adopted_risk_dollars == 1_000.0  # $10 of risk per share, not $100
    assert not report.blocking
    assert "budget" in report.headline()


def test_closing_an_adopted_position_removes_it_from_the_report() -> None:
    """The other way out.

    The baseline is a record of what was held at startup and is never
    rewritten, so without checking live positions the warning would outlive the
    condition and go on blaming holdings that had already been sold.
    """
    report = assess_adopted_positions(
        adopted_baseline={"A": 100.0, "B": 100.0},
        positions=[Position(symbol="B", quantity=100, avg_price=100.0)],
        stops={},
        equity=100_000.0,
        settings=_settings(),
    )

    assert report is not None
    assert [p.symbol for p in report.positions] == ["B"]

    all_closed = assess_adopted_positions(
        adopted_baseline={"A": 100.0, "B": 100.0},
        positions=[],
        stops={},
        equity=100_000.0,
        settings=_settings(),
    )
    assert all_closed is None


def test_positions_opened_by_this_app_are_not_counted_as_adopted() -> None:
    """The warning names what the app did not choose, not the whole book."""
    report = assess_adopted_positions(
        adopted_baseline={"OLD": 100.0},
        positions=[
            Position(symbol="OLD", quantity=100, avg_price=100.0),
            Position(symbol="NEW", quantity=100, avg_price=100.0),
        ],
        stops={"NEW": 95.0},
        equity=100_000.0,
        settings=_settings(max_aggregate_risk_at_stop_pct=0.05),
    )

    assert report is not None
    assert [p.symbol for p in report.positions] == ["OLD"]
    # The adopted share is its own $10,000; the total also carries NEW's $500.
    assert report.adopted_risk_dollars == 10_000.0
    assert report.risk_at_stop_dollars == 10_500.0


def test_a_live_price_is_preferred_to_the_average_entry_price() -> None:
    """Risk is what the position is worth now, not what it cost."""
    report = assess_adopted_positions(
        adopted_baseline={"A": 100.0},
        positions=[Position(symbol="A", quantity=100, avg_price=100.0)],
        stops={},
        equity=100_000.0,
        settings=_settings(),
        prices={"A": 150.0},
    )

    assert report is not None
    assert report.positions[0].value == 15_000.0
    assert report.adopted_risk_dollars == 15_000.0


def test_blocking_means_the_cap_is_breached_not_merely_approached() -> None:
    """An alarm that fires before anything is blocked gets scrolled past."""
    under = assess_adopted_positions(
        adopted_baseline={"A": 10.0},
        positions=[Position(symbol="A", quantity=10, avg_price=100.0)],
        stops={},
        equity=100_000.0,
        settings=_settings(max_aggregate_risk_at_stop_pct=0.05),
    )
    assert under is not None
    assert under.adopted_risk_pct == 0.01
    assert not under.blocking
    assert "refused" not in under.headline()
