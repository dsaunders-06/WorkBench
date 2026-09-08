"""The Regime Monitor says what the regime DOES, not just what it is.

The screen rendered the label and seven probability bars - the inputs - and
never which strategies that permits, which is the fact governing whether
anything trades.

**Eligibility is not the label.** Since M27b it is probability MASS, summed
across a strategy's suitable regimes against a 0.5 threshold, because the label
is one draw from a distribution and collapsing to it turns a near-tie into a
certainty. So an operator reading "Regime: bull" and inferring swing is trading
can be wrong in either direction - and a strategy silently ineligible for a
whole session looks exactly like one that found no setup.

M57c had to fix a regime LOG line that described a mechanism replaced in M27b.
The screen carried the same defect.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.events import RegimeEvent
from qat.presentation.regime_monitor import RegimeMonitorScreen
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel


def _runtime(tmp_path, level: UiLevel) -> Runtime:
    return Runtime.build_demo(
        settings=Settings(
            _env_file=None,
            data_dir=str(tmp_path),
            ui_level=level.label.lower(),
            deployed_strategies="swing",
        )
    )


def _screen(qtbot, tmp_path, level: UiLevel) -> RegimeMonitorScreen:
    screen = RegimeMonitorScreen(_runtime(tmp_path, level))
    qtbot.addWidget(screen)
    screen.show()
    return screen


async def _publish(screen: RegimeMonitorScreen, event: RegimeEvent) -> None:
    """Drive BOTH handlers, because the real application does.

    Driving only the screen was how the concurrency bug hid: the engine had not
    read the distribution, `is_eligible` fell back to label membership, and a
    bear regime reported swing as PERMITTED. `EventBus.publish` dispatches with
    `asyncio.gather`, so ordering these by hand would prove nothing - the engine
    is given the event first and the screen renders from the engine's listener.
    """
    await screen.runtime.strategy_engine._on_regime(event)
    await screen._on_regime(event)


def _bull_event() -> RegimeEvent:
    """A distribution whose mass sits mostly in swing's suitable regimes."""
    return RegimeEvent(
        label="bull",
        probs={"bull": 0.45, "sideways": 0.17, "high_vol": 0.20, "bear": 0.18},
        exposure_scalar=1.0,
    )


def _bear_event() -> RegimeEvent:
    """Mass sits outside them, so swing must read as not permitted."""
    return RegimeEvent(
        label="bear",
        probs={"bear": 0.55, "high_vol": 0.25, "bull": 0.12, "sideways": 0.08},
        exposure_scalar=0.4,
    )


# --- The consequence, which was missing entirely -------------------------------


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
async def test_eligibility_is_stated_at_every_level(qtbot, tmp_path, level):
    """Not level-gated. A strategy silently ineligible for a session is
    indistinguishable from one that found no setup - that was a defect, not a
    detail."""
    screen = _screen(qtbot, tmp_path, level)

    await _publish(screen, _bull_event())

    assert screen.eligibility_label.isVisible() is True
    assert "swing" in screen.eligibility_label.text().lower()


async def test_a_permitting_regime_says_so(qtbot, tmp_path):
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    await _publish(screen, _bull_event())

    assert "PERMITTED" in screen.eligibility_label.text()
    assert "NOT PERMITTED" not in screen.eligibility_label.text()


async def test_a_forbidding_regime_says_so(qtbot, tmp_path):
    """The case that matters. The label reads 'bear' and swing stops trading -
    which today the operator could only infer."""
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    await _publish(screen, _bear_event())

    assert "NOT PERMITTED" in screen.eligibility_label.text()


async def test_the_screen_reports_what_the_engine_decides_not_its_own_sum(qtbot, tmp_path):
    """Reuse, not reimplementation - the rule the adopted panel already pins.

    This is the test that fails if someone later 'simplifies' the screen by
    computing mass from `probs`. The engine is told to refuse; the probabilities
    say otherwise; the screen must follow the engine, because the engine is what
    actually gates the trade.
    """
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)
    screen.runtime.strategy_engine.is_eligible = lambda strategy: False  # type: ignore[method-assign]

    await _publish(screen, _bull_event())

    assert "NOT PERMITTED" in screen.eligibility_label.text()


async def test_the_screens_own_handler_does_not_decide_eligibility(qtbot, tmp_path):
    """The concurrency fix, pinned.

    `EventBus.publish` dispatches with `asyncio.gather`, so the screen's
    RegimeEvent handler and the strategy engine's run at the same time. If the
    screen derived eligibility in its own handler it could render the PREVIOUS
    regime's verdict, and would do so precisely when a regime changes - the one
    moment anybody is looking at this screen.

    So: give the screen a bear event WITHOUT the engine having seen it. The
    verdict must not move, because the screen is not the thing that decides it.
    """
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)
    await _publish(screen, _bull_event())
    assert "PERMITTED" in screen.eligibility_label.text()
    before = screen.eligibility_label.text()

    await screen._on_regime(_bear_event())

    assert screen.eligibility_label.text() == before
    # The label and scalar DO move: they come straight from the event, so no
    # ordering question arises for them.
    assert "bear" in screen.regime_label.text()


async def test_nothing_is_claimed_before_a_regime_arrives(qtbot, tmp_path):
    """`is_eligible` falls back to label membership with no distribution. That
    is a sensible fallback and a terrible thing to present as a measurement."""
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    assert "PERMITTED" not in screen.eligibility_label.text()
    assert "waiting" in screen.eligibility_label.text().lower()


# --- Three levels, three outcomes ---------------------------------------------


async def test_guided_explains_the_scalar_and_hides_the_arithmetic(qtbot, tmp_path):
    screen = _screen(qtbot, tmp_path, UiLevel.GUIDED)
    await _publish(screen, _bear_event())

    assert screen.scalar_sentence.isVisible() is True
    assert "40%" in screen.scalar_sentence.text()
    assert screen.mass_detail.isVisible() is False
    assert screen.macro_panel.isVisible() is False
    assert screen.driver_table.isVisible() is False


async def test_standard_adds_the_arithmetic_and_the_macro_panel(qtbot, tmp_path):
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)
    await _publish(screen, _bear_event())

    assert screen.scalar_sentence.isVisible() is True
    assert screen.mass_detail.isVisible() is True
    assert screen.macro_panel.isVisible() is True
    # The driver table is what Professional adds; Standard is the default level
    # and keeps the macro panel it already had.
    assert screen.driver_table.isVisible() is False


async def test_professional_drops_the_sentence_and_adds_the_drivers(qtbot, tmp_path):
    screen = _screen(qtbot, tmp_path, UiLevel.PROFESSIONAL)
    await _publish(screen, _bear_event())

    assert screen.scalar_sentence.isVisible() is False
    assert screen.mass_detail.isVisible() is True
    assert screen.macro_panel.isVisible() is True
    assert screen.driver_table.isVisible() is True


async def test_guided_and_standard_are_not_the_same_screen(qtbot, tmp_path):
    """Three settings must give three outcomes. The Balances panel reached
    review with two, because `explains()` is true for both."""
    guided = _screen(qtbot, tmp_path, UiLevel.GUIDED)
    standard = _screen(qtbot, tmp_path, UiLevel.STANDARD)
    await guided._on_regime(_bear_event())
    await standard._on_regime(_bear_event())

    assert guided.mass_detail.isVisible() != standard.mass_detail.isVisible()


# --- Safety, and the boundary with the Risk Console ---------------------------


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
async def test_the_transition_history_survives_every_level(qtbot, tmp_path, level):
    """Do-not-touch, per the brief: a regime change can switch a strategy off
    for a session, and this record is how it is reconstructed afterwards."""
    screen = _screen(qtbot, tmp_path, level)

    assert screen.history_list.isVisible() is True


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
async def test_the_scalar_number_itself_is_never_hidden(qtbot, tmp_path, level):
    """Only the sentence explaining it moves. The figure is the same at every
    level, as the Balances figures are."""
    screen = _screen(qtbot, tmp_path, level)

    await _publish(screen, _bear_event())

    assert "0.40" in screen.regime_label.text()


async def test_it_points_at_the_risk_console_rather_than_answering_for_it(qtbot, tmp_path):
    """ "Why did nothing happen" usually has a non-regime answer. 4.7 gives that
    question to the Risk Console, and two screens deriving one refusal picture
    is how they drift apart."""
    screen = _screen(qtbot, tmp_path, UiLevel.STANDARD)

    await _publish(screen, _bull_event())

    assert "risk console" in screen.elsewhere_hint.text().lower()


def test_a_named_but_unpublished_vix_series_fails_preflight() -> None:
    """⚠️ THE SILENT FAILURE, MADE LOUD. `regime_vix_series` names which series
    fills `vix_level`, and nothing publishes a series it was not asked to
    fetch. Point it at `^AXVI` without adding `^AXVI` to `bar_macro_series` and
    the column sits at ZERO all session while the engine fits happily on a flat
    feature. It led the raw feature spread at 85.1% in the 8 September fit.
    """
    from qat.preflight import Status, settings_checks

    checks = settings_checks(
        Settings(_env_file=None, regime_vix_series="^AXVI", trading_mode="paper")
    )
    named = [check for check in checks if check.name == "regime VIX series"]

    assert len(named) == 1
    assert named[0].status is Status.FAIL
    assert "nothing publishes it" in named[0].detail


def test_the_same_series_passes_once_it_is_bridged() -> None:
    from qat.preflight import Status, settings_checks

    checks = settings_checks(
        Settings(
            _env_file=None,
            regime_vix_series="^AXVI",
            bar_macro_series=("^AXVI",),
            trading_mode="paper",
        )
    )
    named = [check for check in checks if check.name == "regime VIX series"]

    assert named[0].status is Status.OK


def test_the_shipped_default_passes() -> None:
    """VIXCLS is in `fred_series`, so a fresh install is not greeted by a
    failure it did not cause."""
    from qat.preflight import Status, settings_checks

    checks = settings_checks(Settings(_env_file=None))
    named = [check for check in checks if check.name == "regime VIX series"]

    assert named[0].status is Status.OK


def test_swapping_the_vix_series_without_its_level_is_warned_about() -> None:
    """⚠️ THE SECOND HALF OF THE SAME TRAP. `^AXVI` reaches 25.0 on 0.2% of ASX
    days - median 11.52, 99th percentile 18.47 over the two years Yahoo serves.
    Keeping the American level while pointing at the Australian index switches
    the SHOCK regime off, and a regime that never fires looks exactly like a
    market that never shocked."""
    from qat.preflight import Status, settings_checks

    checks = settings_checks(
        Settings(
            _env_file=None,
            regime_vix_series="^AXVI",
            bar_macro_series=("^AXVI",),
            trading_mode="paper",
        )
    )
    named = [check for check in checks if check.name == "VIX shock level"]

    assert len(named) == 1
    assert named[0].status is Status.WARN
    assert "0.2%" in named[0].detail


def test_moving_both_together_draws_no_warning() -> None:
    from qat.preflight import settings_checks

    checks = settings_checks(
        Settings(
            _env_file=None,
            regime_vix_series="^AXVI",
            bar_macro_series=("^AXVI",),
            vix_shock_level=14.0,
            trading_mode="paper",
        )
    )

    assert [check for check in checks if check.name == "VIX shock level"] == []


def test_the_shipped_pair_draws_no_warning() -> None:
    from qat.preflight import settings_checks

    checks = settings_checks(Settings(_env_file=None))

    assert [check for check in checks if check.name == "VIX shock level"] == []
