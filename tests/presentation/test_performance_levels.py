"""Performance answers to the level, and says what it cannot answer (M79).

The last Group 4 screen, and the one the trial's answer will eventually be read
from. It consumed no level at all.

**Sequenced against the plan's own reasoning.** The handoff said Performance
waits for September. §5 step 5 says the opposite - *"Where the trial's answer
will eventually be read. Worth being good before there is something to read"* -
and §7 warns against the interface changing "underneath the reading". September
is when the reading starts, so September is exactly when not to build it.

**The M37 diagnostic columns §4.4 lists for Professional did not exist.**
`_TRADE_COLUMNS` ran Closed → R with no regime-at-entry, exit reason, MAE/MFE or
slippage, though `ClosedTrade` has computed all five since M37.

**Guided got a verdict in words.** The promotion table reports one of four
statuses beside a semicolon-joined blocking list - precise, and it assumes the
reader knows there is a bar, what it is, and that failing it this early is
normal rather than damning.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.domain.performance.trades import ClosedTrade
from qat.presentation.performance import (
    NOT_AVAILABLE,
    PerformanceScreen,
    _diagnostics,
)
from qat.presentation.runtime import Runtime


def _screen(qtbot, level: str, tmp_path) -> PerformanceScreen:
    settings = Settings(_env_file=None, ui_level=level, data_dir=str(tmp_path))
    screen = PerformanceScreen(Runtime.build_demo(settings=settings))
    qtbot.addWidget(screen)
    return screen


def _trade(**kwargs) -> ClosedTrade:
    base = dict(
        symbol="AMD",
        strategy="swing",
        quantity=7.0,
        entry_price=510.267,
        exit_price=540.0,
        stop_price=405.55,
        opened_at=datetime(2026, 8, 4, tzinfo=UTC),
        closed_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    base.update(kwargs)
    return ClosedTrade(**base)  # type: ignore[arg-type]


# --- three levels, three outcomes ---------------------------------------------


def test_guided_gets_verdicts_and_not_the_table(qtbot, tmp_path):
    screen = _screen(qtbot, "guided", tmp_path)

    assert screen.verdicts.isVisibleTo(screen)
    assert not screen.promotion_table.isVisibleTo(screen)
    assert not screen.tabs.isVisibleTo(screen)


def test_standard_gets_the_table_and_the_tabs(qtbot, tmp_path):
    screen = _screen(qtbot, "standard", tmp_path)

    assert not screen.verdicts.isVisibleTo(screen)
    assert screen.promotion_table.isVisibleTo(screen)
    assert screen.tabs.isVisibleTo(screen)


def test_only_professional_gets_the_diagnostic_columns(qtbot, tmp_path):
    """§4.4: "for analysis, not monitoring. Professional only"."""
    standard = _screen(qtbot, "standard", tmp_path / "s")
    professional = _screen(qtbot, "professional", tmp_path / "p")

    assert "Regime at entry" not in standard.trade_columns
    assert "Regime at entry" in professional.trade_columns
    assert "Slippage" in professional.trade_columns


def test_only_professional_can_sort_the_trades(qtbot, tmp_path):
    """Sorting is what makes "which regime did the losers happen in"
    answerable, and that is an analysis question."""
    standard = _screen(qtbot, "standard", tmp_path / "s")
    professional = _screen(qtbot, "professional", tmp_path / "p")

    assert standard.trades_table.isSortingEnabled() is False
    assert professional.trades_table.isSortingEnabled() is True


def test_the_three_levels_do_not_render_identically(qtbot, tmp_path):
    """M58a in miniature."""
    shapes = set()
    for level in ("guided", "standard", "professional"):
        screen = _screen(qtbot, level, tmp_path / level)
        shapes.add(
            (
                screen.verdicts.isVisibleTo(screen),
                screen.promotion_table.isVisibleTo(screen),
                len(screen.trade_columns),
            )
        )

    assert len(shapes) == 3


@pytest.mark.parametrize("level", ["guided", "standard", "professional"])
def test_the_headline_is_present_at_every_level(qtbot, tmp_path, level):
    """The one line that says whether the account made money. That is not a
    matter of expertise."""
    screen = _screen(qtbot, level, tmp_path / level)

    assert screen.headline.isVisibleTo(screen)


# --- the diagnostics ----------------------------------------------------------


def test_the_diagnostics_report_what_was_recorded():
    row = _diagnostics(
        _trade(
            regime_at_entry="bull",
            exit_reason="stop",
            reference_price=503.16,
            worst_price=480.0,
            best_price=560.0,
        )
    )

    assert row[0] == "bull"
    assert row[1] == "stop"
    assert row[4] == "+7.1070"  # 510.267 - 503.16


def test_an_unrecorded_diagnostic_is_an_em_dash_not_a_zero():
    """A trade predating the milestone that started recording it has no value,
    and zero is a measurement - the rule the Screener and the prompt both
    follow."""
    row = _diagnostics(_trade())

    assert row == (
        NOT_AVAILABLE,
        NOT_AVAILABLE,
        NOT_AVAILABLE,
        NOT_AVAILABLE,
        NOT_AVAILABLE,
    )


def test_slippage_of_exactly_zero_is_shown_rather_than_hidden():
    """It is the M70 fingerprint: until then a lot's price and its reference
    came from the same announcement, so this read zero by construction. Showing
    it is what makes the defect visible in the record it corrupted."""
    row = _diagnostics(_trade(entry_price=503.16, reference_price=503.16))

    assert row[4] == "+0.0000"


# --- the Guided verdict -------------------------------------------------------


def test_a_strategy_with_no_trades_is_not_judged(qtbot, tmp_path):
    """ "Not eligible" reads as a verdict on the strategy; at this stage it is a
    verdict on the sample."""
    screen = _screen(qtbot, "guided", tmp_path)
    screen.refresh()

    text = screen.verdicts.text()
    assert "nothing to judge it on" in text or "No strategy has produced" in text


def test_the_verdict_names_what_is_blocking(qtbot, tmp_path):
    """§4.4's Guided column asks for the verdict "plus what is blocking it"."""
    from qat.domain.performance.scorecard import build_all_scorecards
    from qat.presentation.performance import _verdict

    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    cards = build_all_scorecards({"swing": [_trade()]}, settings)

    verdict = _verdict(cards[0])

    assert "swing" in verdict
    assert "Waiting on:" in verdict or "clears the bar" in verdict
