"""The Blotter says WHY, and answers to the level (M77).

The last screen in Group 4, and the most safety-critical.

**§4.2 protects a reason text the screen never displayed.** *"Do not touch: …
the reason text on a rejection"* and *"Enhance: rejection reasons are written
for an engineer reading a log"* both presume a reason is on this screen. It was
not: the eleven columns had no reason field, `Order` carries no reason
attribute, and `OMS._record` writes it to the decision journal instead. So the
Blotter listed rejected orders - `_new_rejected_order` creates real ones - and
could not say why any of them was rejected. The sixth time §4.x has been wrong
in detail.

**The plain-language layer already existed and this screen did not read it.**
`refusals.rail_of` turns §4.2's own example - "sized at 0.4 shares, below one
whole share …" - into "Sized below one whole share", and has done since M51. Its
consumers were the reporter and the Risk Console; never the screen where an
operator meets a refused order. That is the sixth instance of the
`shows_advanced()` pattern.

**What must not move.** M45 puts the sign-off gate and the mode banner outside
the level model entirely, so both are asserted identical at all three levels.
Guided is allowed to be STRICTER - one order at a time - and nothing is allowed
to be looser.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QAbstractItemView, QLabel

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain.decision_journal import JournalEntry
from qat.presentation import theme
from qat.presentation.blotter import BlotterScreen
from qat.presentation.runtime import Runtime

_SIZING_REFUSAL = (
    "sized at 0.4 shares, below one whole share - a fractional quantity cannot "
    "carry a protective bracket"
)


def _screen(qtbot, level: str = "standard", tmp_path=None) -> BlotterScreen:
    settings = Settings(_env_file=None, ui_level=level, data_dir=str(tmp_path))
    runtime = Runtime.build_demo(settings=settings)
    screen = BlotterScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def _journal(screen: BlotterScreen, order_id: str, reason: str) -> None:
    screen.runtime.decision_journal.record(
        JournalEntry(
            order_id=order_id,
            symbol="AMD",
            side="buy",
            outcome="rejected",
            reason=reason,
            quantity=0.0,
            price=100.0,
            strategy="swing",
        )
    )


def _order(order_id: str = "o-1", status: str = "rejected") -> Order:
    return Order(symbol="AMD", side="buy", quantity=0.0, order_id=order_id, status=status)


def _column(screen: BlotterScreen, header: str) -> int:
    """Resolved from the header, never hardcoded - a new column shifting the
    index is exactly what silently broke the Screener's tests before."""
    table = screen.orders_table
    for index in range(table.columnCount()):
        if table.horizontalHeaderItem(index).text() == header:
            return index
    raise AssertionError(f"No {header!r} column on the blotter")


def _cell(screen: BlotterScreen, header: str, row: int = 0) -> str:
    item = screen.orders_table.item(row, _column(screen, header))
    return item.text() if item else ""


def _show(screen: BlotterScreen, order: Order, reason: str) -> None:
    """Put one order on screen with a journalled reason, as the app would."""
    screen.runtime.oms._orders[order.order_id] = order
    _journal(screen, order.order_id, reason)
    screen.status_filter.setCurrentText("All")
    screen._reasons_read_at = 0.0
    screen._rendered_signature = None
    screen._timer_refresh()


# --- the reason ---------------------------------------------------------------


def test_a_rejected_order_says_why(qtbot, tmp_path):
    """The defect. The screen listed rejections and explained none of them."""
    screen = _screen(qtbot, "standard", tmp_path)

    _show(screen, _order(), _SIZING_REFUSAL)

    assert _cell(screen, "Reason") == "Sized below one whole share"


def test_the_exact_figures_are_one_hover_away(qtbot, tmp_path):
    """§4.2: "same fact, layered: plain sentence first, exact figures beneath".
    Layering must hide nothing - the rail's own words, with every number it
    mentioned, stay reachable."""
    screen = _screen(qtbot, "standard", tmp_path)

    _show(screen, _order(), _SIZING_REFUSAL)

    item = screen.orders_table.item(0, _column(screen, "Reason"))
    assert item.toolTip() == _SIZING_REFUSAL


def test_an_order_with_no_journalled_reason_shows_a_dash(qtbot, tmp_path):
    """Absent is absent. A blank cell and "we have no reason" must not be the
    same thing on the screen that gates transmission."""
    screen = _screen(qtbot, "standard", tmp_path)
    screen.runtime.oms._orders["o-2"] = _order("o-2")
    screen.status_filter.setCurrentText("All")
    screen._timer_refresh()

    assert _cell(screen, "Reason") == "-"


def test_a_pending_order_also_shows_its_reason(qtbot, tmp_path):
    """The journal records why an order was PROPOSED too, and that is exactly
    the "order detail that supports the decision" §4.2 says to protect - it
    helps the sign-off judgement, not only the post-mortem."""
    screen = _screen(qtbot, "standard", tmp_path)

    _show(screen, _order("o-3", status="pending_signoff"), "proposed by swing")

    assert _cell(screen, "Reason") == "proposed by swing"


@pytest.mark.parametrize("level", ["guided", "standard", "professional"])
def test_a_proposal_is_not_run_through_the_refusal_vocabulary(qtbot, tmp_path, level):
    """Rendering it found "proposed by swing - not recognised - see the note
    below" at Guided. `classify` returns UNCLASSIFIED for anything that is not
    a refusal, and that sentence belongs to the refusal REPORT, where a note
    does follow. Here it called a healthy proposal unrecognised."""
    screen = _screen(qtbot, level, tmp_path / level)

    _show(screen, _order("o-4", status="pending_signoff"), "proposed by swing")

    assert _cell(screen, "Reason") == "proposed by swing"


def test_an_unclassified_refusal_is_not_labelled_unrecognised(qtbot, tmp_path):
    """The same trap by the other route: a rail added later, refusing for a
    reason the patterns do not yet match, must not tell a Guided operator its
    own refusal was "not recognised"."""
    screen = _screen(qtbot, "guided", tmp_path)

    _show(screen, _order("o-5"), "some rail nobody has classified yet")

    assert "not recognised" not in _cell(screen, "Reason")


# --- layered by level ---------------------------------------------------------


def test_guided_is_told_what_the_family_means(qtbot, tmp_path):
    """ "Position limit" still assumes you know the book has one."""
    screen = _screen(qtbot, "guided", tmp_path)

    _show(screen, _order(), _SIZING_REFUSAL)

    text = _cell(screen, "Reason")
    assert text.startswith("Sized below one whole share")
    assert "says something about the strategy" in text


def test_standard_gets_the_label_alone(qtbot, tmp_path):
    screen = _screen(qtbot, "standard", tmp_path)

    _show(screen, _order(), _SIZING_REFUSAL)

    assert _cell(screen, "Reason") == "Sized below one whole share"


def test_professional_reads_the_rails_own_words(qtbot, tmp_path):
    """A label is a summary, and this is the level that chooses to do without
    one."""
    screen = _screen(qtbot, "professional", tmp_path)

    _show(screen, _order(), _SIZING_REFUSAL)

    assert _cell(screen, "Reason") == _SIZING_REFUSAL


def test_the_three_levels_do_not_render_the_reason_identically(qtbot, tmp_path):
    """M58a in miniature."""
    texts = set()
    for level in ("guided", "standard", "professional"):
        screen = _screen(qtbot, level, tmp_path / level)
        _show(screen, _order(), _SIZING_REFUSAL)
        texts.add(_cell(screen, "Reason"))

    assert len(texts) == 3


# --- what the level may NOT change --------------------------------------------


def test_guided_approves_one_order_at_a_time(qtbot, tmp_path):
    """§4.2. Enforced in the selection model, so a batch cannot be formed at
    all - stricter, never looser."""
    screen = _screen(qtbot, "guided", tmp_path)

    assert screen.orders_table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert not screen.select_all_button.isVisibleTo(screen)


@pytest.mark.parametrize("level", ["standard", "professional"])
def test_bulk_sign_off_is_standard_and_above(qtbot, tmp_path, level):
    screen = _screen(qtbot, level, tmp_path / level)

    assert screen.orders_table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    assert screen.select_all_button.isVisibleTo(screen)


@pytest.mark.parametrize("level", ["guided", "standard", "professional"])
def test_the_sign_off_gate_is_identical_at_every_level(qtbot, tmp_path, level):
    """M45: safety is not a level. Sign-off and reject stay distinct, both
    start disabled, and neither may be reached without the confirm dialog."""
    screen = _screen(qtbot, level, tmp_path / level)

    assert screen.sign_off_button.isVisibleTo(screen)
    assert screen.reject_button.isVisibleTo(screen)
    assert screen.sign_off_button.isEnabled() is False
    assert screen.reject_button.isEnabled() is False


@pytest.mark.parametrize("level", ["guided", "standard", "professional"])
def test_signing_off_still_requires_confirmation_at_every_level(qtbot, tmp_path, level):
    """The invariant the whole screen exists for. Declining the dialog must
    reach oms.sign_off zero times, at every level."""
    screen = _screen(qtbot, level, tmp_path / level)
    order = _order("o-9", status="pending_signoff")
    _show(screen, order, "proposed")
    screen.orders_table.selectAll()
    reached: list[str] = []
    screen.runtime.oms.sign_off = lambda *a, **k: reached.append(a[0])  # type: ignore[assignment]
    screen._confirm = lambda _message: False  # type: ignore[assignment]

    screen._on_sign_off_clicked()

    assert reached == []


# --- the mode banner ----------------------------------------------------------


def _mode_banner(screen: BlotterScreen) -> QLabel:
    for child in screen.findChildren(QLabel):
        if child.text().startswith("MODE:"):
            return child
    raise AssertionError("No mode banner on the blotter")


def test_the_mode_banner_uses_the_design_system(qtbot, tmp_path):
    """Two of M75's 25 raw-hex sites, and theme.banner names this exact use -
    "the mode and execution banners, which state the two facts that change what
    every other number on screen means"."""
    screen = _screen(qtbot, "standard", tmp_path)

    assert _mode_banner(screen).styleSheet() == theme.banner(theme.SUCCESS)


@pytest.mark.parametrize("level", ["guided", "standard", "professional"])
def test_the_mode_banner_is_identical_at_every_level(qtbot, tmp_path, level):
    """M45 puts the mode banner in the same class as the sign-off gate: it
    states which account this is, and no level may soften that."""
    screen = _screen(qtbot, level, tmp_path / level)
    banner = _mode_banner(screen)

    assert banner.isVisibleTo(screen)
    assert banner.text() == "MODE: PAPER"
    assert banner.styleSheet() == theme.banner(theme.SUCCESS)


# --- the journal is not re-read on every tick ---------------------------------


def test_the_journal_is_not_re_read_when_everything_is_explained(qtbot, tmp_path):
    """`entries()` re-parses a 464KB CSV and this screen refreshes every two
    seconds."""
    screen = _screen(qtbot, "standard", tmp_path)
    _show(screen, _order(), _SIZING_REFUSAL)
    reads: list[int] = []
    original = screen.runtime.decision_journal.entries
    screen.runtime.decision_journal.entries = lambda *a, **k: (  # type: ignore[assignment]
        reads.append(1),
        original(*a, **k),
    )[1]

    screen._timer_refresh()
    screen._timer_refresh()

    assert reads == []
