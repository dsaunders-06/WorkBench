"""Custodian-side, field-limited reference and structural releases.

These pure functions accept synthetic rows in tests. Production callers must
inject the independently controlled receipt authority and shard reader.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from qat.promotion.operator_signatures import (
    CustodianTrust,
    OperatorApproval,
    resolve_custodian_trust,
    verify_operator_approval,
)


class ExtractLockedError(PermissionError):
    """A proposed release breaches the information boundary."""


class ReceiptAuthority(Protocol):
    head: str

    def append(self, state: str, payload: dict[str, object], *, expected_head: str) -> object: ...

    def verify(
        self, receipt: object, *, state: str, payload: dict[str, object], expected_head: str
    ) -> bool: ...


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=_date_json).encode("ascii")
    ).hexdigest()


def _date_json(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("unsupported release value")


def _record(authority: ReceiptAuthority, state: str, payload: dict[str, object]) -> str:
    head = authority.head
    try:
        receipt = authority.append(state, payload, expected_head=head)
        if not authority.verify(receipt, state=state, payload=payload, expected_head=head):
            raise ExtractLockedError("release receipt failed independent verification")
        new_head = authority.head
        if not re.fullmatch(r"[0-9a-f]{64}", new_head) or new_head == head:
            raise ExtractLockedError("release receipt did not advance the ledger")
        return new_head
    except Exception as exc:
        raise ExtractLockedError("release receipt was not committed and verified") from exc


@dataclass(frozen=True, slots=True)
class ReferenceCatalog:
    catalog_id: str
    source_shard_hash: str
    holdout_start: date
    official_sessions: tuple[date, ...]

    def __post_init__(self) -> None:
        if (
            not self.catalog_id
            or re.fullmatch(r"[0-9a-f]{64}", self.source_shard_hash) is None
            or not self.official_sessions
            or tuple(sorted(set(self.official_sessions))) != self.official_sessions
            or self.holdout_start <= self.official_sessions[0]
        ):
            raise ValueError("invalid reference catalog or official session ledger")


@dataclass(frozen=True, slots=True)
class ExposureWindow:
    pseudonymous_issuer_id: str
    window_start: date
    window_end: date
    eligible: bool
    index_member: bool
    market_cap_bucket: str
    liquidity_bucket: str
    corporate_event_category: str
    event_onset_session: date | None
    consideration_category: str

    @property
    def end(self) -> date:
        return self.window_end


@dataclass(frozen=True, slots=True)
class ReferenceViewReleaseReceipt:
    state: str
    catalog_id: str
    release_id: str
    schema: tuple[str, ...]
    row_count: int
    issuer_count: int
    maximum_session: date
    official_calendar_hash: str
    source_record_hashes: tuple[str, ...]
    output_hash: str
    head: str


@dataclass(frozen=True, slots=True)
class ReferenceViewAccess:
    exposure_windows: tuple[ExposureWindow, ...]
    schema: tuple[str, ...]
    maximum_session: date
    latest_receipt: ReferenceViewReleaseReceipt


_REFERENCE_OUTPUT = (
    "pseudonymous_issuer_id",
    "window_start",
    "window_end",
    "eligible",
    "index_member",
    "market_cap_bucket",
    "liquidity_bucket",
    "corporate_event_category",
    "event_onset_session",
    "consideration_category",
)
_REFERENCE_INPUT = frozenset({"issuer_id", *_REFERENCE_OUTPUT})


def authorize_reference_view(
    rows: Sequence[Mapping[str, object]],
    *,
    catalog: ReferenceCatalog,
    release_id: str,
    authority: ReceiptAuthority,
    operator_approval: OperatorApproval | None = None,
    test_mode: bool = False,
    test_trust: CustodianTrust | None = None,
) -> ReferenceViewAccess:
    """Release only strategy-independent windows ending before the holdout."""
    if not release_id or not rows or authority is None:
        raise ExtractLockedError("reference release needs a named source and authority")
    windows: list[ExposureWindow] = []
    issuers: set[str] = set()
    pseudonyms: dict[str, str] = {}
    source_hashes: list[str] = []
    sessions = set(catalog.official_sessions)
    for row in rows:
        if set(row) != _REFERENCE_INPUT:
            raise ExtractLockedError("reference source contains forbidden or missing fields")
        issuer = row["issuer_id"]
        pseudonym = row["pseudonymous_issuer_id"]
        start, end = row["window_start"], row["window_end"]
        onset = row["event_onset_session"]
        if (
            not isinstance(issuer, str)
            or not issuer
            or not isinstance(pseudonym, str)
            or not pseudonym
            or pseudonym == issuer
            or (pseudonym in pseudonyms and pseudonyms[pseudonym] != issuer)
            or not isinstance(start, date)
            or not isinstance(end, date)
            or start not in sessions
            or end not in sessions
            or start > end
            or end >= catalog.holdout_start
            or type(row["eligible"]) is not bool
            or type(row["index_member"]) is not bool
            or any(
                not isinstance(row[key], str) or not row[key]
                for key in (
                    "market_cap_bucket",
                    "liquidity_bucket",
                    "corporate_event_category",
                    "consideration_category",
                )
            )
            or (
                onset is not None
                and (
                    not isinstance(onset, date)
                    or onset not in sessions
                    or onset < start
                    or onset > end
                )
            )
            or (row["corporate_event_category"] == "none" and onset is not None)
        ):
            raise ExtractLockedError("invalid or holdout-crossing reference exposure")
        pseudonyms[pseudonym] = issuer
        issuers.add(issuer)
        source_hashes.append(_digest(dict(row)))
        windows.append(
            ExposureWindow(
                pseudonym,
                start,
                end,
                row["eligible"],
                row["index_member"],
                cast(str, row["market_cap_bucket"]),
                cast(str, row["liquidity_bucket"]),
                cast(str, row["corporate_event_category"]),
                onset,
                cast(str, row["consideration_category"]),
            )
        )
    maximum = max(window.end for window in windows)
    calendar_hash = _digest(catalog.official_sessions)
    output = tuple(windows)
    output_hash = _digest([asdict(window) for window in output])
    payload: dict[str, object] = {
        "catalog_id": catalog.catalog_id,
        "source_shard_hash": catalog.source_shard_hash,
        "official_calendar_hash": calendar_hash,
        "holdout_start": catalog.holdout_start.isoformat(),
        "release_id": release_id,
        "schema": list(_REFERENCE_OUTPUT),
        "row_count": len(windows),
        "issuer_count": len(issuers),
        "maximum_session": maximum.isoformat(),
        "source_record_hashes": source_hashes,
        "output_hash": output_hash,
    }
    try:
        trust = resolve_custodian_trust(test_mode=test_mode, test_trust=test_trust)
        if operator_approval is None:
            raise ExtractLockedError("reference release needs an operator signature")
        verify_operator_approval(operator_approval, "REFERENCE_VIEW_RELEASED", payload, trust=trust)
    except Exception as exc:
        raise ExtractLockedError("reference release lacks pinned operator approval") from exc
    head = _record(authority, "REFERENCE_VIEW_RELEASED", payload)
    receipt = ReferenceViewReleaseReceipt(
        "REFERENCE_VIEW_RELEASED",
        catalog.catalog_id,
        release_id,
        _REFERENCE_OUTPUT,
        len(windows),
        len(issuers),
        maximum,
        calendar_hash,
        tuple(source_hashes),
        output_hash,
        head,
    )
    return ReferenceViewAccess(output, _REFERENCE_OUTPUT, maximum, receipt)


@dataclass(frozen=True, slots=True)
class StructuralDependencyClosure:
    extractor_hash: str
    engine_hash: str
    eligibility_hash: str
    normalization_hash: str
    official_calendar_hash: str
    numeric_hash: str
    cost_hash: str
    sizing_hash: str
    schema_hash: str
    source_shard_hash: str

    def __post_init__(self) -> None:
        if any(re.fullmatch(r"[0-9a-f]{64}", getattr(self, f.name)) is None for f in fields(self)):
            raise ValueError("dependency closure requires ten SHA-256 digests")

    @property
    def sha256(self) -> str:
        return _digest({f.name: getattr(self, f.name) for f in fields(self)})


@dataclass(frozen=True, slots=True)
class StructuralExtractReceipt:
    state: str
    dependency_closure_hash: str
    input_hash: str
    output_hash: str
    head: str

    def valid_for(
        self, closure: StructuralDependencyClosure, *, report_writer_hash: str | None = None
    ) -> bool:
        return self.dependency_closure_hash == closure.sha256


@dataclass(frozen=True, slots=True)
class StructuralView:
    schema: tuple[str, ...]
    monthly_frequency: tuple[tuple[str, str, int], ...]
    pattern_summaries: tuple[tuple[str, int, tuple[tuple[str, str, str], ...]], ...]
    category_counts: tuple[tuple[str, str, str, int], ...]
    latest_receipt: StructuralExtractReceipt


_STRUCTURAL_INPUT = frozenset(
    {
        "pattern",
        "signal_month",
        "stop_distance",
        "candidate_count",
        "rejection_reason",
        "price_bucket",
        "liquidity_bucket",
        "cost_to_planned_risk",
        "quantity",
        "notional",
    }
)
_STRUCTURAL_NUMERIC = (
    "stop_distance",
    "candidate_count",
    "cost_to_planned_risk",
    "quantity",
    "notional",
)


def derive_structural_view(
    rows: Sequence[Mapping[str, object]],
    *,
    patterns: Sequence[str],
    complete_months: Sequence[str],
    closure: StructuralDependencyClosure,
    authority: ReceiptAuthority,
) -> StructuralView:
    """Return aggregates from signal-time fields after logging their exact closure."""
    if (
        authority is None
        or not patterns
        or not complete_months
        or len(set(patterns)) != len(patterns)
        or len(set(complete_months)) != len(complete_months)
        or any(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None for month in complete_months)
    ):
        raise ExtractLockedError("structural extract needs approved patterns, months and authority")
    values: dict[str, dict[str, list[Decimal]]] = {
        pattern: {key: [] for key in _STRUCTURAL_NUMERIC} for pattern in patterns
    }
    frequencies = {(pattern, month): 0 for pattern in patterns for month in complete_months}
    categories: Counter[tuple[str, str, str]] = Counter()
    safe_rows: list[dict[str, str]] = []
    for row in rows:
        if set(row) != _STRUCTURAL_INPUT:
            raise ExtractLockedError("structural source contains forbidden or missing fields")
        pattern, month = row["pattern"], row["signal_month"]
        if (
            not isinstance(pattern, str)
            or not isinstance(month, str)
            or (pattern, month) not in frequencies
        ):
            raise ExtractLockedError("structural row is outside declared pattern/month scope")
        safe: dict[str, str] = {}
        for key in _STRUCTURAL_NUMERIC:
            raw = row[key]
            if not isinstance(raw, (str, int)) or isinstance(raw, bool):
                raise ExtractLockedError("structural numeric input must be an exact decimal")
            try:
                value = Decimal(str(raw))
            except InvalidOperation as exc:
                raise ExtractLockedError("invalid structural decimal") from exc
            if not value.is_finite() or value < 0:
                raise ExtractLockedError("structural numeric value must be finite and nonnegative")
            values[pattern][key].append(value)
            safe[key] = str(value)
        if not all(
            isinstance(row[key], str) and row[key]
            for key in ("rejection_reason", "price_bucket", "liquidity_bucket")
        ):
            raise ExtractLockedError("structural categorical input is invalid")
        safe.update(
            {
                key: str(row[key])
                for key in (
                    "pattern",
                    "signal_month",
                    "rejection_reason",
                    "price_bucket",
                    "liquidity_bucket",
                )
            }
        )
        safe_rows.append(safe)
        frequencies[(pattern, month)] += 1
        for key in ("rejection_reason", "price_bucket", "liquidity_bucket"):
            categories[(pattern, key, safe[key])] += 1
    monthly = tuple(
        (pattern, month, frequencies[(pattern, month)])
        for pattern in patterns
        for month in complete_months
    )
    summaries = tuple(
        (
            pattern,
            len(values[pattern]["stop_distance"]),
            tuple(
                (key, str(min(items)), str(max(items)))
                for key in _STRUCTURAL_NUMERIC
                if (items := values[pattern][key])
            ),
        )
        for pattern in patterns
    )
    category_counts = tuple(
        (pattern, key, value, count) for (pattern, key, value), count in sorted(categories.items())
    )
    schema = ("monthly_frequency", "pattern_summaries", "category_counts")
    input_hash, output_hash = _digest(safe_rows), _digest((monthly, summaries, category_counts))
    payload: dict[str, object] = {
        "dependency_closure_hash": closure.sha256,
        "schema": list(schema),
        "input_hash": input_hash,
        "output_hash": output_hash,
    }
    head = _record(authority, "DEV_STRUCTURE_DERIVED", payload)
    receipt = StructuralExtractReceipt(
        "DEV_STRUCTURE_DERIVED", closure.sha256, input_hash, output_hash, head
    )
    return StructuralView(schema, monthly, summaries, category_counts, receipt)
