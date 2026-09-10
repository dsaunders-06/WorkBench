"""M100 / Task 5 option 1: UNSUPPORTED is not UNREADABLE.

`CorporateActionMonitor._fetch` calls `broker.announcements(...)` inside a
`try/except Exception`. On an adapter that does not implement it - IBKR - the
`AttributeError` is caught and **every held symbol lands in `_unreadable` on
every sweep**.

The blindness reporting itself is right and was built deliberately: M39 makes
blindness a STATE so no screen can say "none pending" while the detector cannot
see. What is wrong is the KIND of state.

**The message describes a transient fault; the condition is permanent.** The
Risk Console says *the query failed - see the log for why*, and the log says
`AttributeError`, every time, for ever. There is no query. At
`protection_sweep_seconds=300` with ten positions that is 2,880 warnings a day
and a permanently lit banner pointing at something unfixable - which is how an
operator learns to stop reading banners. This project has already found that
shape three times in `session_check`: *an alarm you learn to ignore is worse
than no alarm.*

So the two states are separated:

* **UNSUPPORTED** - this adapter has no `announcements` method at all.
  Permanent, knowable without asking, stated once, calmly.
* **UNREADABLE** - the method exists and this pass failed. Transient, worth an
  alarm, worth "check the log".

Both must still refuse to report "none pending", which is the invariant M39
was built around and the one thing neither state may break.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pytest

from qat.data.broker.adapter import Position, RestingStopOrder
from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.monitor import CorporateActionMonitor


class _Broker:
    """A broker with positions and stops. `announcements` is present only if
    `serves_announcements`, which is the whole distinction under test."""

    def __init__(self, serves_announcements: bool, raises: bool = False) -> None:
        self.calls = 0
        self._raises = raises
        if serves_announcements:
            self.announcements = self._announcements  # type: ignore[assignment]

    async def _announcements(self, symbol: str, since: date, until: date) -> list[Announcement]:
        self.calls += 1
        if self._raises:
            raise RuntimeError("the endpoint is down")
        return []

    async def positions(self) -> list[Position]:
        return [
            Position(symbol="BHP.AX", quantity=10, avg_price=60.0),
            Position(symbol="CBA.AX", quantity=5, avg_price=100.0),
        ]

    async def resting_stop_orders(self) -> dict[str, RestingStopOrder]:
        return {}

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        return {"last": 60.0}


def _monitor(broker: _Broker, tmp_path: Any) -> CorporateActionMonitor:
    from qat.config import Settings

    class _OMS:
        pass

    oms = _OMS()
    oms.broker = broker  # type: ignore[attr-defined]
    return CorporateActionMonitor(
        oms=oms,
        settings=Settings(_env_file=None, trading_mode="paper", data_dir=str(tmp_path)),
        entries_source=lambda: {},
    )


async def test_an_adapter_without_announcements_is_UNSUPPORTED_not_blind(tmp_path) -> None:
    """The whole point. Every held symbol landing in `unreadable_symbols()`
    every sweep is a permanent condition wearing a transient one's clothes."""
    monitor = _monitor(_Broker(serves_announcements=False), tmp_path)

    await monitor.refresh()

    assert monitor.detection_supported() is False
    assert monitor.unreadable_symbols() == [], (
        "a capability gap was reported as a per-symbol query failure - the "
        "banner would say 'check the log' about something unfixable"
    )


async def test_an_adapter_that_serves_announcements_is_supported(tmp_path) -> None:
    monitor = _monitor(_Broker(serves_announcements=True), tmp_path)

    await monitor.refresh()

    assert monitor.detection_supported() is True
    assert monitor.unreadable_symbols() == []


async def test_a_real_query_failure_is_still_UNREADABLE(tmp_path) -> None:
    """The transient path is unchanged. A method that exists and fails is
    exactly what the existing alarm was built for, and it keeps it."""
    monitor = _monitor(_Broker(serves_announcements=True, raises=True), tmp_path)

    await monitor.refresh()

    assert monitor.detection_supported() is True
    assert monitor.unreadable_symbols() == ["BHP.AX", "CBA.AX"]


async def test_an_unsupported_adapter_is_not_asked_once_per_symbol(tmp_path) -> None:
    """2,880 warnings a day came from asking a question that cannot be
    answered, per symbol, per sweep. Knowing the answer without asking is the
    fix, not a quieter log level."""
    broker = _Broker(serves_announcements=False)
    monitor = _monitor(broker, tmp_path)

    await monitor.refresh()
    await monitor.refresh()

    assert broker.calls == 0


async def test_the_capability_is_logged_once_not_every_sweep(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    monitor = _monitor(_Broker(serves_announcements=False), tmp_path)

    with caplog.at_level(logging.WARNING):
        await monitor.refresh()
        await monitor.refresh()
        await monitor.refresh()

    said = [r for r in caplog.records if "UNAVAILABLE" in r.message or "unavailable" in r.message]
    assert len(said) == 1, [r.message for r in said]


async def test_neither_state_may_claim_nothing_is_pending(tmp_path) -> None:
    """The invariant M39 exists to protect, and the one thing neither state is
    allowed to break: a screen must never read 'none pending' while the
    detector cannot see. `pending_actions()` is empty in both cases, so the
    screens must distinguish them by asking, which is what
    `detection_supported()` is for."""
    unsupported = _monitor(_Broker(serves_announcements=False), tmp_path)
    await unsupported.refresh()

    assert unsupported.pending_actions() == []
    assert unsupported.detection_supported() is False


async def test_the_unsupported_verdict_is_re_derived_not_latched(tmp_path) -> None:
    """A mutation run found this: the initial value is already True, so nothing
    exercised the reset and "once unsupported, always unsupported" passed every
    test. It matters because the broker is read from the OMS on every pass and
    can be swapped - a monitor that latched False would keep reporting
    UNAVAILABLE against an adapter that answers perfectly well, which is the
    same class of lie in the opposite direction.
    """
    monitor = _monitor(_Broker(serves_announcements=False), tmp_path)
    await monitor.refresh()
    assert monitor.detection_supported() is False

    monitor.oms.broker = _Broker(serves_announcements=True)  # type: ignore[attr-defined]
    await monitor.refresh()

    assert monitor.detection_supported() is True


# --- what the operator actually reads -------------------------------------


class _Monitor:
    def __init__(self, supported: bool, unreadable: list[str] | None = None) -> None:
        self._supported = supported
        self._unreadable = unreadable or []

    def detection_supported(self) -> bool:
        return self._supported

    def unreadable_symbols(self) -> list[str]:
        return list(self._unreadable)

    def pending_actions(self) -> list[Any]:
        return []


def test_the_risk_console_says_UNAVAILABLE_not_could_not_be_read() -> None:
    """A permanent capability stated calmly, once, without instructing anyone
    to go and read a log that will say the same thing for ever."""
    from qat.presentation.risk_console import corporate_action_summary

    text = corporate_action_summary(_Monitor(supported=False), mode="shadow")

    assert "UNAVAILABLE" in text
    assert "none pending" not in text.lower(), "the one claim neither state may make"
    assert "check the log" not in text.lower()


def test_the_risk_console_still_alarms_on_a_real_query_failure() -> None:
    from qat.presentation.risk_console import corporate_action_summary

    text = corporate_action_summary(_Monitor(supported=True, unreadable=["BHP.AX"]), mode="shadow")

    assert "COULD NOT BE READ" in text
    assert "BHP.AX" in text


def test_the_risk_console_may_say_none_pending_only_when_it_can_see() -> None:
    from qat.presentation.risk_console import corporate_action_summary

    text = corporate_action_summary(_Monitor(supported=True), mode="shadow")

    assert "none pending" in text.lower()


def test_the_dashboard_still_shows_something_when_detection_is_unavailable() -> None:
    """The invariant from the Dashboard's own comment: "A silent Dashboard
    while the detector cannot see is indistinguishable from a quiet book."
    That holds for UNAVAILABLE too - so it is shown, but as a STANDING
    CONDITION rather than an alarm. No "check the log": there is nothing in
    the log to find, and sending someone there repeatedly is how the banner
    stops being read at all."""
    from qat.presentation.dashboard import corporate_action_banner_text

    text = corporate_action_banner_text(_Monitor(supported=False), acting=False)

    assert text is not None, "silence here is indistinguishable from a quiet book"
    assert "UNAVAILABLE" in text
    assert "check the log" not in text.lower()


def test_the_dashboard_alarms_normally_on_a_real_failure() -> None:
    from qat.presentation.dashboard import corporate_action_banner_text

    text = corporate_action_banner_text(
        _Monitor(supported=True, unreadable=["BHP.AX"]), acting=False
    )

    assert text is not None
    assert "COULD NOT BE READ" in text
    assert "Check the log" in text


def test_the_dashboard_is_silent_when_it_can_see_and_nothing_is_pending() -> None:
    from qat.presentation.dashboard import corporate_action_banner_text

    assert corporate_action_banner_text(_Monitor(supported=True), acting=False) is None


# --- The standing condition is stated ONCE (10 September 2026) ----------------


def test_the_standing_condition_is_stated_the_first_time() -> None:
    """⚠️ OPERATOR DECISION, 10 September 2026, restoring a call they made
    originally and were talked out of.

    The invariant above still holds - silence on the FIRST pass would be
    indistinguishable from a quiet book, so it is still said.
    """
    from qat.presentation.dashboard import corporate_action_banner_text

    text = corporate_action_banner_text(
        _Monitor(supported=False), acting=False, standing_condition_stated=False
    )

    assert text is not None
    assert "UNAVAILABLE" in text


def test_the_standing_condition_is_NOT_repeated() -> None:
    """A permanent banner is furniture, not an alert.

    It fired at EVERY startup, in the same visual space as five real
    kill-switch alerts on 9 September. A condition that cannot change while
    this broker is connected is stated once and then stops competing with
    things that CAN change.
    """
    from qat.presentation.dashboard import corporate_action_banner_text

    text = corporate_action_banner_text(
        _Monitor(supported=False), acting=False, standing_condition_stated=True
    )

    assert text is None


def test_a_REAL_failure_still_alarms_every_time() -> None:
    """⚠️ THE CONTROL, and it is what stops this becoming a silencer.

    The gate is scoped to the STANDING condition. A symbol the detector could
    not read is a per-occurrence fact that can change between passes, and
    suppressing it would be the corporate-action banner's own disease in a new
    place - a rail that stops reporting.
    """
    from qat.presentation.dashboard import corporate_action_banner_text

    text = corporate_action_banner_text(
        _Monitor(supported=True, unreadable=["BHP.AX"]),
        acting=False,
        standing_condition_stated=True,
    )

    assert text is not None
    assert "COULD NOT BE READ" in text
