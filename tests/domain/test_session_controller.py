"""Session lifecycle against market hours (spec M19).

The clock is injected everywhere, so these assert real calendar behaviour -
weekends, holidays, the open and the close - without waiting for one.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qat.domain.session_controller import SessionController

NY = ZoneInfo("America/New_York")

# Wednesday 29 July 2026: an ordinary US trading day.
MID_SESSION = datetime(2026, 7, 29, 12, 0, tzinfo=NY)
BEFORE_OPEN = datetime(2026, 7, 29, 7, 0, tzinfo=NY)
AFTER_CLOSE = datetime(2026, 7, 29, 18, 0, tzinfo=NY)
SATURDAY = datetime(2026, 7, 25, 12, 0, tzinfo=NY)
# 4 July 2026 falls on a Saturday, so the holiday is observed on Friday the 3rd.
HOLIDAY = datetime(2026, 7, 3, 12, 0, tzinfo=NY)


class FakeFeed:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.running = True  # the orchestrator starts it before the controller runs

    async def start(self) -> None:
        self.started += 1
        self.running = True

    async def stop(self) -> None:
        self.stopped += 1
        self.running = False


class FakeEngine:
    def __init__(self) -> None:
        self.emitting = True


def _controller(now: datetime, **kwargs) -> tuple[SessionController, FakeFeed, FakeEngine]:
    feed, engine = FakeFeed(), FakeEngine()
    clock = kwargs.pop("clock", None) or (lambda: now)
    controller = SessionController(feed, engine, market="US", clock=clock, **kwargs)
    return controller, feed, engine


@pytest.mark.parametrize(
    ("label", "now"),
    [
        ("before open", BEFORE_OPEN),
        ("after close", AFTER_CLOSE),
        ("weekend", SATURDAY),
        ("holiday", HOLIDAY),
    ],
)
async def test_the_session_stands_down_while_the_market_is_shut(label, now):
    controller, feed, engine = _controller(now)

    await controller.apply_once()

    assert controller.active is False, label
    assert feed.running is False
    assert engine.emitting is False


async def test_the_session_runs_while_the_market_is_open():
    controller, feed, engine = _controller(MID_SESSION)

    await controller.apply_once()

    assert controller.active is True
    assert feed.running is True
    assert engine.emitting is True
    assert feed.stopped == 0  # it was already running; nothing to do


async def test_the_feed_is_restarted_at_the_open():
    """The whole point: a session that stood down overnight must come back."""
    current = {"now": AFTER_CLOSE}
    controller, feed, engine = _controller(AFTER_CLOSE, clock=lambda: current["now"])

    await controller.apply_once()
    assert controller.active is False

    current["now"] = MID_SESSION
    await controller.apply_once()

    assert controller.active is True
    assert feed.started == 1
    assert engine.emitting is True


async def test_repeated_checks_do_not_thrash_the_feed():
    """apply_once runs on a timer, so it must be idempotent - restarting the
    feed every twenty seconds would re-subscribe and lose the tick buffer."""
    controller, feed, _ = _controller(AFTER_CLOSE)

    for _ in range(5):
        await controller.apply_once()

    assert feed.stopped == 1
    assert feed.started == 0


async def test_disabled_control_leaves_everything_running():
    """The default on simulated prices, which have no trading hours."""
    controller, feed, engine = _controller(SATURDAY, enabled=False)

    await controller.apply_once()

    assert controller.active is True
    assert feed.running is True
    assert engine.emitting is True
    assert "always on" in controller.status_line()


# --- manual override ---------------------------------------------------------


async def test_the_override_starts_a_session_against_a_closed_market():
    controller, feed, engine = _controller(SATURDAY)
    await controller.apply_once()
    assert controller.active is False

    await controller.force_start("tester")

    assert controller.active is True
    assert feed.running is True
    assert engine.emitting is True
    assert "manually started" in controller.status_line()


async def test_a_forced_start_does_not_claim_the_market_is_open(caplog):
    """M52. On 6 August these two lines were logged in the same second:

        Trading session force-started by operator (dashboard) while US is closed
        Trading session started - US is open

    The second contradicted the first. The watcher surfaced only the second, so
    the operator was told the market was open eight minutes before it was."""
    controller, _feed, _engine = _controller(SATURDAY)
    await controller.apply_once()  # stand down first, so the start is a transition

    with caplog.at_level("INFO"):
        await controller.force_start("tester")

    text = caplog.text
    assert "is NOT open" in text
    assert "OPERATOR OVERRIDE" in text
    assert "is open" not in text.replace("is NOT open", ""), "must not assert an open market"
    # And it says what the override turns on, because a forced start disarms
    # the staleness rail's exemption for a shut market.
    assert "staleness rail" in text


async def test_a_real_open_still_reads_as_a_plain_start(caplog):
    controller, _feed, _engine = _controller(MID_SESSION)
    controller.active = False  # as at launch, before the first check

    with caplog.at_level("INFO"):
        await controller.apply_once()

    assert "Trading session started - US is open" in caplog.text
    assert "OPERATOR OVERRIDE" not in caplog.text


async def test_the_override_survives_repeated_checks():
    controller, feed, _ = _controller(SATURDAY)
    await controller.force_start("tester")

    for _ in range(3):
        await controller.apply_once()

    assert controller.active is True


async def test_the_override_retires_itself_once_the_market_opens():
    """It exists so a closed market never blocks the operator, not as a
    standing exemption from the schedule."""
    current = {"now": BEFORE_OPEN}
    controller, _, _ = _controller(BEFORE_OPEN, clock=lambda: current["now"])

    await controller.force_start("tester")
    assert controller.override_until_close is True

    current["now"] = MID_SESSION
    await controller.apply_once()

    assert controller.override_until_close is False
    assert controller.active is True  # still active, but now because it is open

    current["now"] = AFTER_CLOSE
    await controller.apply_once()

    assert controller.active is False, "the override must not outlive the session"


async def test_clearing_the_override_stands_the_session_back_down():
    controller, _, engine = _controller(SATURDAY)
    await controller.force_start("tester")

    await controller.clear_override()

    assert controller.active is False
    assert engine.emitting is False


async def test_the_status_line_names_why_the_market_is_shut():
    controller, _, _ = _controller(HOLIDAY)
    await controller.apply_once()

    assert "public holiday" in controller.status_line()
