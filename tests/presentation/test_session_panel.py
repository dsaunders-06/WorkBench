"""Dashboard market session panel (spec M19): countdowns and the 30-minute
alert threshold, asserted against an injected clock rather than waited for."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qat.config import Settings
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime
from qat.presentation.session_panel import (
    ALERT_SECONDS,
    countdown_for,
    format_duration,
)

NY = ZoneInfo("America/New_York")

MID_SESSION = datetime(2026, 7, 29, 12, 0, tzinfo=NY)
JUST_INSIDE_CLOSE_ALERT = datetime(2026, 7, 29, 15, 31, tzinfo=NY)  # 29 min to 16:00
JUST_OUTSIDE_CLOSE_ALERT = datetime(2026, 7, 29, 15, 29, tzinfo=NY)  # 31 min to 16:00
JUST_INSIDE_OPEN_ALERT = datetime(2026, 7, 29, 9, 1, tzinfo=NY)  # 29 min to 09:30
JUST_OUTSIDE_OPEN_ALERT = datetime(2026, 7, 29, 8, 59, tzinfo=NY)  # 31 min to 09:30
SATURDAY = datetime(2026, 7, 25, 12, 0, tzinfo=NY)
HOLIDAY = datetime(2026, 7, 3, 12, 0, tzinfo=NY)  # observed Independence Day


def test_durations_render_as_hh_mm_ss():
    assert format_duration(0) == "00:00:00"
    assert format_duration(59) == "00:00:59"
    assert format_duration(3661) == "01:01:01"
    assert format_duration(36_000) == "10:00:00"


def test_a_passed_deadline_clamps_to_zero_rather_than_going_negative():
    """A negative countdown looks like a fault; zero reads as 'any moment'."""
    assert format_duration(-5) == "00:00:00"


def test_an_open_market_counts_down_to_the_close():
    countdown = countdown_for("US", MID_SESSION)

    assert countdown.is_open is True
    assert countdown.headline == "US OPEN"
    assert countdown.detail == "closes in 04:00:00"
    assert countdown.alerting is False


def test_a_closed_market_counts_down_to_the_next_open():
    countdown = countdown_for("US", JUST_OUTSIDE_OPEN_ALERT)

    assert countdown.is_open is False
    assert "opens in 00:31:00" in countdown.detail


@pytest.mark.parametrize(
    ("label", "now", "expected"),
    [
        ("29 min to close", JUST_INSIDE_CLOSE_ALERT, True),
        ("31 min to close", JUST_OUTSIDE_CLOSE_ALERT, False),
        ("29 min to open", JUST_INSIDE_OPEN_ALERT, True),
        ("31 min to open", JUST_OUTSIDE_OPEN_ALERT, False),
    ],
)
def test_the_alert_turns_on_inside_thirty_minutes(label, now, expected):
    assert countdown_for("US", now).alerting is expected, label


def test_the_alert_threshold_is_thirty_minutes():
    assert ALERT_SECONDS == 30 * 60


def test_a_weekend_counts_down_to_monday_not_to_tomorrow():
    countdown = countdown_for("US", SATURDAY)

    assert countdown.is_open is False
    assert "weekend" in countdown.headline
    assert "Mon" in countdown.detail


def test_a_holiday_is_named_rather_than_shown_as_an_ordinary_closure():
    """ "Closed" on a Friday morning with no explanation reads as a bug."""
    countdown = countdown_for("US", HOLIDAY)

    assert "public holiday" in countdown.headline
    assert countdown.is_open is False


def test_routine_closures_are_not_editorialised():
    """Before the open on a trading day is mechanics, not news."""
    assert countdown_for("US", JUST_OUTSIDE_OPEN_ALERT).headline == "US closed"


def test_an_alerting_countdown_is_coloured_differently_from_a_calm_one():
    calm = countdown_for("US", MID_SESSION)
    alerting = countdown_for("US", JUST_INSIDE_CLOSE_ALERT)

    assert calm.colour != alerting.colour


# --- the panel on the Dashboard ---------------------------------------------


def _dashboard(qtbot, **settings_kwargs) -> DashboardScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, **settings_kwargs))
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def test_the_dashboard_shows_the_session_panel(qtbot):
    screen = _dashboard(qtbot)

    assert screen.session_panel is not None
    assert screen.session_panel.headline.text()
    assert screen.session_panel.session_status.text()


def test_the_override_button_is_hidden_when_session_control_is_off(qtbot):
    """On simulated prices the session never stands down, so an override would
    offer to fix something that is not broken."""
    screen = _dashboard(qtbot, market_data_source="synthetic")

    # isVisibleTo rather than show() + isVisible, matching the pattern in
    # test_execution_mode_ui. Realising this screen paints its pyqtgraph equity
    # plot, and a paint dispatched from pytest-qt's event pumping against a
    # widget being torn down is an access violation that kills the whole run -
    # a race so finely balanced that merely adding a module to the import chain
    # took it from never firing to seven runs in ten. The assertion does not
    # need a realised widget, so it should not ask for one.
    assert screen.session_panel.start_button.isVisibleTo(screen) is False


def test_the_panel_reports_the_controller_state_rather_than_re_deriving_it(qtbot):
    """If the panel computed 'is trading live' itself it could disagree with
    the engine that actually decides."""
    screen = _dashboard(qtbot)
    controller = screen.runtime.session_controller

    controller.enabled = True
    controller.active = False
    screen.session_panel.refresh()

    assert "standing by" in screen.session_panel.session_status.text()


# --- open-market prominence (M20) -------------------------------------------


def test_an_open_market_is_a_filled_banner_not_just_coloured_text():
    """Whether the market is open is the most consequential fact on the
    Dashboard, and coloured text alone was too easy to miss."""
    assert "background-color" in countdown_for("US", MID_SESSION).banner_style


def test_an_imminent_open_is_also_filled():
    assert "background-color" in countdown_for("US", JUST_INSIDE_OPEN_ALERT).banner_style


def test_a_quiet_closure_stays_flat():
    """Making every state shout is the same as making none of them."""
    assert "background-color" not in countdown_for("US", SATURDAY).banner_style


def test_the_open_banner_and_the_alert_banner_differ():
    calm = countdown_for("US", MID_SESSION).banner_style
    closing_soon = countdown_for("US", JUST_INSIDE_CLOSE_ALERT).banner_style

    assert calm != closing_soon
    assert "background-color" in calm and "background-color" in closing_soon
