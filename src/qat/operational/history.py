"""Versioned operational authorities, append-only bars, and offline source ports.

No vendor client lives here. The writer must explicitly select an OPERATIONAL
root outside the repository and name all protected evidence roots.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from qat.data.broker.ticks import tick_size
from qat.domain.market_calendar import is_trading_day
from qat.domain.strategies.authoritative_swing.evidence import canonical_payload
from qat.domain.strategies.authoritative_swing.model import Ohlcv
from qat.domain.strategies.authoritative_swing.numeric import (
    SplitFactor,
    parse_decimal,
    to_analytical_price,
)

OPERATIONAL = "OPERATIONAL"
SYDNEY = ZoneInfo("Australia/Sydney")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_payload(value)).hexdigest()


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("expected JSON object")
    return dict(value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected nonempty text")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("expected integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("expected boolean")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("expected array")
    return value


def _decimal(value: object) -> Decimal:
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError("expected exact decimal")
    return parse_decimal(value)


def _timestamp(value: object) -> datetime:
    result = datetime.fromisoformat(_text(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return result


def _read(path: Path) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return _object(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique))


@dataclass(frozen=True, slots=True)
class Session:
    session: date
    open: datetime


@dataclass(frozen=True, slots=True)
class Closure:
    session: date
    notice: str


@dataclass(frozen=True, slots=True)
class CalendarLedger:
    schema: str
    version: int
    published_on: date
    coverage_start: date
    coverage_end: date
    source: str
    fixture: bool
    sessions: tuple[Session, ...]
    closures: tuple[Closure, ...]

    def __post_init__(self) -> None:
        dates = tuple(s.session for s in self.sessions)
        if (
            not self.source.startswith("https://www.asx.com.au/")
            or self.schema != "asx-calendar-v1"
            or self.version < 1
            or not dates
            or self.coverage_start > self.coverage_end
            or dates != tuple(sorted(set(dates)))
            or any(not self.coverage_start <= d <= self.coverage_end for d in dates)
        ):
            raise ValueError("invalid calendar schema, coverage, or ordered sessions")
        for s in self.sessions:
            if s.open.tzinfo is None or s.open.astimezone(SYDNEY).date() != s.session:
                raise ValueError("open must be a timezone-aware Sydney session timestamp")
        closure_dates = tuple(c.session for c in self.closures)
        if len(set(closure_dates)) != len(closure_dates):
            raise ValueError("duplicate closure")
        for c in self.closures:
            if (
                not c.notice.startswith("https://www.asx.com.au/")
                or c.session in dates
                or not self.coverage_start <= c.session <= self.coverage_end
            ):
                raise ValueError("closures require an ASX notice and no trading session")

    @property
    def content_hash(self) -> str:
        return digest(self)

    def next_open(self, session: date) -> datetime:
        if session not in {s.session for s in self.sessions}:
            raise ValueError("unknown ASX session")
        for s in self.sessions:
            if s.session > session:
                return s.open
        raise ValueError("calendar does not cover next ASX open")

    def conflicts(self, start: date, end: date) -> bool:
        official = {s.session for s in self.sessions}
        notices = {c.session for c in self.closures}
        day = start
        while day <= end:
            # A cited ad hoc closure amends the published calendar, rather than
            # silently letting the rule-based cross-check overrule ASX.
            if day not in notices and (day in official) != is_trading_day("ASX", day):
                return True
            day += timedelta(days=1)
        return False


@dataclass(frozen=True, slots=True)
class Membership:
    schema: str
    version: int
    published_on: date
    effective_from: date
    effective_to: date
    source: str
    fixture: bool
    symbols: tuple[str, ...]
    managed_symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.schema != "asx200-membership-v1"
            or self.version < 1
            or self.published_on > self.effective_from
            or self.effective_from > self.effective_to
            or not self.source.startswith("https://www.spglobal.com/")
            or not self.symbols
        ):
            raise ValueError("invalid dated membership authority")
        for symbols in (self.symbols, self.managed_symbols):
            if symbols != tuple(sorted(set(symbols))) or any(
                not s.endswith(".AX") for s in symbols
            ):
                raise ValueError("membership symbols must be sorted, unique ASX symbols")

    @property
    def content_hash(self) -> str:
        return digest(self)


def load_calendar(path: Path) -> CalendarLedger:
    obj = _read(path)
    return CalendarLedger(
        _text(obj["schema"]),
        _integer(obj["version"]),
        date.fromisoformat(_text(obj["published_on"])),
        date.fromisoformat(_text(obj["coverage_start"])),
        date.fromisoformat(_text(obj["coverage_end"])),
        _text(obj["source"]),
        _boolean(obj["fixture"]),
        tuple(
            Session(date.fromisoformat(_text(s["session"])), _timestamp(s["open"]))
            for s in map(_object, _list(obj["sessions"]))
        ),
        tuple(
            Closure(date.fromisoformat(_text(s["session"])), _text(s["notice"]))
            for s in map(_object, _list(obj["closures"]))
        ),
    )


def load_membership(path: Path) -> Membership:
    obj = _read(path)
    return Membership(
        _text(obj["schema"]),
        _integer(obj["version"]),
        date.fromisoformat(_text(obj["published_on"])),
        date.fromisoformat(_text(obj["effective_from"])),
        date.fromisoformat(_text(obj["effective_to"])),
        _text(obj["source"]),
        _boolean(obj["fixture"]),
        tuple(_text(s) for s in _list(obj["symbols"])),
        tuple(_text(s) for s in _list(obj["managed_symbols"])),
    )


@dataclass(frozen=True, slots=True)
class OperationalBar:
    symbol: str
    session: date
    raw: Ohlcv
    analytical: Ohlcv
    factor: SplitFactor
    split_ratio: SplitFactor
    dividend: Decimal
    actions_verified: bool
    source: str
    retrieved_at: datetime
    retrieval_timezone: str
    finalised: bool
    exchange: str = "ASX"
    currency: str = "AUD"

    def __post_init__(self) -> None:
        if (
            not self.symbol
            or self.retrieved_at.tzinfo is None
            or self.retrieved_at.utcoffset() is None
        ):
            raise ValueError("bar needs a symbol and aware retrieval timestamp")
        zone = ZoneInfo(self.retrieval_timezone)
        if self.retrieved_at.utcoffset() != self.retrieved_at.astimezone(zone).utcoffset():
            raise ValueError("retrieval offset disagrees with retrieval timezone")
        # Also rejects binary floats, NaN and infinity, before hashing/persistence.
        for prices in (self.raw, self.analytical):
            for value in (prices.open, prices.high, prices.low, prices.close):
                if not isinstance(value, Decimal) or not value.is_finite():
                    raise ValueError("OHLC must be finite Decimal")
            _integer(prices.volume)
        if not isinstance(self.dividend, Decimal) or not self.dividend.is_finite():
            raise ValueError("dividend must be finite Decimal")
        for flag in (self.actions_verified, self.finalised):
            _boolean(flag)


def parse_bar(obj: Mapping[str, object]) -> OperationalBar:
    def prices(value: object) -> Ohlcv:
        p = _object(value)
        return Ohlcv(
            _decimal(p["open"]),
            _decimal(p["high"]),
            _decimal(p["low"]),
            _decimal(p["close"]),
            _integer(p["volume"]),
        )

    def factor(value: object) -> SplitFactor:
        f = _list(value)
        if len(f) != 2:
            raise ValueError("factor requires numerator and denominator")
        return SplitFactor(_integer(f[0]), _integer(f[1]))

    return OperationalBar(
        _text(obj["symbol"]),
        date.fromisoformat(_text(obj["session"])),
        prices(obj["raw"]),
        prices(obj["analytical"]),
        factor(obj["factor"]),
        factor(obj["split_ratio"]),
        _decimal(obj["dividend"]),
        _boolean(obj["actions_verified"]),
        _text(obj["source"]),
        _timestamp(obj["retrieved_at"]),
        _text(obj["retrieval_timezone"]),
        _boolean(obj["finalised"]),
        _text(obj["exchange"]),
        _text(obj["currency"]),
    )


def _bar_payload(bar: OperationalBar) -> bytes:
    # A rational serializes explicitly; the engine's dataclass canonicalizer
    # covers the rest without introducing binary floats.
    return canonical_payload(
        {
            "symbol": bar.symbol,
            "session": bar.session,
            "raw": bar.raw,
            "analytical": bar.analytical,
            "factor": [bar.factor.numerator, bar.factor.denominator],
            "split_ratio": [bar.split_ratio.numerator, bar.split_ratio.denominator],
            "dividend": bar.dividend,
            "actions_verified": bar.actions_verified,
            "source": bar.source,
            "retrieved_at": bar.retrieved_at,
            "retrieval_timezone": bar.retrieval_timezone,
            "finalised": bar.finalised,
            "exchange": bar.exchange,
            "currency": bar.currency,
        }
    )


@dataclass(frozen=True, slots=True)
class BarRecord:
    bar: OperationalBar
    version: int
    content_hash: str
    accepted: bool
    received_at: datetime
    calendar_hash: str
    previous_hash: str
    label: str = OPERATIONAL


@dataclass(frozen=True, slots=True)
class QualityResult:
    symbol: str
    session: date
    eligible: bool
    new_cards_allowed: bool
    reasons: tuple[str, ...]


def _three_year_start(session: date) -> date:
    try:
        return session.replace(year=session.year - 3)
    except ValueError:
        return session.replace(year=session.year - 3, day=28)


def _bar_reasons(bar: OperationalBar) -> set[str]:
    reasons: set[str] = set()
    if bar.source != "IBKR":
        reasons.add("source_not_ibkr")
    if not bar.finalised:
        reasons.add("not_final")
    if (bar.exchange, bar.currency) != ("ASX", "AUD"):
        reasons.add("exchange_currency")
    if not bar.actions_verified:
        reasons.add("corporate_actions_unverified")
    if bar.dividend < 0:
        reasons.add("dividend_invalid")
    for prices in (bar.raw, bar.analytical):
        if (
            min(prices.open, prices.high, prices.low, prices.close) <= 0
            or prices.volume <= 0
            or prices.low > min(prices.open, prices.close)
            or prices.high < max(prices.open, prices.close)
            or prices.high < prices.low
        ):
            reasons.add("ohlcv_invalid")
    for value in (bar.raw.open, bar.raw.high, bar.raw.low, bar.raw.close):
        if value <= 0 or value % tick_size(value, "ASX") != 0:
            reasons.add("raw_tick_invalid")
    for raw, analytical in zip(
        (bar.raw.open, bar.raw.high, bar.raw.low, bar.raw.close),
        (bar.analytical.open, bar.analytical.high, bar.analytical.low, bar.analytical.close),
        strict=True,
    ):
        if raw > 0 and to_analytical_price(raw, bar.factor) != analytical:
            reasons.add("split_price_mismatch")
    # Share volume is raw, never dividend-adjusted or reconstructed.
    if bar.raw.volume != bar.analytical.volume:
        reasons.add("volume_adjustment")
    if bar.retrieved_at.astimezone(SYDNEY).date() < bar.session:
        reasons.add("retrieval_before_session")
    return reasons


_SQL = """
CREATE TABLE IF NOT EXISTS bars (
 symbol TEXT NOT NULL, session TEXT NOT NULL, version INTEGER NOT NULL,
 payload TEXT NOT NULL, hash TEXT NOT NULL, accepted INTEGER NOT NULL,
 calendar_hash TEXT NOT NULL, previous_hash TEXT NOT NULL, received_at TEXT NOT NULL,
 label TEXT NOT NULL CHECK(label='OPERATIONAL'),
 PRIMARY KEY(symbol,session,version));
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS bars_no_update BEFORE UPDATE ON bars BEGIN
 SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS bars_no_delete BEFORE DELETE ON bars BEGIN
 SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN
 SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN
 SELECT RAISE(ABORT,'append only'); END;
"""


class HistoryStore:
    def __init__(
        self, root: Path, *, repository_root: Path, protected_roots: Sequence[Path]
    ) -> None:
        resolved = root.resolve()
        forbidden = (repository_root.resolve(), *(p.resolve() for p in protected_roots))
        if (
            resolved.name != OPERATIONAL
            or any(resolved.is_relative_to(p) for p in forbidden)
            or any("research" in p.lower() or "promotion" in p.lower() for p in resolved.parts)
            or any(p.is_symlink() or p.is_junction() for p in (root, *root.parents))
            or any((p / ".git").exists() for p in resolved.parents)
        ):
            raise ValueError("operational namespace must be outside repository and evidence stores")
        marker = resolved / "namespace.json"
        self._database = resolved / "history.sqlite3"
        self._root = resolved
        if resolved.exists() and any(resolved.iterdir()):
            if (
                not marker.is_file()
                or marker.is_symlink()
                or marker.read_bytes() != canonical_payload({"namespace": OPERATIONAL, "schema": 1})
            ):
                raise ValueError("refusing foreign or unlabelled store")
        if self.database.is_symlink():
            raise ValueError("refusing linked database")
        resolved.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            with marker.open("xb") as file:
                file.write(canonical_payload({"namespace": OPERATIONAL, "schema": 1}))
        with self._connect() as conn:
            conn.executescript(_SQL)

    @property
    def database(self) -> Path:
        return self._database

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        marker = self._root / "namespace.json"
        if (
            any(p.is_symlink() or p.is_junction() for p in (self._root, *self._root.parents))
            or marker.is_symlink()
            or self.database.is_symlink()
            or not marker.is_file()
            or marker.read_bytes() != canonical_payload({"namespace": OPERATIONAL, "schema": 1})
            or (self.database.exists() and self.database.stat().st_nlink != 1)
        ):
            raise ValueError("operational namespace changed or linked evidence path")
        conn = sqlite3.connect(self.database)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _decode(row: tuple[object, ...]) -> BarRecord:
        (
            symbol,
            session,
            version,
            payload,
            content_hash,
            accepted,
            calendar_hash,
            previous_hash,
            received_at,
            label,
        ) = row
        obj = _object(json.loads(_text(payload)))
        bar = parse_bar(obj)
        record = BarRecord(
            bar,
            _integer(version),
            _text(content_hash),
            bool(accepted),
            _timestamp(received_at),
            _text(calendar_hash),
            str(previous_hash),
            _text(label),
        )
        identity = {
            "bar": obj,
            "version": record.version,
            "accepted": record.accepted,
            "received_at": record.received_at,
            "calendar_hash": record.calendar_hash,
            "previous_hash": record.previous_hash,
            "label": record.label,
        }
        if (
            digest(identity) != record.content_hash
            or symbol != bar.symbol
            or session != bar.session.isoformat()
            or record.label != OPERATIONAL
        ):
            raise ValueError("operational record integrity failure")
        return record

    def versions(self, symbol: str, session: date) -> tuple[BarRecord, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bars WHERE symbol=? AND session=? ORDER BY version",
                (symbol, session.isoformat()),
            ).fetchall()
        result = tuple(self._decode(row) for row in rows)
        for index, record in enumerate(result):
            expected = result[index - 1].content_hash if index else ""
            if record.version != index + 1 or record.previous_hash != expected:
                raise ValueError("broken operational version chain")
        return result

    def decision_bars(self, symbol: str, session: date) -> tuple[BarRecord, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bars WHERE symbol=? AND session<=? ORDER BY session,version",
                (symbol, session.isoformat()),
            ).fetchall()
        selected: dict[date, BarRecord] = {}
        previous: dict[date, BarRecord] = {}
        for row in rows:
            record = self._decode(row)
            day = record.bar.session
            prior = previous.get(day)
            if record.version != (prior.version + 1 if prior else 1) or record.previous_hash != (
                prior.content_hash if prior else ""
            ):
                raise ValueError("broken operational version chain")
            previous[day] = record
            if record.accepted:
                selected[day] = record
        return tuple(selected.values())

    def log(self, event: object) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit(payload) VALUES(?)", (canonical_payload(event).decode(),)
            )

    def audit_bytes(self) -> bytes:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM audit ORDER BY id").fetchall()
        return b"\n".join(row[0].encode() for row in rows)

    def ingest(
        self, bars: Sequence[OperationalBar], calendar: CalendarLedger, *, received_at: datetime
    ) -> tuple[BarRecord, ...]:
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("receipt timestamp must be timezone-aware")
        if any(b.retrieved_at > received_at for b in bars):
            raise ValueError("receipt cannot precede retrieval")
        result = []
        calendar_hash = calendar.content_hash
        calendar_sessions = {s.session for s in calendar.sessions}
        seen: set[tuple[str, date]] = set()
        previous: dict[str, date] = {}
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for bar in bars:
                key = (bar.symbol, bar.session)
                reasons = []
                if key in seen:
                    reasons.append("duplicates")
                if bar.symbol in previous and bar.session < previous[bar.symbol]:
                    reasons.append("ordering")
                if bar.session not in calendar_sessions:
                    reasons.append("unexpected_session")
                seen.add(key)
                previous[bar.symbol] = bar.session
                if reasons:
                    conn.execute(
                        "INSERT INTO audit(payload) VALUES(?)",
                        (
                            canonical_payload(
                                {"kind": "ingest_block", "symbol": bar.symbol, "reasons": reasons}
                            ).decode(),
                        ),
                    )
                rows = conn.execute(
                    "SELECT * FROM bars WHERE symbol=? AND session=? ORDER BY version",
                    (bar.symbol, bar.session.isoformat()),
                ).fetchall()
                versions = tuple(self._decode(row) for row in rows)
                version = len(versions) + 1
                accepted = not versions or received_at <= calendar.next_open(bar.session)
                payload = _bar_payload(bar).decode()
                previous_hash = versions[-1].content_hash if versions else ""
                identity = {
                    "bar": json.loads(payload),
                    "version": version,
                    "accepted": accepted,
                    "received_at": received_at,
                    "calendar_hash": calendar_hash,
                    "previous_hash": previous_hash,
                    "label": OPERATIONAL,
                }
                content_hash = digest(identity)
                conn.execute(
                    "INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        bar.symbol,
                        bar.session.isoformat(),
                        version,
                        payload,
                        content_hash,
                        int(accepted),
                        calendar_hash,
                        previous_hash,
                        received_at.isoformat(),
                        OPERATIONAL,
                    ),
                )
                if not accepted:
                    conn.execute(
                        "INSERT INTO audit(payload) VALUES(?)",
                        (
                            canonical_payload(
                                {
                                    "kind": "late_correction",
                                    "symbol": bar.symbol,
                                    "session": bar.session,
                                    "version": version,
                                    "hash": content_hash,
                                }
                            ).decode(),
                        ),
                    )
                result.append(
                    BarRecord(
                        bar,
                        version,
                        content_hash,
                        accepted,
                        received_at,
                        calendar_hash,
                        previous_hash,
                    )
                )
        return tuple(result)

    def check(
        self, symbol: str, session: date, calendar: CalendarLedger, membership: Membership
    ) -> QualityResult:
        reasons: set[str] = set()
        start = _three_year_start(session)
        current = (
            membership.effective_from <= session <= membership.effective_to
            and symbol in membership.symbols
        )
        managed = symbol in membership.managed_symbols
        if not current and not managed:
            reasons.add("not_member_or_managed")
        if not membership.effective_from <= session <= membership.effective_to:
            reasons.add("membership_stale")
        if calendar.coverage_start > start or calendar.coverage_end < session:
            reasons.add("calendar_coverage")
        if calendar.conflicts(start, session):
            reasons.add("calendar_conflict")
        records = self.decision_bars(symbol, session)
        dates = {r.bar.session for r in records}
        expected = {s.session for s in calendar.sessions if start <= s.session <= session}
        if not records or not expected or records[0].bar.session > min(expected):
            reasons.add("three_year_history")
        if not records or records[-1].bar.session != session:
            reasons.add("stale_last_session")
        if expected - dates:
            reasons.add("gaps")
        if dates - {s.session for s in calendar.sessions}:
            reasons.add("unexpected_session")
        for record in records:
            reasons.update(_bar_reasons(record.bar))
        for left, right in zip(records, records[1:], strict=False):
            a, b = left.bar, right.bar
            # Raw-to-common-basis factors must change only by the declared
            # ex-session split ratio. Dividends never alter these factors.
            if (
                a.factor.numerator * b.factor.denominator * b.split_ratio.denominator
                != b.factor.numerator * a.factor.denominator * b.split_ratio.numerator
            ):
                reasons.add("split_continuity")
        with self._connect() as conn:
            events = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM audit")]
        for event in events:
            if event.get("kind") == "ingest_block" and event.get("symbol") == symbol:
                reasons.update(event["reasons"])
        result = QualityResult(symbol, session, not reasons, current, tuple(sorted(reasons)))
        self.log(
            {
                "kind": "quality",
                "result": result,
                "calendar_hash": calendar.content_hash,
                "membership_hash": membership.content_hash,
            }
        )
        return result


class IBKRBarSource(Protocol):
    def fetch(self, session: date, symbols: tuple[str, ...]) -> tuple[OperationalBar, ...]: ...


class YahooCrossCheck(Protocol):
    def compare(self, bars: tuple[OperationalBar, ...]) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class FakeIBKRSource:
    bars: tuple[OperationalBar, ...]
    failure: str | None = None

    def fetch(self, session: date, symbols: tuple[str, ...]) -> tuple[OperationalBar, ...]:
        if self.failure is not None:
            raise ValueError(self.failure)
        return tuple(b for b in self.bars if b.session == session and b.symbol in symbols)


@dataclass(frozen=True, slots=True)
class IngestResult:
    abstained: bool
    reasons: tuple[str, ...]


def ingest_session(
    store: HistoryStore,
    calendar: CalendarLedger,
    session: date,
    symbols: tuple[str, ...],
    source: IBKRBarSource,
    cross_check: YahooCrossCheck | None = None,
    *,
    received_at: datetime,
) -> IngestResult:
    try:
        bars = source.fetch(session, symbols)
        if (
            len(bars) != len(symbols)
            or {b.symbol for b in bars} != set(symbols)
            or any(b.session != session or b.source != "IBKR" or not b.finalised for b in bars)
        ):
            raise ValueError("missing, wrong-source, or unfinished required bars")
        store.ingest(bars, calendar, received_at=received_at)
    except Exception as error:
        result = IngestResult(True, (f"ibkr_source_failure:{error}",))
        store.log({"kind": "source_failure", "session": session, "result": result})
        return result
    if cross_check is not None:
        try:
            notes = cross_check.compare(bars)
        except Exception as error:
            notes = (f"yahoo_cross_check_failure:{error}",)
        store.log({"kind": "yahoo_cross_check", "session": session, "notes": notes})
    store.log({"kind": "source_success", "session": session})
    return IngestResult(False, ())
