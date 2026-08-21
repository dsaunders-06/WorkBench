"""Feeds the daily-loss and drawdown rails (spec M13).

Before M13, KillSwitch.check_daily_loss and KillSwitch.check_drawdown were
implemented and unit-tested but called from nowhere in `src/` - the two rails
the README leads with were dead code in the running application. Nothing
polled equity, nothing tracked a day-start value, nothing tracked a high-water
mark. This engine is what makes them real.

State is persisted to disk because both rails are meaningless across a
restart otherwise: a high-water mark that resets to the current equity every
time the app launches can never register a drawdown, and a day-start equity
re-read at 3pm makes the day's loss look like zero. The original app persisted
both for exactly this reason.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qat.config import Settings
from qat.data.broker.adapter import BrokerAdapter
from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent
from qat.domain.market_calendar import trading_date
from qat.domain.risk_engine.kill_switch import KillSwitch

logger = logging.getLogger(__name__)

STATE_FILENAME = "equity_state.json"


@dataclass
class EquityState:
    day: str
    day_start_equity: float
    high_water_mark: float

    @property
    def as_dict(self) -> dict[str, object]:
        return {
            "day": self.day,
            "day_start_equity": self.day_start_equity,
            "high_water_mark": self.high_water_mark,
        }


class EquityMonitor:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "equity-monitor"

    def __init__(
        self,
        broker: BrokerAdapter,
        kill_switch: KillSwitch,
        settings: Settings | None = None,
        data_dir: str | Path | None = None,
        bus: EventBus | None = None,
        equity_curve: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.broker = broker
        self.kill_switch = kill_switch
        self.bus = bus
        # Optional EquityCurve (domain.performance). This engine already polls
        # the account on a timer, so it is the natural sampler - a separate
        # poller would double the broker traffic to record the same number.
        self.equity_curve = equity_curve
        self.settings = settings or Settings()
        self.path = Path(data_dir or self.settings.data_dir) / STATE_FILENAME
        # Defaults to the wall clock; injected so a test can cross a DST
        # boundary without waiting until October (M111).
        self._clock = clock or (lambda: datetime.now(UTC))
        self.state: EquityState | None = None
        self.last_equity: float | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a bad poll must not kill the rails
                logger.exception("Equity poll failed; continuing")
            await asyncio.sleep(self.settings.equity_poll_seconds)

    async def poll(self) -> EquityState:
        """One measurement: refresh state, then test both rails.

        Public and separately awaitable so tests and the UI can force a
        measurement without waiting on the poll interval.
        """
        account = await self.broker.account()
        equity = float(account.net_liquidation)
        self.last_equity = equity

        state = self._refresh_state(equity)
        self._save(state)

        if self.equity_curve is not None:
            try:
                # M133. `gross_position_value` is what exposure means. Passed
                # through as None when the broker does not report it, so the
                # metric can say "unknown" instead of inferring it from
                # `equity - cash` and counting accrued interest as a position.
                position_value = getattr(account, "gross_position_value", None)
                self.equity_curve.record(  # type: ignore[attr-defined]
                    equity,
                    float(account.cash),
                    position_value=None if position_value is None else float(position_value),
                )
            except Exception:  # noqa: BLE001 - sampling must not break the rails
                logger.warning("Could not record an equity sample", exc_info=True)

        was_tripped = self.kill_switch.tripped
        self.kill_switch.check_daily_loss(
            state.day_start_equity, equity, self.settings.daily_loss_limit_pct
        )
        self.kill_switch.check_drawdown(
            state.high_water_mark, equity, self.settings.max_drawdown_limit_pct
        )

        # KillSwitch.trip() is a plain state change that publishes nothing, so
        # without this a rail could trip here and no screen would ever hear
        # about it - the halt would be real but invisible until something
        # happened to re-read the switch.
        if self.bus is not None and self.kill_switch.tripped and not was_tripped:
            await self.bus.publish(
                KillSwitchEvent(
                    reason=self.kill_switch.reason or "equity rail breached",
                    triggered_by=self.name,
                )
            )
        return state

    def day_pnl_pct(self, equity: float | None = None) -> float:
        """Today's P&L as a fraction of day-start equity. 0.0 before the first
        poll - an unknown P&L must not read as a loss, which would pause buys
        on nothing more than the app having just started."""
        current = equity if equity is not None else self.last_equity
        if self.state is None or current is None or self.state.day_start_equity <= 0:
            return 0.0
        return (current - self.state.day_start_equity) / self.state.day_start_equity

    def _refresh_state(self, equity: float) -> EquityState:
        # M111. Was `datetime.now(UTC).strftime(...)`, which is a UTC date and
        # not a trading day. The ASX session crosses UTC midnight under AEDT,
        # so from 5 October 2026 this ran an hour into the session, logged
        # "New trading day", and re-baselined the daily-loss rail against a
        # book that had already moved.
        today = trading_date(self.settings.market, self._clock()).isoformat()
        state = self.state if self.state is not None else self._load()

        if state is None or state.day != today:
            # A new day resets the day-start equity but never the high-water
            # mark: drawdown-from-peak is a running measure that a date change
            # has no business clearing.
            previous_hwm = state.high_water_mark if state else equity
            state = EquityState(
                day=today,
                day_start_equity=equity,
                high_water_mark=max(previous_hwm, equity),
            )
            logger.info("New trading day - day-start equity recorded as %.2f", equity)
        elif equity > state.high_water_mark:
            state.high_water_mark = equity

        self.state = state
        return state

    def _load(self) -> EquityState | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return EquityState(
                day=str(raw["day"]),
                day_start_equity=float(raw["day_start_equity"]),
                high_water_mark=float(raw["high_water_mark"]),
            )
        except (OSError, KeyError, ValueError, TypeError):
            logger.warning("Could not read %s - starting fresh", self.path, exc_info=True)
            return None

    def _save(self, state: EquityState) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(state.as_dict, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Could not persist equity state to %s", self.path)
