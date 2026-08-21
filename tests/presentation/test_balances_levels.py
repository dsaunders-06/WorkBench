"""The Balances panel consumes the expertise level, in three distinct ways.

The panel showed eleven cells in one flat grid. Measured against the live
account, ten of them carry a figure - so the brief's diagnosis, "most of them
dashes", was wrong. The real problem is INAPPLICABLE data at equal weight:
broker buying power reads $336,486 against $44,771 spendable, and margin is
reported in full on an account whose buys can never exceed cash. The panel's own
docstring already called that gap the single most confusing thing about running
the two side by side, and it was explained only by a tooltip.

**Three settings must produce three outcomes.** The first draft of this design
gave Guided and Standard identical screens, because `explains()` is true for
both - the M58a failure in miniature, where an operator chooses a level and
nothing changes. These tests exist mostly to stop that coming back.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.data.broker.account_poller import AccountSnapshot
from qat.data.broker.adapter import AccountBalances
from qat.presentation.balances_panel import BalancesPanel
from qat.presentation.ui_level import UiLevel


def _balances(**overrides) -> AccountBalances:
    values = {
        "cash": 44_772.43,
        "buying_power": 336_485.98,
        "equity": 101_244.97,
        "last_equity": 100_699.39,
        "long_market_value": 56_472.54,
        "short_market_value": 0.0,
        "initial_margin": 28_599.70,
        "maintenance_margin": 16_941.76,
        "multiplier": 4.0,
        "daytrade_count": None,
        "status": "ACTIVE",
    }
    values.update(overrides)
    return AccountBalances(**values)


def _snapshot(**overrides) -> AccountSnapshot:
    return AccountSnapshot(
        summary=None,
        balances=_balances(**overrides),
        positions=(),
        taken_at=datetime.now(UTC),
    )


def _panel(qtbot, level: UiLevel, **overrides) -> BalancesPanel:
    panel = BalancesPanel(1.0, level=level)
    qtbot.addWidget(panel)
    panel.show()
    panel.update_from(_snapshot(**overrides))
    return panel


# --- The predicate ------------------------------------------------------------


def test_only_professional_prefers_density() -> None:
    """`shows_advanced()` cannot serve here - it is true at Standard, and
    Standard wants the group folded rather than open."""
    assert UiLevel.GUIDED.prefers_density() is False
    assert UiLevel.STANDARD.prefers_density() is False
    assert UiLevel.PROFESSIONAL.prefers_density() is True


# --- Three levels, three outcomes ---------------------------------------------


def test_guided_explains_and_omits_the_broker_group(qtbot):
    """Fewer figures, each explained - `ui_level`'s own description of Guided."""
    panel = _panel(qtbot, UiLevel.GUIDED)

    assert panel.broker_group is None
    assert panel.captions[0].isVisible() is True


def test_standard_explains_and_folds_the_broker_group(qtbot):
    """Everything present, with explanations. Present but folded is not the
    same as absent, and the operator can open it."""
    panel = _panel(qtbot, UiLevel.STANDARD)

    assert panel.broker_group is not None
    assert panel.captions[0].isVisible() is True
    assert panel.broker_body.isVisible() is False


def test_professional_drops_the_captions_and_opens_the_group(qtbot):
    """Maximum density, explanations off."""
    panel = _panel(qtbot, UiLevel.PROFESSIONAL)

    assert panel.broker_group is not None
    assert panel.captions[0].isVisible() is False
    assert panel.broker_body.isVisible() is True


def test_guided_and_standard_are_not_the_same_screen(qtbot):
    """The defect this design already had once, pinned so it cannot return.

    Both levels explain, so a scheme keyed only on `explains()` renders them
    identically - three settings producing two outcomes.
    """
    guided = _panel(qtbot, UiLevel.GUIDED)
    standard = _panel(qtbot, UiLevel.STANDARD)

    assert (guided.broker_group is None) != (standard.broker_group is None)


def test_the_operator_can_open_the_folded_group(qtbot):
    """The level sets the STARTING state and never locks the control. That is
    the difference between folding detail away and hiding it."""
    panel = _panel(qtbot, UiLevel.STANDARD)
    assert panel.broker_body.isVisible() is False

    panel.broker_toggle.click()

    assert panel.broker_body.isVisible() is True


# --- Safety is not a level ----------------------------------------------------


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_a_blocked_account_is_unmistakable_at_every_level(qtbot, level):
    """The one cell here that is genuinely safety-relevant. It stays in the
    primary group at every level and is never folded away."""
    panel = _panel(qtbot, level, status="ACCOUNT_CLOSED", trading_blocked=True)

    assert panel.account_status.isVisible() is True
    assert "BLOCKED" in panel.account_status._value.text()


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_the_freshness_line_survives_every_level(qtbot, level):
    """A stale figure is a safety concern rather than a detail."""
    panel = _panel(qtbot, level)

    assert panel.freshness.isVisible() is True


def test_caption_text_is_set_even_when_it_is_hidden(qtbot):
    """M58c's rule. Hidden, not absent - so anything reading the panel
    programmatically still sees the whole story."""
    panel = _panel(qtbot, UiLevel.PROFESSIONAL)

    assert panel.captions[0].isVisible() is False
    assert panel.captions[0].text().strip() != ""


def test_the_spendable_caption_explains_the_buying_power_gap(qtbot):
    """At Guided the buying-power CELL is gone, so the caption is what stops an
    operator seeing $336k at Alpaca and finding nothing here that explains why
    this system will not spend it."""
    panel = _panel(qtbot, UiLevel.GUIDED)

    spendable_caption = panel.caption_for("Spendable here")
    assert "margin" in spendable_caption.text().lower()


# --- The figures themselves are unchanged -------------------------------------


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_the_primary_figures_render_identically_at_every_level(qtbot, level):
    """Only the arrangement changes. A cell showing $101,244.97 shows exactly
    that at every level."""
    panel = _panel(qtbot, level)

    assert panel.portfolio_value._value.text() == "$101,244.97"
    assert panel.spendable._value.text() == "$44,771.43"


def test_the_demoted_figures_keep_their_values(qtbot):
    """Demoted is not discarded - the numbers are the same, in a quieter place."""
    panel = _panel(qtbot, UiLevel.PROFESSIONAL)

    # Was three assertions until 21 August. The margin figures and short market
    # value were removed from the panel entirely - on IBKR all three render a
    # permanent dash, and short value is structurally zero on a long-only
    # system. Buying power is what is left in the demoted row, and it is real.
    assert panel.buying_power._value.text().startswith("$336,485.98")
