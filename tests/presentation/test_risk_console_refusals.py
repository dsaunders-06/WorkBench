"""The screen called "why was I refused" must answer that question.

It showed four VaR tiles, a correlation matrix, the kill-switch and quarantined
positions - and nothing at all about refusals. M64 then made the Regime Monitor
point here: when the regime permits a strategy and nothing still trades, that
screen says "the reason is a risk rail - see the Risk Console". A forward
reference to a screen that cannot answer is the M58a pattern, a promise the
application does not keep.

The numbers come from `summarise_refusals`, the same function the daily report
uses, so the screen and the report cannot disagree about the same night.

**Safety is not a level.** UI_UX_APPROACH 4.7 puts kill-switch control at
Professional and hides this screen at Guided; `ui_level.py` says warnings,
refusal reasons and the sign-off gate are identical at every level. The doctrine
wins, and these tests pin it.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qat.config import Settings
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel

_COLUMNS = ["timestamp", "symbol", "approved", "reason", "shares", "inputs"]
_TODAY = datetime.now(UTC).date().isoformat()
_YESTERDAY = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()


def _write_decisions(tmp_path: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows are (symbol, approved, reason), written in the real column shape."""
    path = tmp_path / "risk_decisions.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for symbol, approved, reason in rows:
            writer.writerow(
                {
                    "timestamp": f"{_TODAY}T14:00:00+00:00",
                    "symbol": symbol,
                    "approved": approved,
                    "reason": reason,
                    "shares": "0",
                    "inputs": "{}",
                }
            )


def _busy_night(tmp_path: Path) -> None:
    """A night shaped like the real record: mostly capacity, some cost rail."""
    rows = [("AAPL", "True", "approved")]
    rows += [("MSFT", "False", "already at the 10-position limit")] * 6
    rows += [("NVDA", "False", "Round-trip cost $18.24 is 13.2% of the $138.38 at risk")] * 3
    _write_decisions(tmp_path, rows)


def _screen(qtbot, tmp_path, level: UiLevel) -> RiskConsoleScreen:
    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, data_dir=str(tmp_path), ui_level=level.label.lower())
    )
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    screen.show()
    screen.refresh_refusals()
    return screen


# --- Safety is not a level ----------------------------------------------------


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_the_kill_switch_is_reachable_at_every_level(qtbot, tmp_path, level):
    """4.7 puts kill-switch control at Professional only. Overruled: it is the
    most safety-critical control in the application, and a Guided operator who
    cannot halt trading is the worst outcome this document could produce."""
    screen = _screen(qtbot, tmp_path, level)

    assert screen.kill_switch_button.isVisible() is True
    assert screen.kill_switch_button.isEnabled() is True


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_a_reason_is_available_at_every_level(qtbot, tmp_path, level):
    """`ui_level` names refusal reasons as content that does not vary. Only the
    DEPTH changes."""
    _busy_night(tmp_path)
    screen = _screen(qtbot, tmp_path, level)

    assert screen.refusal_headline.isVisible() is True
    assert screen.refusal_headline.text().strip() != ""


# --- It answers the question, with the report's own numbers -------------------


def test_the_headline_is_the_one_the_report_would_print(qtbot, tmp_path):
    """Reuse, not reimplementation. If the screen counted rows itself, it and
    the daily report could describe the same night differently - and the
    operator would have no way to know which was lying."""
    from qat.domain.evaluation.refusals import load_risk_decisions, summarise_refusals

    _busy_night(tmp_path)
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    expected = summarise_refusals(load_risk_decisions(tmp_path))
    assert screen.refusal_headline.text() == expected.headline()


def test_the_families_are_shown_with_their_counts(qtbot, tmp_path):
    """Capacity against candidate is the split that decides what to do:
    capacity says change the limits, candidate says look at the strategy."""
    _busy_night(tmp_path)
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    detail = screen.refusal_detail.toPlainText()
    assert "capacity" in detail.lower()
    assert "6" in detail


def test_a_quiet_night_says_so_rather_than_going_blank(qtbot, tmp_path):
    _write_decisions(tmp_path, [])
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    assert screen.refusal_headline.text().strip() != ""


def test_no_file_means_no_data_not_no_refusals(qtbot, tmp_path):
    """A figure that was not recorded is a different claim from a figure that
    was zero - the same rule the Balances panel applies to a dash."""
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    text = screen.refusal_headline.text().lower()
    assert "no sizing decisions recorded" in text or "no data" in text


# --- Three levels, three depths -----------------------------------------------


def test_guided_gets_the_sentence_and_nothing_below_it(qtbot, tmp_path):
    _busy_night(tmp_path)
    screen = _screen(qtbot, tmp_path, UiLevel.GUIDED)

    assert screen.refusal_headline.isVisible() is True
    assert screen.refusal_detail.isVisible() is False
    assert screen.audit_log.isVisible() is False


def test_standard_adds_the_families(qtbot, tmp_path):
    _busy_night(tmp_path)
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    assert screen.refusal_detail.isVisible() is True
    assert screen.audit_log.isVisible() is False


def test_professional_adds_the_audit_log(qtbot, tmp_path):
    _busy_night(tmp_path)
    screen = _screen(qtbot, tmp_path, UiLevel.PROFESSIONAL)

    assert screen.refusal_detail.isVisible() is True
    assert screen.audit_log.isVisible() is True


def test_yesterdays_refusals_are_not_reported_as_tonights(qtbot, tmp_path):
    """M56b, which this panel reintroduced in its first draft.

    That defect was lifetime totals under a daily heading - the 6 August report
    claimed a kill-switch that had fired on the 4th. Unbounded, this panel reads
    "2,629 candidates considered" from the real record while meaning "since the
    file was created", and an operator would take it for tonight.
    """
    path = tmp_path / "risk_decisions.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for day, symbol in ((_YESTERDAY, "OLD"), (_TODAY, "NEW")):
            writer.writerow(
                {
                    "timestamp": f"{day}T14:00:00+00:00",
                    "symbol": symbol,
                    "approved": "False",
                    "reason": "already at the 10-position limit",
                    "shares": "0",
                    "inputs": "{}",
                }
            )

    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    # One candidate today, not two. The heading says "today" and the figure
    # must agree with it.
    assert "1 candidate(s) considered" in screen.refusal_headline.text()


# --- Binding correlation pairs, from the rail rather than the screen ----------


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_binding_pairs_are_stated_at_every_level(qtbot, tmp_path, level):
    """A constraint on what may be traded. The matrix is the detail; this is
    the fact."""
    screen = _screen(qtbot, tmp_path, level)

    assert screen.binding_pairs_label.isVisible() is True
    assert screen.binding_pairs_label.text().strip() != ""


def test_the_matrix_is_detail_and_the_pairs_are_not(qtbot, tmp_path):
    """Guided gets the binding fact without the N x N table it cannot read."""
    guided = _screen(qtbot, tmp_path, UiLevel.GUIDED)
    standard = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    assert guided.correlation_table.isVisible() is False
    assert standard.correlation_table.isVisible() is True
    assert guided.binding_pairs_label.isVisible() is True


def test_the_pairs_come_from_the_governor_not_from_this_screen(qtbot, tmp_path):
    """Reuse, pinned. The screen's own intraday matrix would say something
    different; what must appear is the rail's answer, because that is the one
    that refuses the trade.

    This is the test that fails if someone later 'simplifies' the panel by
    correlating `_price_history` instead.
    """
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)
    screen.runtime.risk_engine.governor.binding_pairs = (  # type: ignore[method-assign]
        lambda returns, positions=None: [("AMAT", "AMD", 0.79)]
    )
    screen.runtime.signal_bridge._entries["AMAT"] = object()  # type: ignore[assignment]
    screen.runtime.signal_bridge._entries["AMD"] = object()  # type: ignore[assignment]

    screen.refresh_binding_pairs()

    text = screen.binding_pairs_label.text()
    assert "AMAT/AMD" in text
    assert "0.79" in text


def test_nothing_held_says_so_rather_than_claiming_no_correlation(qtbot, tmp_path):
    """ "Nothing held" and "held things that do not correlate" are different
    states of the world, and only one of them is reassuring."""
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    screen.refresh_binding_pairs()

    assert "nothing held" in screen.binding_pairs_label.text().lower()


def test_guided_and_standard_are_not_the_same_screen(qtbot, tmp_path):
    """The defect the Balances design reached review with, pinned again."""
    _busy_night(tmp_path)
    guided = _screen(qtbot, tmp_path, UiLevel.GUIDED)
    standard = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    assert guided.refusal_detail.isVisible() != standard.refusal_detail.isVisible()
