"""Read-only IBKR daily history for the Phase 3 operational adapter.

The source returns only the requested session to the frozen ingest port. It
keeps the two raw observations in the caller's audit store before conversion.
Call ``fetch`` from a worker thread when a Qt/asyncio loop is running.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time
from decimal import Decimal
from fractions import Fraction
from typing import Any

from qat.config import Settings
from qat.data.broker.ib_readonly import (
    check_paper_account,
    connection_target,
    to_asx_stock_contract,
)
from qat.data.broker.ticks import tick_size
from qat.domain.strategies.authoritative_swing.model import Ohlcv
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor
from qat.operational.history import (
    SYDNEY,
    ActionLedger,
    CalendarLedger,
    HaltLedger,
    OperationalAnalyticalOhlcv,
    OperationalBar,
    _derived_raw,
)

MIN_REQUEST_SPACING_SECONDS = 15.0


def filter_backfill_to_calendar(
    bars: tuple[OperationalBar, ...],
    calendar: CalendarLedger,
    *,
    audit: Callable[[dict[str, object]], None],
) -> tuple[OperationalBar, ...]:
    """Exclude request-margin bars before ingest, preserving a per-symbol audit count."""
    dropped: Counter[str] = Counter()
    accepted: list[OperationalBar] = []
    for bar in bars:
        if bar.session < calendar.coverage_start:
            dropped[bar.symbol] += 1
        else:
            accepted.append(bar)
    for symbol, count in sorted(dropped.items()):
        audit(
            {
                "kind": "history_before_calendar_dropped",
                "symbol": symbol,
                "count": count,
                "coverage_start": calendar.coverage_start.isoformat(),
            }
        )
    return tuple(accepted)


def _default_client() -> Any:
    from ib_async import IB

    return IB()


class IBKRHistoricalBarSource:
    """Two-observation, same-source ASX bar client with strict paper gating."""

    def __init__(
        self,
        settings: Settings,
        actions: ActionLedger,
        halts: HaltLedger,
        *,
        audit: Callable[[dict[str, object]], None],
        client_factory: Callable[[], Any] = _default_client,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if settings.market != "ASX" or settings.is_live or not settings.ibkr_account_id:
            raise ValueError("operational history requires configured ASX paper account")
        host, port, client_id = connection_target(settings)
        if host not in {"127.0.0.1", "localhost", "::1"} or port not in {4002, 7497}:
            raise ValueError("operational history requires local paper Gateway or TWS")
        if actions.fixture or halts.fixture:
            raise ValueError("operational history requires real ASX authorities")
        self.settings = settings
        self.actions = actions
        self.halts = halts
        self.audit = audit
        self.client_factory = client_factory
        self.now = now or (lambda: datetime.now(SYDNEY))
        self.sleep = sleep or asyncio.sleep
        self.host, self.port, self.client_id = host, port, client_id
        self.backfill: tuple[OperationalBar, ...] = ()

    def fetch(self, session: date, symbols: tuple[str, ...]) -> tuple[OperationalBar, ...]:
        if (
            not symbols
            or len(set(symbols)) != len(symbols)
            or any(not symbol.endswith(".AX") for symbol in symbols)
        ):
            raise ValueError("unique ASX symbols required")
        observed = self.now().astimezone(SYDNEY)
        if observed.date() != session or observed >= datetime.combine(session, time(20), SYDNEY):
            raise ValueError("session is outside same-source retry window")
        return asyncio.run(self._fetch(session, symbols))

    def _check_account(self, client: Any) -> None:
        accounts = tuple(client.managedAccounts())
        check_paper_account(accounts)
        if accounts != (self.settings.ibkr_account_id,):
            raise ValueError("Gateway must expose exactly the configured account")

    async def _fetch(self, session: date, symbols: tuple[str, ...]) -> tuple[OperationalBar, ...]:
        client = self.client_factory()
        try:
            await client.connectAsync(
                self.host,
                self.port,
                clientId=self.client_id,
                readonly=True,
                timeout=15,
            )
            rounds: list[dict[str, dict[date, tuple[Any, datetime]]]] = []
            for round_index in range(2):
                response: dict[str, dict[date, tuple[Any, datetime]]] = {}
                for symbol_index, symbol in enumerate(symbols):
                    if round_index or symbol_index:
                        await self.sleep(MIN_REQUEST_SPACING_SECONDS)
                    self._check_account(client)
                    qualified = await client.qualifyContractsAsync(to_asx_stock_contract(symbol))
                    if len(qualified) != 1:
                        raise ValueError(f"{symbol}: expected one qualified ASX contract")
                    self._check_account(client)
                    rows = await client.reqHistoricalDataAsync(
                        qualified[0],
                        endDateTime="",
                        # Fetch beyond the three-year decision window so the
                        # first required calendar session survives IBKR's
                        # rolling end-time boundary.
                        durationStr="4 Y",
                        barSizeSetting="1 day",
                        whatToShow="TRADES",
                        useRTH=False,
                        formatDate=1,
                        keepUpToDate=False,
                        timeout=self.settings.ibkr_call_timeout_seconds,
                    )
                    by_date: dict[date, tuple[Any, datetime]] = {}
                    for row in rows:
                        bar_session = self._session_date(row.date)
                        if bar_session > session:
                            continue
                        if bar_session in by_date:
                            raise ValueError(f"{symbol}: duplicate session bars")
                        retrieved_at = self._audit_row(symbol, bar_session, round_index, row)
                        by_date[bar_session] = (row, retrieved_at)
                    response[symbol] = by_date
                rounds.append(response)
            result: list[OperationalBar] = []
            backfill: list[OperationalBar] = []
            for symbol in symbols:
                for bar_session, (row, retrieved_at) in sorted(rounds[1][symbol].items()):
                    if self._halt_placeholder(symbol, bar_session, row):
                        continue
                    previous = rounds[0][symbol].get(bar_session)
                    stable = previous is not None and self._identity(previous[0]) == self._identity(
                        row
                    )
                    if bar_session == session:
                        stable = stable and self.now().astimezone(SYDNEY) >= datetime.combine(
                            session, time(17), SYDNEY
                        )
                    bar = self._convert(symbol, bar_session, session, row, retrieved_at, stable)
                    if bar_session == session:
                        result.append(bar)
                    else:
                        backfill.append(bar)
            self.backfill = tuple(backfill)
            return tuple(result)
        finally:
            client.disconnect()

    @staticmethod
    def _session_date(value: object) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value[:10])
        raise ValueError("unrecognised IBKR history date")

    @staticmethod
    def _identity(row: Any) -> tuple[object, ...]:
        return tuple(getattr(row, name) for name in ("open", "high", "low", "close", "volume"))

    def _audit_row(self, symbol: str, session: date, round_index: int, row: Any) -> datetime:
        fields = ("open", "high", "low", "close", "volume")
        retrieved_at = self.now().astimezone(SYDNEY)
        self.audit(
            {
                "kind": "ibkr_history_observation",
                "symbol": symbol,
                "session": session.isoformat(),
                "round": round_index + 1,
                "retrieved_at": retrieved_at.isoformat(),
                "series": "TRADES",
                "use_rth": False,
                "float_repr": {name: repr(getattr(row, name)) for name in fields},
                "float_hex": {
                    name: value.hex()
                    for name in fields
                    if isinstance(value := getattr(row, name), float)
                },
            }
        )
        return retrieved_at

    def _halt_placeholder(self, symbol: str, session: date, row: Any) -> bool:
        if float(row.volume) != 0:
            return False
        if getattr(row, "barCount", None) == 0 and self.halts.covers(symbol, session):
            self.audit(
                {
                    "kind": "documented_halt_placeholder",
                    "symbol": symbol,
                    "session": session.isoformat(),
                }
            )
            return True
        raise ValueError(f"{symbol}: zero-volume bar not in halt ledger")

    def _convert(
        self,
        symbol: str,
        bar_session: date,
        decision_session: date,
        row: Any,
        retrieved_at: datetime,
        stable: bool,
    ) -> OperationalBar:
        if not self.actions.coverage_start <= bar_session <= self.actions.coverage_end:
            raise ValueError("corporate action authority does not cover session")
        factor_value = Fraction(1)
        for event in self.actions.events:
            if event.symbol == symbol and bar_session < event.ex_session <= decision_session:
                factor_value *= Fraction(event.split_ratio.numerator, event.split_ratio.denominator)
        factor = SplitFactor(factor_value.numerator, factor_value.denominator)
        prices = []
        for name in ("open", "high", "low", "close"):
            value = getattr(row, name)
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("IBKR OHLC must be finite floats")
            price = Decimal(repr(value))
            if price <= 0 or (
                factor == SplitFactor(1, 1) and price % (tick_size(price, "ASX") / 2) != 0
            ):
                raise ValueError(f"{symbol}: OHLC outside ASX half-step grid")
            prices.append(price)
        volume = row.volume
        if isinstance(volume, bool) or not isinstance(volume, (float, int)):
            raise ValueError("IBKR requires integer volume")
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError("IBKR requires positive integer volume")
        if factor == SplitFactor(1, 1) and volume != int(volume):
            raise ValueError("IBKR requires integer volume")
        analytical_volume = Decimal(repr(volume))
        if factor == SplitFactor(1, 1):
            raw: Ohlcv = Ohlcv(prices[0], prices[1], prices[2], prices[3], int(volume))
            analytical: Ohlcv | OperationalAnalyticalOhlcv = raw
        else:
            analytical = OperationalAnalyticalOhlcv(
                prices[0], prices[1], prices[2], prices[3], analytical_volume
            )
            raw = _derived_raw(analytical, factor)
        ex_action = next(
            (
                event
                for event in self.actions.events
                if event.symbol == symbol and event.ex_session == bar_session
            ),
            None,
        )
        bar = OperationalBar(
            symbol=symbol,
            session=bar_session,
            raw=raw,
            analytical=analytical,
            factor=factor,
            split_ratio=ex_action.split_ratio if ex_action else SplitFactor(1, 1),
            dividend=ex_action.dividend if ex_action else Decimal(0),
            actions_verified=True,
            source="IBKR",
            retrieved_at=retrieved_at,
            retrieval_timezone="Australia/Sydney",
            finalised=stable,
            raw_provenance="DERIVED" if factor != SplitFactor(1, 1) else "AS_TRADED",
        )
        return bar


class IBKRRawBarProbe:
    """Read-only observation path when ASX authorities are not yet supplied.

    It records IBKR responses but cannot return an OperationalBar or card.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        audit: Callable[[dict[str, object]], None],
        client_factory: Callable[[], Any] = _default_client,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if settings.market != "ASX" or settings.is_live or not settings.ibkr_account_id:
            raise ValueError("raw history probe requires configured ASX paper account")
        host, port, client_id = connection_target(settings)
        if host not in {"127.0.0.1", "localhost", "::1"} or port not in {4002, 7497}:
            raise ValueError("raw history probe requires local paper Gateway or TWS")
        self.settings = settings
        self.audit = audit
        self.client_factory = client_factory
        self.now = now or (lambda: datetime.now(SYDNEY))
        self.sleep = sleep or asyncio.sleep
        self.host, self.port, self.client_id = host, port, client_id

    def _check_account(self, client: Any) -> None:
        accounts = tuple(client.managedAccounts())
        check_paper_account(accounts)
        if accounts != (self.settings.ibkr_account_id,):
            raise ValueError("Gateway must expose exactly the configured account")

    @staticmethod
    def _session_date(value: object) -> date:
        return IBKRHistoricalBarSource._session_date(value)

    @staticmethod
    def _identity(row: Any) -> tuple[object, ...]:
        return IBKRHistoricalBarSource._identity(row)

    def _audit_row(self, symbol: str, session: date, round_index: int, row: Any) -> None:
        fields = ("open", "high", "low", "close", "volume")
        retrieved_at = self.now().astimezone(SYDNEY)
        self.audit(
            {
                "kind": "ibkr_history_observation",
                "symbol": symbol,
                "session": session.isoformat(),
                "round": round_index + 1,
                "retrieved_at": retrieved_at.isoformat(),
                "series": "TRADES",
                "use_rth": False,
                "float_repr": {name: repr(getattr(row, name)) for name in fields},
                "float_hex": {
                    name: value.hex()
                    for name in fields
                    if isinstance(value := getattr(row, name), float)
                },
            }
        )

    def fetch(self, session: date, symbols: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        if (
            not symbols
            or len(set(symbols)) != len(symbols)
            or any(not symbol.endswith(".AX") for symbol in symbols)
        ):
            raise ValueError("unique ASX symbols required")
        observed = self.now().astimezone(SYDNEY)
        if observed.date() != session or observed >= datetime.combine(session, time(20), SYDNEY):
            raise ValueError("session is outside same-source retry window")
        return asyncio.run(self._fetch_raw(session, symbols))

    async def _fetch_raw(
        self, session: date, symbols: tuple[str, ...]
    ) -> tuple[dict[str, object], ...]:
        client = self.client_factory()
        try:
            await client.connectAsync(
                self.host, self.port, clientId=self.client_id, readonly=True, timeout=15
            )
            rounds: list[dict[str, dict[date, Any]]] = []
            for round_index in range(2):
                response: dict[str, dict[date, Any]] = {}
                for symbol_index, symbol in enumerate(symbols):
                    if round_index or symbol_index:
                        await self.sleep(MIN_REQUEST_SPACING_SECONDS)
                    self._check_account(client)
                    qualified = await client.qualifyContractsAsync(to_asx_stock_contract(symbol))
                    if len(qualified) != 1:
                        raise ValueError(f"{symbol}: expected one qualified ASX contract")
                    self._check_account(client)
                    rows = await client.reqHistoricalDataAsync(
                        qualified[0],
                        endDateTime="",
                        durationStr="3 Y",
                        barSizeSetting="1 day",
                        whatToShow="TRADES",
                        useRTH=False,
                        formatDate=1,
                        keepUpToDate=False,
                        timeout=self.settings.ibkr_call_timeout_seconds,
                    )
                    by_date: dict[date, Any] = {}
                    for row in rows:
                        bar_session = self._session_date(row.date)
                        if bar_session > session:
                            continue
                        if bar_session in by_date:
                            raise ValueError(f"{symbol}: duplicate session bars")
                        self._audit_row(symbol, bar_session, round_index, row)
                        by_date[bar_session] = row
                    response[symbol] = by_date
                rounds.append(response)
            result: list[dict[str, object]] = []
            for symbol in symbols:
                row = rounds[1][symbol].get(session)
                if row is None:
                    continue
                prior = rounds[0][symbol].get(session)
                stable = (
                    prior is not None
                    and self._identity(prior) == self._identity(row)
                    and self.now().astimezone(SYDNEY) >= datetime.combine(session, time(17), SYDNEY)
                )
                result.append(
                    {
                        "symbol": symbol,
                        "session": session.isoformat(),
                        "close": repr(row.close),
                        "volume": repr(row.volume),
                        "stable": stable,
                    }
                )
            return tuple(result)
        finally:
            client.disconnect()
