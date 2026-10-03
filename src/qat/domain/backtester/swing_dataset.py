"""Signed, partition-scoped historical inputs for the authoritative swing replay.

The public catalog contains identities and hashes, never sealed observations.
Only a caller-supplied shard capability may be opened by ``load_swing_dataset``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from qat.domain.backtester.swing_events import (
    CashDividendEvent,
    DelistingEvent,
    SplitEvent,
    SuspensionEvent,
    SwingMarketEvent,
    SymbolChangeEvent,
)
from qat.domain.market_calendar import is_trading_day
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    FinalBar,
    Ohlcv,
)
from qat.domain.strategies.authoritative_swing.numeric import (
    SplitFactor,
    normalize_reconstructed_raw,
    to_raw_price,
)


class DatasetIntegrityError(ValueError):
    """A signed data contract or authorized shard failed closed."""


class DatasetTier(StrEnum):
    ENGINEERING_SYNTHETIC = "engineering_synthetic"
    ENGINEERING_STATIC = "engineering_static"
    PROMOTION_POINT_IN_TIME = "promotion_point_in_time"


class EngineeringMode(StrEnum):
    STRICT_AUTHORITATIVE = "strict_authoritative"
    MECHANICAL_DIAGNOSTIC = "mechanical_diagnostic"


class SessionKind(StrEnum):
    FULL = "FULL"
    SHORTENED = "SHORTENED"
    AD_HOC_CLOSED = "AD_HOC_CLOSED"
    SCHEDULED_CLOSED = "SCHEDULED_CLOSED"
    WEEKEND = "WEEKEND"


TRADABLE_KINDS = frozenset({SessionKind.FULL, SessionKind.SHORTENED})
SCHEMA_VERSION = "phase2-swing-dataset-v1"
DAILY_COLUMNS = frozenset({
    "session", "raw_open", "raw_high", "raw_low", "raw_close", "raw_volume",
    "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close",
    "adjusted_volume", "split_factor_numerator", "split_factor_denominator",
    "source", "quality", "finalized",
})
CALENDAR_COLUMNS = frozenset({
    "calendar_date", "session_kind", "open_time", "close_time", "source",
    "source_version", "source_notice", "reason", "retrieved_at", "source_hash",
    "finalized",
})
CORPORATE_COLUMNS = frozenset({
    "event_id", "symbol", "declaration_date", "ex_session", "record_date",
    "payment_date", "kind", "ratio_numerator", "ratio_denominator",
    "cash_amount", "new_symbol", "terminal_price", "currency",
})
REGIME_COLUMNS = frozenset({
    "session", "label", "probabilities_json", "model_version", "model_code_hash",
    "configuration_hash", "training_start", "training_end", "input_cutoff",
    "max_input_session", "input_hash", "fit_id", "output_hash",
})
EXPECTED_COLUMNS = {
    "sessions.csv": CALENDAR_COLUMNS,
    "membership.csv": frozenset({"session", "symbol", "is_member"}),
    "corporate_actions.csv": CORPORATE_COLUMNS,
    "regimes.csv": REGIME_COLUMNS,
    "benchmark.csv": DAILY_COLUMNS,
}


@dataclass(frozen=True, slots=True)
class OfficialCalendarRow:
    calendar_date: date
    session_kind: SessionKind
    open_time: time | None
    close_time: time | None
    source: str
    source_version: str
    source_notice: str | None
    reason: str
    retrieved_at: datetime
    source_hash: str
    finalized: bool

    @property
    def is_tradable(self) -> bool:
        return self.session_kind in TRADABLE_KINDS


@dataclass(frozen=True, slots=True)
class OfficialSessionCalendar:
    rows: tuple[OfficialCalendarRow, ...]
    official_sessions: tuple[date, ...]
    source_hash: str

    def row(self, day: date) -> OfficialCalendarRow:
        for row in self.rows:
            if row.calendar_date == day:
                return row
        raise KeyError(day)


@dataclass(frozen=True, slots=True)
class DatasetShardManifest:
    shard_id: str
    partition: str
    first_session: date
    last_session: date
    files_sha256: Mapping[str, str]
    merkle_root: str
    shard_kind: str
    signal_months: tuple[str, ...]
    boundary_ids: Mapping[str, date]

    def __post_init__(self) -> None:
        object.__setattr__(self, "files_sha256", MappingProxyType(dict(self.files_sha256)))
        object.__setattr__(self, "boundary_ids", MappingProxyType(dict(self.boundary_ids)))


@dataclass(frozen=True, slots=True)
class DatasetCatalog:
    schema_version: str
    dataset_id: str
    tier: DatasetTier
    source: str
    adjustment_policy: str
    currency: str
    first_session: date
    last_session: date
    point_in_time_membership: bool
    benchmark_kind: str
    coverage_limit_reason: str | None
    shards: Mapping[str, DatasetShardManifest]
    operator_signature: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "shards", MappingProxyType(dict(self.shards)))


@dataclass(frozen=True, slots=True)
class PartitionAccess:
    """The only filesystem capability presented to the observation loader."""

    catalog_path: Path
    shard_id: str
    shard_root: Path
    verification_key: bytes
    authorized_tail_id: str | None = None


@dataclass(frozen=True, slots=True)
class PointInTimeRegime:
    session: date
    label: str
    probabilities: Mapping[str, Decimal]
    model_version: str
    model_code_hash: str
    configuration_hash: str
    training_start: date
    training_end: date
    input_cutoff: date
    max_input_session: date
    input_hash: str
    fit_id: str
    output_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "probabilities", MappingProxyType(dict(self.probabilities)))


@dataclass(frozen=True, slots=True)
class RegimeAuditResult:
    checked_input_count: int
    sampled_sessions: tuple[date, ...]
    failed_input_sessions: tuple[date, ...]
    failed_output_sessions: tuple[date, ...]
    unknown_model_versions: frozenset[str]


@dataclass(frozen=True, slots=True)
class SwingDataset:
    catalog: DatasetCatalog
    manifest: DatasetShardManifest
    official_calendar: OfficialSessionCalendar
    official_sessions: tuple[date, ...]
    bars: Mapping[str, tuple[FinalBar, ...]]
    membership: Mapping[date, frozenset[str]]
    corporate_actions: tuple[SwingMarketEvent, ...]
    benchmark: tuple[FinalBar, ...]
    regimes: Mapping[date, PointInTimeRegime]
    authorized_tail: DatasetShardManifest | None
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", MappingProxyType(dict(self.bars)))
        object.__setattr__(self, "membership", MappingProxyType(dict(self.membership)))
        object.__setattr__(self, "regimes", MappingProxyType(dict(self.regimes)))

    def members(self, session: date | str) -> frozenset[str]:
        day = date.fromisoformat(session) if isinstance(session, str) else session
        return self.membership.get(day, frozenset())


def select_regime_audit_sessions(
    regimes: Mapping[date, PointInTimeRegime],
) -> tuple[date, ...]:
    """Deterministic sample: >=1%, >=100/version, each year and transition."""

    by_version: dict[str, list[PointInTimeRegime]] = defaultdict(list)
    for regime in regimes.values():
        by_version[regime.model_version].append(regime)
    selected: set[date] = set()
    for records in by_version.values():
        ordered = sorted(records, key=lambda row: row.session)
        target = min(len(ordered), max(100, (len(ordered) + 99) // 100))
        if target == 1:
            selected.add(ordered[0].session)
        else:
            selected.update(
                ordered[index * (len(ordered) - 1) // (target - 1)].session
                for index in range(target)
            )
        seen_years: set[int] = set()
        previous: PointInTimeRegime | None = None
        for row in ordered:
            if row.session.year not in seen_years:
                selected.add(row.session)
                seen_years.add(row.session.year)
            if previous is not None and previous.label != row.label:
                selected.add(row.session)
            previous = row
    return tuple(sorted(selected))


def audit_regime_provenance(
    dataset: SwingDataset,
    digest_prefix: Callable[[date, tuple[FinalBar, ...]], str],
    recompute: Callable[
        [PointInTimeRegime, tuple[FinalBar, ...]],
        tuple[str, Mapping[str, Decimal], str],
    ],
) -> RegimeAuditResult:
    """Check every input digest and replay a frozen stratified model sample."""

    sampled = select_regime_audit_sessions(dataset.regimes)
    sample_set = set(sampled)
    failed_inputs: list[date] = []
    failed_outputs: list[date] = []
    unknown_versions: set[str] = set()
    for session, regime in sorted(dataset.regimes.items()):
        prefix = tuple(
            bar
            for symbol in sorted(dataset.bars)
            for bar in dataset.bars[symbol]
            if bar.session <= regime.max_input_session
        )
        if digest_prefix(session, prefix) != regime.input_hash:
            failed_inputs.append(session)
            unknown_versions.add(regime.model_version)
        if session in sample_set:
            label, probabilities, output_hash = recompute(regime, prefix)
            if (
                label != regime.label
                or probabilities != regime.probabilities
                or output_hash != regime.output_hash
            ):
                failed_outputs.append(session)
                unknown_versions.add(regime.model_version)
    return RegimeAuditResult(
        len(dataset.regimes),
        sampled,
        tuple(failed_inputs),
        tuple(failed_outputs),
        frozenset(unknown_versions),
    )


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetIntegrityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def shard_merkle_root(files: Mapping[str, str]) -> str:
    """Pairwise SHA-256 tree; leaves bind canonical path and content hash."""

    if not files:
        raise DatasetIntegrityError("shard Merkle tree requires at least one file")
    nodes = [
        hashlib.sha256(b"\x00" + name.encode() + b"\x00" + bytes.fromhex(digest)).digest()
        for name, digest in sorted(files.items())
    ]
    while len(nodes) > 1:
        if len(nodes) % 2:
            nodes.append(nodes[-1])
        nodes = [
            hashlib.sha256(b"\x01" + nodes[index] + nodes[index + 1]).digest()
            for index in range(0, len(nodes), 2)
        ]
    return nodes[0].hex()


def _required(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetIntegrityError(f"{label} is missing")
    return value


def _day(value: object, label: str) -> date:
    try:
        return date.fromisoformat(_required(value, label))
    except ValueError as error:
        raise DatasetIntegrityError(f"{label} is not an ISO date") from error


def _digest(value: object, label: str) -> str:
    digest = _required(value, label)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise DatasetIntegrityError(f"{label} is not a SHA-256 hex digest")
    return digest


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise DatasetIntegrityError(f"unsafe shard file path: {name}")
    return path


def validate_catalog(catalog_path: Path, verification_key: bytes) -> DatasetCatalog:
    """Verify only public metadata; this function never traverses shard paths."""

    try:
        with catalog_path.open("rb") as stream:
            raw: object = json.load(stream, object_pairs_hook=_unique_json_object)
        if not isinstance(raw, dict):
            raise DatasetIntegrityError("catalog manifest must be a JSON object")
        payload: dict[str, Any] = raw
        signature_hex = _required(payload.get("operator_signature"), "operator signature")
        try:
            signature = bytes.fromhex(signature_hex)
        except ValueError as error:
            raise DatasetIntegrityError("catalog signature is not hexadecimal") from error
        signed = {key: value for key, value in payload.items() if key != "operator_signature"}
        Ed25519PublicKey.from_public_bytes(verification_key).verify(
            signature, _canonical(signed)
        )
        dataset_id = _digest(signed.get("dataset_id"), "dataset id")
        identity = {key: value for key, value in signed.items() if key != "dataset_id"}
        if dataset_id != _sha256(_canonical(identity)):
            raise DatasetIntegrityError("catalog dataset id does not match its content hash")
        if signed.get("schema_version") != SCHEMA_VERSION:
            raise DatasetIntegrityError("unsupported catalog schema version")
        shards_raw = signed.get("shards")
        if not isinstance(shards_raw, dict) or not shards_raw:
            raise DatasetIntegrityError("catalog has no shard manifests")
        shards: dict[str, DatasetShardManifest] = {}
        for shard_id, item in shards_raw.items():
            if not isinstance(shard_id, str) or not isinstance(item, dict):
                raise DatasetIntegrityError("invalid shard manifest")
            files_raw = item.get("files_sha256")
            if not isinstance(files_raw, dict) or not files_raw:
                raise DatasetIntegrityError(f"shard {shard_id} has no file hashes")
            files = {
                _safe_relative(str(name)).as_posix(): _digest(digest, f"{shard_id} file hash")
                for name, digest in files_raw.items()
            }
            merkle_root = _digest(item.get("merkle_root"), f"{shard_id} merkle root")
            if shard_merkle_root(files) != merkle_root:
                raise DatasetIntegrityError(f"shard {shard_id} merkle root mismatch")
            first = _day(item.get("first_session"), f"{shard_id} first session")
            last = _day(item.get("last_session"), f"{shard_id} last session")
            if last < first or item.get("shard_id") != shard_id:
                raise DatasetIntegrityError(f"shard {shard_id} identity or boundary mismatch")
            boundaries = item.get("boundary_ids", {})
            if not isinstance(boundaries, dict):
                raise DatasetIntegrityError(f"shard {shard_id} boundaries are invalid")
            shards[shard_id] = DatasetShardManifest(
                shard_id,
                _required(item.get("partition"), f"{shard_id} partition"),
                first,
                last,
                files,
                merkle_root,
                _required(item.get("shard_kind"), f"{shard_id} kind"),
                tuple(str(month) for month in item.get("signal_months", ())),
                {str(name): _day(day, f"{shard_id} boundary") for name, day in boundaries.items()},
            )
        first = _day(signed.get("first_session"), "catalog first session")
        last = _day(signed.get("last_session"), "catalog last session")
        if last < first or any(
            shard.first_session < first or shard.last_session > last
            for shard in shards.values()
        ):
            raise DatasetIntegrityError("shard boundary lies outside catalog interval")
        try:
            tier = DatasetTier(_required(signed.get("tier"), "dataset tier"))
        except ValueError as error:
            raise DatasetIntegrityError("invalid dataset tier") from error
        membership_flag = signed.get("point_in_time_membership")
        if not isinstance(membership_flag, bool):
            raise DatasetIntegrityError("point-in-time membership flag is not Boolean")
        if tier is DatasetTier.PROMOTION_POINT_IN_TIME:
            if not membership_flag:
                raise DatasetIntegrityError("promotion requires point-in-time membership")
            if signed.get("adjustment_policy") != "split_only":
                raise DatasetIntegrityError("promotion requires split-only analytical prices")
            if signed.get("benchmark_kind") != "accumulation_total_return":
                raise DatasetIntegrityError("promotion requires an accumulation benchmark")
            for partition in ("development", "validation", "holdout"):
                kinds = {
                    shard.shard_kind for shard in shards.values()
                    if shard.partition == partition
                }
                if not {"signal", "tail"}.issubset(kinds):
                    raise DatasetIntegrityError(
                        f"promotion catalog lacks signal and tail shards for {partition}"
                    )
            for shard in shards.values():
                if shard.shard_kind == "tail" and not {"T1", "T64"}.issubset(
                    shard.boundary_ids
                ):
                    raise DatasetIntegrityError(
                        f"promotion tail {shard.shard_id} lacks named boundaries"
                    )
        return DatasetCatalog(
            SCHEMA_VERSION,
            dataset_id,
            tier,
            _required(signed.get("source"), "catalog source"),
            _required(signed.get("adjustment_policy"), "adjustment policy"),
            _required(signed.get("currency"), "catalog currency"),
            first,
            last,
            membership_flag,
            _required(signed.get("benchmark_kind"), "benchmark kind"),
            signed.get("coverage_limit_reason"),
            shards,
            signature_hex,
            tuple(str(item) for item in signed.get("limitations", ())),
        )
    except (OSError, json.JSONDecodeError, UnicodeError, InvalidSignature) as error:
        raise DatasetIntegrityError(
            f"catalog signature or manifest validation failed: {error}"
        ) from error


def _authorized_files(access: PartitionAccess, manifest: DatasetShardManifest) -> dict[str, bytes]:
    root = access.shard_root.resolve(strict=True)
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed != set(manifest.files_sha256):
        raise DatasetIntegrityError("authorized shard has missing or unlisted files")
    content: dict[str, bytes] = {}
    for name, expected in sorted(manifest.files_sha256.items()):
        path = (root / Path(*_safe_relative(name).parts)).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise DatasetIntegrityError(f"shard file escapes its authorized root: {name}")
        raw = path.read_bytes()
        if _sha256(raw) != expected:
            raise DatasetIntegrityError(f"shard file hash mismatch: {name}")
        content[name] = raw
    return content


def _rows(files: dict[str, bytes], name: str) -> tuple[dict[str, str], ...]:
    try:
        data = files[name].decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(data))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise DatasetIntegrityError(f"{name} has invalid columns")
        expected = DAILY_COLUMNS if name.startswith("daily/") else EXPECTED_COLUMNS.get(name)
        if name == "corporate_actions.csv" and set(reader.fieldnames) == (
            CORPORATE_COLUMNS | {"resume_session"}
        ):
            expected = CORPORATE_COLUMNS | {"resume_session"}
        if expected is None or set(reader.fieldnames) != expected:
            raise DatasetIntegrityError(f"{name} has missing or unlisted columns")
        rows = tuple(dict(row) for row in reader)
        if any(set(row) != expected or any(value is None for value in row.values())
               for row in rows):
            raise DatasetIntegrityError(f"{name} has invalid row width")
        return rows
    except (KeyError, UnicodeError, csv.Error) as error:
        raise DatasetIntegrityError(f"required shard file or CSV is invalid: {name}") from error


def _bool(value: str | None, label: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise DatasetIntegrityError(f"{label} must be true or false")


def _calendar(files: dict[str, bytes], manifest: DatasetShardManifest) -> OfficialSessionCalendar:
    calendar_rows: list[OfficialCalendarRow] = []
    for row in _rows(files, "sessions.csv"):
        day = _day(row.get("calendar_date"), "calendar row date")
        try:
            kind = SessionKind(_required(row.get("session_kind"), "session kind"))
            retrieved = datetime.fromisoformat(_required(row.get("retrieved_at"), "retrieved at"))
            open_time = time.fromisoformat(row["open_time"]) if row.get("open_time") else None
            close_time = time.fromisoformat(row["close_time"]) if row.get("close_time") else None
        except ValueError as error:
            raise DatasetIntegrityError(f"invalid calendar row on {day}") from error
        if retrieved.tzinfo is None:
            raise DatasetIntegrityError(f"calendar row {day} has no retrieval timezone")
        if kind in TRADABLE_KINDS:
            if open_time is None or close_time is None or open_time >= close_time:
                raise DatasetIntegrityError(f"tradable calendar row {day} has invalid hours")
            if kind is SessionKind.SHORTENED and (
                datetime.combine(day, close_time) - datetime.combine(day, open_time)
                >= timedelta(hours=6)
            ):
                raise DatasetIntegrityError(f"shortened calendar row {day} has full hours")
        elif open_time is not None or close_time is not None:
            raise DatasetIntegrityError(f"closed calendar row {day} has market hours")
        if kind is SessionKind.AD_HOC_CLOSED and not row.get("source_notice"):
            raise DatasetIntegrityError(f"ad hoc calendar row {day} lacks closure notice")
        calendar_rows.append(
            OfficialCalendarRow(
                day, kind, open_time, close_time,
                _required(row.get("source"), "calendar source"),
                _required(row.get("source_version"), "calendar source version"),
                row.get("source_notice") or None,
                _required(row.get("reason"), "calendar reason"),
                retrieved,
                _required(row.get("source_hash"), "calendar source hash"),
                _bool(row.get("finalized"), "calendar finalized"),
            )
        )
    dates = tuple(row.calendar_date for row in calendar_rows)
    if not dates or dates != tuple(sorted(set(dates))):
        raise DatasetIntegrityError("calendar rows are duplicated or unordered")
    expected = tuple(
        dates[0] + timedelta(days=offset)
        for offset in range((dates[-1] - dates[0]).days + 1)
    )
    if dates != expected:
        raise DatasetIntegrityError("calendar row missing for a civil date")
    official = tuple(row.calendar_date for row in calendar_rows if row.is_tradable)
    if (
        not official
        or official[0] != manifest.first_session
        or official[-1] != manifest.last_session
    ):
        raise DatasetIntegrityError("calendar official-session bounds disagree with shard")
    if not all(row.finalized for row in calendar_rows):
        raise DatasetIntegrityError("calendar contains non-finalized rows")
    source_hashes = {row.source_hash for row in calendar_rows}
    if len(source_hashes) != 1:
        raise DatasetIntegrityError("calendar source hash changes within shard")
    return OfficialSessionCalendar(tuple(calendar_rows), official, source_hashes.pop())


def _decimal(value: str | None, label: str) -> Decimal:
    try:
        parsed = Decimal(_required(value, label))
    except ValueError as error:
        raise DatasetIntegrityError(f"{label} is not an exact decimal") from error
    if not parsed.is_finite():
        raise DatasetIntegrityError(f"{label} is not finite")
    return parsed


def _int(value: str | None, label: str) -> int:
    try:
        return int(_required(value, label))
    except ValueError as error:
        raise DatasetIntegrityError(f"{label} is not an integer") from error


def _ohlcv(row: dict[str, str], prefix: str) -> Ohlcv:
    return Ohlcv(
        _decimal(row.get(f"{prefix}_open"), f"{prefix} open"),
        _decimal(row.get(f"{prefix}_high"), f"{prefix} high"),
        _decimal(row.get(f"{prefix}_low"), f"{prefix} low"),
        _decimal(row.get(f"{prefix}_close"), f"{prefix} close"),
        _int(row.get(f"{prefix}_volume"), f"{prefix} volume"),
    )


def _geometry_valid(bar: Ohlcv) -> bool:
    return (
        bar.low > 0 and bar.open > 0 and bar.close > 0
        and bar.high >= max(bar.open, bar.close)
        and bar.low <= min(bar.open, bar.close)
        and bar.volume >= 0
    )


def _bar(symbol: str, row: dict[str, str], content_hash: str) -> tuple[FinalBar, str | None]:
    session = _day(row.get("session"), f"{symbol} bar session")
    raw = _ohlcv(row, "raw")
    adjusted = _ohlcv(row, "adjusted")
    try:
        factor = SplitFactor(
            _int(row.get("split_factor_numerator"), "split numerator"),
            _int(row.get("split_factor_denominator"), "split denominator"),
        )
        quality = DataQuality(_required(row.get("quality"), "bar quality"))
    except ValueError as error:
        raise DatasetIntegrityError(f"{symbol} has invalid factor or quality") from error
    if any(
        normalize_reconstructed_raw(to_raw_price(value, factor), source) != source
        for value, source in (
            (adjusted.open, raw.open), (adjusted.high, raw.high),
            (adjusted.low, raw.low), (adjusted.close, raw.close),
        )
    ):
        raise DatasetIntegrityError(f"{symbol} adjustment lineage disagrees with raw prices")
    expected_volume = Fraction(raw.volume * factor.denominator, factor.numerator)
    if abs(Fraction(adjusted.volume) - expected_volume) > 1:
        raise DatasetIntegrityError(f"{symbol} volume lineage disagrees with split factor")
    issue = None
    if not _geometry_valid(raw) or not _geometry_valid(adjusted):
        issue = f"{symbol} {session} has malformed finite OHLC geometry"
        quality = DataQuality.UNVERIFIED
    finalized = _bool(row.get("finalized"), "bar finalized")
    if not finalized:
        issue = f"{symbol} {session} has a non-finalized bar"
        quality = DataQuality.UNVERIFIED
    return (
        FinalBar(
            symbol, session, raw, adjusted,
            _required(row.get("source"), "bar source"), quality,
            AdjustmentStatus.SPLIT_NORMALIZED, factor,
            finalized, content_hash,
        ),
        issue,
    )


def _events(files: dict[str, bytes], currency: str) -> tuple[SwingMarketEvent, ...]:
    events: list[SwingMarketEvent] = []
    identities: set[str] = set()
    for row in _rows(files, "corporate_actions.csv"):
        event_id = _required(row.get("event_id"), "corporate action event id")
        symbol = _required(row.get("symbol"), "corporate action symbol")
        if event_id in identities:
            raise DatasetIntegrityError("duplicate corporate action identity")
        identities.add(event_id)
        if row.get("currency") != currency:
            raise DatasetIntegrityError(f"corporate action {event_id} currency mismatch")
        effective = _day(row.get("ex_session"), f"{event_id} effective session")
        kind = row.get("kind")
        if kind in {"split", "consolidation"}:
            events.append(SplitEvent(event_id, symbol, effective,
                                     _int(row.get("ratio_numerator"), "split numerator"),
                                     _int(row.get("ratio_denominator"), "split denominator")))
        elif kind == "cash_dividend":
            events.append(CashDividendEvent(
                event_id, symbol, effective,
                _day(row.get("declaration_date"), "dividend declaration"), effective,
                _day(row.get("record_date"), "dividend record"),
                _day(row.get("payment_date"), "dividend payment"),
                _decimal(row.get("cash_amount"), "cash dividend"),
            ))
        elif kind == "symbol_change":
            events.append(SymbolChangeEvent(event_id, symbol, effective,
                                            _required(row.get("new_symbol"), "new symbol")))
        elif kind == "suspension":
            resume = row.get("resume_session")
            events.append(SuspensionEvent(event_id, symbol, effective,
                                          _day(resume, "resume session") if resume else None))
        elif kind == "delisting":
            events.append(DelistingEvent(event_id, symbol, effective,
                                         _decimal(row.get("terminal_price"), "terminal price")))
        else:
            raise DatasetIntegrityError(f"unknown corporate action kind: {kind}")
    return tuple(events)


def _regimes(files: dict[str, bytes], sessions: tuple[date, ...]) -> dict[date, PointInTimeRegime]:
    result: dict[date, PointInTimeRegime] = {}
    for row in _rows(files, "regimes.csv"):
        session = _day(row.get("session"), "regime session")
        if session in result:
            raise DatasetIntegrityError("duplicate regime session")
        try:
            probabilities_raw = json.loads(
                _required(row.get("probabilities_json"), "regime probabilities"),
                parse_float=Decimal,
                object_pairs_hook=_unique_json_object,
            )
        except json.JSONDecodeError as error:
            raise DatasetIntegrityError("regime probabilities JSON is invalid") from error
        if not isinstance(probabilities_raw, dict):
            raise DatasetIntegrityError("regime probabilities must be an object")
        probabilities = {
            str(label): _decimal(str(value), "regime probability")
            for label, value in probabilities_raw.items()
        }
        start = _day(row.get("training_start"), "regime training start")
        end = _day(row.get("training_end"), "regime training end")
        cutoff = _day(row.get("input_cutoff"), "regime input cutoff")
        max_input = _day(row.get("max_input_session"), "regime max input session")
        if not start <= end <= cutoff <= session or max_input > cutoff:
            raise DatasetIntegrityError("regime provenance crosses its session cutoff")
        result[session] = PointInTimeRegime(
            session, _required(row.get("label"), "regime label"), probabilities,
            _required(row.get("model_version"), "regime model version"),
            _required(row.get("model_code_hash"), "regime model code hash"),
            _required(row.get("configuration_hash"), "regime configuration hash"),
            start, end, cutoff, max_input,
            _required(row.get("input_hash"), "regime input hash"),
            _required(row.get("fit_id"), "regime fit id"),
            _required(row.get("output_hash"), "regime output hash"),
        )
    if set(result) != set(sessions):
        raise DatasetIntegrityError("regime session coverage differs from official sessions")
    return result


def load_swing_dataset(access: PartitionAccess) -> SwingDataset:
    """Verify one explicitly authorized shard and map it into Phase 2A/B records."""

    catalog = validate_catalog(access.catalog_path, access.verification_key)
    if catalog.adjustment_policy != "split_only":
        raise DatasetIntegrityError("signed shard loader requires split-only prices")
    if access.shard_id not in catalog.shards:
        raise DatasetIntegrityError("authorized shard identity is absent from catalog")
    manifest = catalog.shards[access.shard_id]
    try:
        files = _authorized_files(access, manifest)
        unknown = set(files) - set(EXPECTED_COLUMNS) - {
            name for name in files
            if name.startswith("daily/") and name.endswith(".csv")
            and len(PurePosixPath(name).parts) == 2
        }
        if unknown:
            raise DatasetIntegrityError(f"authorized shard has unknown file: {sorted(unknown)[0]}")
        calendar = _calendar(files, manifest)
        issues: list[str] = [
            f"rule-derived calendar disagrees with signed row on {row.calendar_date}"
            for row in calendar.rows
            if is_trading_day("ASX", row.calendar_date) != row.is_tradable
        ]
        sessions = set(calendar.official_sessions)
        closed = {row.calendar_date for row in calendar.rows if not row.is_tradable}
        membership: dict[date, set[str]] = {day: set() for day in calendar.official_sessions}
        seen_membership: set[tuple[date, str]] = set()
        for row in _rows(files, "membership.csv"):
            session = _day(row.get("session"), "membership session")
            symbol = _required(row.get("symbol"), "membership symbol")
            key = (session, symbol)
            if session not in sessions or key in seen_membership:
                raise DatasetIntegrityError("membership has closed, missing or duplicate session")
            seen_membership.add(key)
            if _bool(row.get("is_member"), "membership flag"):
                membership[session].add(symbol)
        bars: dict[str, tuple[FinalBar, ...]] = {}
        for name, raw in sorted(files.items()):
            if not name.startswith("daily/") or not name.endswith(".csv"):
                continue
            symbol = Path(name).stem
            if not symbol or symbol in bars:
                raise DatasetIntegrityError("duplicate or empty symbol history")
            parsed = tuple(_bar(symbol, row, _sha256(raw)) for row in _rows(files, name))
            history = tuple(bar for bar, _ in parsed)
            issues.extend(issue for _, issue in parsed if issue is not None)
            history_sessions = tuple(bar.session for bar in history)
            if history_sessions != tuple(sorted(set(history_sessions))):
                raise DatasetIntegrityError(f"{symbol} has duplicate or unordered bars")
            if any(day not in sessions for day in history_sessions):
                raise DatasetIntegrityError(f"{symbol} has a bar on a closed calendar row")
            bars[symbol] = history
        if not bars:
            raise DatasetIntegrityError("authorized shard has no symbol histories")
        benchmark = tuple(
            _bar("BENCH.AX", row, _sha256(files["benchmark.csv"]))[0]
            for row in _rows(files, "benchmark.csv")
        )
        if tuple(bar.session for bar in benchmark) != calendar.official_sessions:
            raise DatasetIntegrityError(
                "benchmark gaps or ordering disagree with official sessions"
            )
        if any(not bar.finalized for bar in benchmark):
            raise DatasetIntegrityError("benchmark includes a non-finalized bar")
        if any(not membership[day] for day in calendar.official_sessions):
            raise DatasetIntegrityError("tradable calendar row lacks point-in-time membership")
        for day, members in membership.items():
            if any(
                not any(bar.session == day for bar in bars.get(symbol, ()))
                for symbol in members
            ):
                raise DatasetIntegrityError(f"tradable calendar row {day} lacks member bars")
        events = _events(files, catalog.currency)
        if any(event.effective_session in closed or event.effective_session not in sessions
               for event in events):
            raise DatasetIntegrityError("corporate action lies outside tradable calendar rows")
        for event in events:
            if event.symbol not in bars:
                raise DatasetIntegrityError(
                    f"corporate action {event.event_id} lacks symbol history"
                )
            if isinstance(event, SymbolChangeEvent) and (
                event.new_symbol not in bars
                or bars[event.symbol][-1].session >= event.effective_session
                or bars[event.new_symbol][0].session < event.effective_session
            ):
                raise DatasetIntegrityError(
                    f"symbol change lineage is unresolved for {event.event_id}"
                )
            if isinstance(event, DelistingEvent) and any(
                bar.session >= event.effective_session for bar in bars[event.symbol]
            ):
                raise DatasetIntegrityError(
                    f"delisting {event.event_id} has a contradictory traded bar"
                )
            if isinstance(event, SuspensionEvent) and any(
                bar.session >= event.effective_session
                and (event.resume_session is None or bar.session < event.resume_session)
                for bar in bars[event.symbol]
            ):
                raise DatasetIntegrityError(
                    f"suspension {event.event_id} has a contradictory traded bar"
                )
        regimes = _regimes(files, calendar.official_sessions)
        return SwingDataset(
            catalog, manifest, calendar, calendar.official_sessions, bars,
            {day: frozenset(symbols) for day, symbols in membership.items()},
            events, benchmark, regimes,
            catalog.shards.get(access.authorized_tail_id) if access.authorized_tail_id else None,
            tuple(issues),
        )
    except (OSError, KeyError, ValueError) as error:
        if isinstance(error, DatasetIntegrityError):
            raise
        raise DatasetIntegrityError(f"authorized shard is incomplete: {error}") from error


def load_static_asx_engineering_dataset(cache_dir: Path | None = None) -> SwingDataset:
    """Read the old ASX snapshot as visibly non-promotional engineering data."""

    root = cache_dir or Path(__file__).resolve().parents[4] / "scripts" / "research" / "asx_bars"
    paths = tuple(sorted(root.glob("*.csv")))
    if not paths:
        raise DatasetIntegrityError("static ASX engineering cache is empty")
    files: dict[str, str] = {}
    bars: dict[str, tuple[FinalBar, ...]] = {}
    issues: list[str] = []
    for path in paths:
        symbol = path.stem
        raw = path.read_bytes()
        digest = _sha256(raw)
        files[path.name] = digest
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames != ["ts", "open", "high", "low", "close", "volume"]:
            raise DatasetIntegrityError(f"static ASX file {path.name} has unexpected columns")
        history: list[FinalBar] = []
        for row in reader:
            try:
                session = datetime.fromisoformat(_required(row.get("ts"), "static timestamp"))
                if session.tzinfo is None:
                    raise DatasetIntegrityError("static timestamp lacks timezone")
                price = Ohlcv(
                    _decimal(row.get("open"), "static open"),
                    _decimal(row.get("high"), "static high"),
                    _decimal(row.get("low"), "static low"),
                    _decimal(row.get("close"), "static close"),
                    _int(row.get("volume"), "static volume"),
                )
            except ValueError as error:
                raise DatasetIntegrityError(f"static ASX file {path.name} is invalid") from error
            if not _geometry_valid(price):
                issues.append(f"{symbol} {session.date()} has malformed vendor OHLC")
            history.append(
                FinalBar(
                    symbol,
                    session.date(),
                    price,
                    price,
                    "legacy-static-asx-cache",
                    DataQuality.UNVERIFIED,
                    AdjustmentStatus.VENDOR_ADJUSTED,
                    SplitFactor(1, 1),
                    True,
                    digest,
                )
            )
        sessions = tuple(bar.session for bar in history)
        if sessions != tuple(sorted(set(sessions))):
            raise DatasetIntegrityError(f"static ASX file {path.name} has unordered dates")
        bars[symbol] = tuple(history)
    official = tuple(sorted({bar.session for history in bars.values() for bar in history}))
    first, last = official[0], official[-1]
    static_hash = shard_merkle_root(files)
    calendar_rows = tuple(
        OfficialCalendarRow(
            day,
            SessionKind.FULL if day in official else (
                SessionKind.WEEKEND if day.weekday() >= 5 else SessionKind.SCHEDULED_CLOSED
            ),
            time(10) if day in official else None,
            time(16) if day in official else None,
            "derived-from-legacy-static-cache",
            "unverified-engineering",
            None,
            "observed cache date" if day in official else "no cached market row",
            datetime(1970, 1, 1, tzinfo=UTC),
            static_hash,
            True,
        )
        for day in (first + timedelta(days=offset)
                    for offset in range((last - first).days + 1))
    )
    calendar = OfficialSessionCalendar(calendar_rows, official, static_hash)
    membership = {
        day: frozenset(
            symbol for symbol, history in bars.items()
            if any(bar.session == day for bar in history)
        )
        for day in official
    }
    benchmark = bars.get("STW.AX")
    benchmark_complete = (
        benchmark is not None
        and tuple(bar.session for bar in benchmark) == official
    )
    limitations = (
        "survivorship-biased static 95-symbol snapshot; no former members or delistings",
        "raw as-traded prices absent; vendor-adjusted data cannot support authoritative fills",
        "dividend and split adjustment components cannot be separated",
        "corporate-action and terminal-outcome histories unavailable",
        "official exchange-calendar signatures and acquisition timestamps unavailable",
        "under-three-year resistance history; strict mode abstains",
        "benchmark is a vendor-adjusted price proxy, not accumulation total return",
    ) + (() if benchmark_complete else (
        "STW.AX benchmark proxy has missing sessions; no prices are carried or fabricated",
    ))
    manifest = DatasetShardManifest(
        "static-asx", "engineering", first, last, files, static_hash,
        "signal", tuple(sorted({day.strftime("%Y-%m") for day in official})), {},
    )
    catalog = DatasetCatalog(
        SCHEMA_VERSION,
        _sha256(_canonical({"tier": DatasetTier.ENGINEERING_STATIC, "files": files})),
        DatasetTier.ENGINEERING_STATIC,
        "legacy-static-asx-cache",
        "vendor_adjusted_unknown_components",
        "AUD",
        first,
        last,
        False,
        "vendor_adjusted_price_proxy" if benchmark_complete else "unavailable",
        "static snapshot spans less than three calendar years",
        {manifest.shard_id: manifest},
        "UNSIGNED_ENGINEERING_ONLY",
        limitations,
    )
    return SwingDataset(
        catalog, manifest, calendar, official, bars, membership,
        (), benchmark if benchmark_complete and benchmark is not None else (),
        {}, None, tuple(issues),
    )
