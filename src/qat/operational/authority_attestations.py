"""Append-only daily audit attestations for fixed, DS-approved authorities.

The four authority files remain immutable under their approved SHA-256 hashes.
This separate OPERATIONAL ledger extends their effective validity one ASX
session at a time; it never changes an authority's original hash chain.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from qat.operational.continuity import RETIREMENT, ContinuityEvidence, checked_date
from qat.operational.history import CalendarLedger

AUTHORITY_FILES = ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
SYDNEY = ZoneInfo("Australia/Sydney")
_FIELDS = {
    "sequence",
    "session",
    "authority_hashes",
    "audit_sha256",
    "operator",
    "recorded_at",
    "previous_hash",
    "content_hash",
}


def base_validity(*dates: date | None) -> date:
    """The oldest fixed-file validity date; none may be undated."""
    if not dates or any(value is None for value in dates):
        raise ValueError("real authority has no valid-through date")
    return min(value for value in dates if value is not None)


def _digest(value: dict[str, Any]) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def _hash(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("invalid SHA-256 hash")
    return value


def _hashes(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(AUTHORITY_FILES):
        raise ValueError("attestation must name exactly four authority hashes")
    return {name: _hash(value[name]) for name in AUTHORITY_FILES}


def _outside_git(path: Path) -> None:
    target = path.expanduser().resolve()
    if any((parent / ".git").exists() for parent in (target, *target.parents)):
        raise ValueError("authority attestations and audit evidence must stay outside Git")
    if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)):
        raise ValueError("authority attestation path cannot be linked")


@dataclass(frozen=True, slots=True)
class Attestation:
    sequence: int
    session: date
    authority_hashes: dict[str, str]
    audit_sha256: str
    operator: str
    recorded_at: datetime
    previous_hash: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class CatchUpAttestation:
    sequence: int
    first_session: date
    last_session: date
    authority_hashes: dict[str, str]
    audit_sha256: str
    approval_sha256: str
    membership_successor_sha256: str | None
    operator: str
    recorded_at: datetime
    previous_hash: str
    content_hash: str

    @property
    def session(self) -> date:
        return self.last_session


Record = Attestation | CatchUpAttestation
_CATCHUP_FIELDS = (_FIELDS - {"session"}) | {
    "record_type",
    "first_session",
    "last_session",
    "approval_sha256",
    "membership_successor_sha256",
}


def _value(record: Record) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sequence": record.sequence,
        "authority_hashes": record.authority_hashes,
        "audit_sha256": record.audit_sha256,
        "operator": record.operator,
        "recorded_at": record.recorded_at.isoformat(),
        "previous_hash": record.previous_hash,
        "content_hash": record.content_hash,
    }
    if isinstance(record, CatchUpAttestation):
        result.update(
            record_type="catch_up_v1",
            first_session=str(record.first_session),
            last_session=str(record.last_session),
            approval_sha256=record.approval_sha256,
            membership_successor_sha256=record.membership_successor_sha256,
        )
    else:
        result["session"] = str(record.session)
    return result


def _json_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate attestation JSON key")
        result[name] = value
    return result


class AuthorityAttestations:
    """Strict physical chain and contiguous logical ASX-session coverage."""

    def __init__(self, path: Path, *, evidence: ContinuityEvidence | None = None) -> None:
        self.path = path
        self.evidence = evidence

    def load(
        self,
        *,
        calendar: CalendarLedger | None = None,
        base_valid_through: date | None = None,
        verify_evidence: bool = False,
    ) -> tuple[Record, ...]:
        _outside_git(self.path)
        if not self.path.exists():
            return ()
        if (
            not self.path.is_file()
            or self.path.is_symlink()
            or self.path.is_junction()
            or self.path.stat().st_nlink != 1
        ):
            raise ValueError("authority attestation ledger is not a regular file")
        raw = self.path.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise ValueError("authority attestation ledger has an incomplete record")
        previous = ""
        records: list[Record] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            try:
                value = json.loads(line, object_pairs_hook=_json_unique)
                if not isinstance(value, dict):
                    raise ValueError("invalid attestation fields")
                is_range = value.get("record_type") == "catch_up_v1"
                if set(value) != (_CATCHUP_FIELDS if is_range else _FIELDS):
                    raise ValueError("invalid attestation fields")
                session = checked_date(value["last_session"] if is_range else value["session"])
                recorded_at = datetime.fromisoformat(value["recorded_at"])
                operator = value["operator"]
                hashes = _hashes(value["authority_hashes"])
                audit = _hash(value["audit_sha256"])
                if (
                    type(value["sequence"]) is not int
                    or value["sequence"] != number
                    or not isinstance(operator, str)
                    or not operator.strip()
                    or recorded_at.tzinfo is None
                    or recorded_at.utcoffset() is None
                    or value["previous_hash"] != previous
                    or (records and session <= records[-1].session)
                    or _hash(value["content_hash"])
                    != _digest({k: v for k, v in value.items() if k != "content_hash"})
                ):
                    raise ValueError("broken attestation hash chain")
                if is_range:
                    first = checked_date(value["first_session"])
                    local = recorded_at.astimezone(SYDNEY)
                    if (
                        first > session
                        or session > local.date()
                        or (session == local.date() and (local.hour, local.minute) < (16, 20))
                    ):
                        raise ValueError("catch-up cannot cover an uncompleted/future session")
                    approval_hash = _hash(value["approval_sha256"])
                    successor_hash = value["membership_successor_sha256"]
                    if successor_hash is not None:
                        successor_hash = _hash(successor_hash)
                    record: Record = CatchUpAttestation(
                        number,
                        first,
                        session,
                        hashes,
                        audit,
                        approval_hash,
                        successor_hash,
                        operator,
                        recorded_at,
                        previous,
                        value["content_hash"],
                    )
                else:
                    if recorded_at.astimezone(SYDNEY).date() != session:
                        raise ValueError("daily attestation cannot be backdated")
                    record = Attestation(
                        number,
                        session,
                        hashes,
                        audit,
                        operator,
                        recorded_at,
                        previous,
                        value["content_hash"],
                    )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"broken attestation hash chain at record {number}") from error
            if isinstance(record, CatchUpAttestation):
                if self.evidence is None:
                    raise ValueError("independently pinned catch-up evidence is required")
                self.evidence.verify_record(value, verify_review=verify_evidence)
            records.append(record)
            previous = record.content_hash
        if any(isinstance(row, CatchUpAttestation) for row in records):
            if calendar is None or base_valid_through is None:
                raise ValueError("approved calendar/base required to load catch-up coverage")
            self._coverage(tuple(records), calendar, base_valid_through)
        return tuple(records)

    def _coverage(
        self, records: tuple[Record, ...], calendar: CalendarLedger, base: date
    ) -> tuple[date, ...]:
        days = tuple(row.session for row in calendar.sessions)
        if days != tuple(sorted(set(days))):
            raise ValueError("invalid approved calendar sessions")
        covered: list[date] = []
        active_hashes: dict[str, str] | None = None
        for row in records:
            if isinstance(row, CatchUpAttestation):
                if row.first_session not in days or row.last_session not in days:
                    raise ValueError("missing session in approved ASX calendar")
                covered.extend(d for d in days if row.first_session <= d <= row.last_session)
                active_hashes = row.authority_hashes
                if row.membership_successor_sha256 is not None:
                    from qat.operational.continuity import EFFECTIVE, RETIREMENT

                    if (
                        RETIREMENT not in days
                        or EFFECTIVE not in days
                        or days.index(EFFECTIVE) != days.index(RETIREMENT) + 1
                    ):
                        raise ValueError(
                            "membership restriction boundary differs from approved calendar"
                        )
            elif row.session > base:
                if active_hashes is not None and row.authority_hashes != active_hashes:
                    raise ValueError("daily authority hashes differ from catch-up base")
                covered.append(row.session)
        if covered:
            expected = tuple(d for d in days if base < d <= covered[-1])
            if tuple(covered) != expected:
                raise ValueError("duplicate or missing session in authority attestation ledger")
        return tuple(covered)

    def covered_sessions(
        self, calendar: CalendarLedger, base_valid_through: date
    ) -> tuple[date, ...]:
        return self._coverage(
            self.load(calendar=calendar, base_valid_through=base_valid_through),
            calendar,
            base_valid_through,
        )

    def successor_hash(self, calendar: CalendarLedger, base_valid_through: date) -> str | None:
        records = self.load(calendar=calendar, base_valid_through=base_valid_through)
        values = [
            r.membership_successor_sha256 for r in records if isinstance(r, CatchUpAttestation)
        ]
        return values[-1] if values else None

    def require_current(
        self,
        session: date,
        approved_hashes: dict[str, str],
        calendar: CalendarLedger,
        base_valid_through: date,
        *,
        verify_evidence: bool = False,
    ) -> str:
        expected_hashes = _hashes(approved_hashes)
        if session <= base_valid_through:
            return ""
        expected = tuple(
            r.session for r in calendar.sessions if base_valid_through < r.session <= session
        )
        if not expected or expected[-1] != session:
            raise ValueError("missing session in approved ASX calendar")
        records = self.load(
            calendar=calendar,
            base_valid_through=base_valid_through,
            verify_evidence=verify_evidence,
        )
        covered = self._coverage(records, calendar, base_valid_through)
        if covered != expected:
            raise ValueError("missing session in authority attestation ledger")
        if (
            not records
            or records[-1].session != session
            or records[-1].authority_hashes != expected_hashes
        ):
            raise ValueError("current authority attestation names a different hash or session")
        if session > RETIREMENT and not any(
            isinstance(r, CatchUpAttestation) and r.membership_successor_sha256 is not None
            for r in records
        ):
            raise ValueError("post-retirement validity requires a ledger-bound successor")
        if any(
            isinstance(r, CatchUpAttestation) and r.authority_hashes != expected_hashes
            for r in records
        ):
            raise ValueError("catch-up authority hashes differ from current approved files")
        return records[-1].content_hash

    def validate_append(
        self,
        session: date,
        approved_hashes: dict[str, str],
        audit_file: Path,
        *,
        operator: str,
        recorded_at: datetime,
        calendar: CalendarLedger,
        base_valid_through: date,
        expected_audit_sha256: str | None = None,
    ) -> Attestation:
        _outside_git(self.path)
        _outside_git(audit_file)
        if not audit_file.is_file() or audit_file.is_symlink() or audit_file.is_junction():
            raise ValueError("daily audit evidence is unavailable or linked")
        if (
            not operator.strip()
            or recorded_at.tzinfo is None
            or recorded_at.astimezone(SYDNEY).date() != session
            or session <= base_valid_through
        ):
            raise ValueError("invalid daily authority attestation")
        hashes = _hashes(approved_hashes)
        audit_hash = hashlib.sha256(audit_file.read_bytes()).hexdigest()
        if expected_audit_sha256 is not None and audit_hash != _hash(expected_audit_sha256):
            raise ValueError("daily audit evidence differs from reviewed SHA-256")
        prior = self.load(
            calendar=calendar, base_valid_through=base_valid_through, verify_evidence=True
        )
        if session > RETIREMENT and not any(
            isinstance(r, CatchUpAttestation) and r.membership_successor_sha256 is not None
            for r in prior
        ):
            raise ValueError("post-retirement daily append requires a ledger-bound successor")
        expected = tuple(
            row.session for row in calendar.sessions if base_valid_through < row.session <= session
        )
        if not expected or expected[-1] != session:
            raise ValueError("missing session in approved ASX calendar")
        if self._coverage(prior, calendar, base_valid_through) != expected[:-1]:
            raise ValueError("duplicate or missing session in authority attestation ledger")
        if any(isinstance(r, CatchUpAttestation) and r.authority_hashes != hashes for r in prior):
            raise ValueError("daily authority hashes differ from catch-up base")
        identity = {
            "sequence": len(prior) + 1,
            "session": str(session),
            "authority_hashes": hashes,
            "audit_sha256": audit_hash,
            "operator": operator,
            "recorded_at": recorded_at.isoformat(),
            "previous_hash": prior[-1].content_hash if prior else "",
        }
        return Attestation(
            len(prior) + 1,
            session,
            hashes,
            audit_hash,
            operator,
            recorded_at,
            prior[-1].content_hash if prior else "",
            _digest(identity),
        )

    def validate_catchup(
        self,
        first_session: date,
        last_session: date,
        approved_hashes: dict[str, str],
        *,
        recorded_at: datetime,
        calendar: CalendarLedger,
        base_valid_through: date,
        operator: str = "DS",
    ) -> CatchUpAttestation:
        _outside_git(self.path)
        if self.evidence is None or recorded_at.tzinfo is None or operator != "DS":
            raise ValueError("pinned DS evidence and aware catch-up time required")
        local = recorded_at.astimezone(SYDNEY)
        if (
            first_session > last_session
            or first_session <= base_valid_through
            or last_session > local.date()
            or (last_session == local.date() and (local.hour, local.minute) < (16, 20))
        ):
            raise ValueError("catch-up requires completed contiguous ASX sessions")
        hashes = _hashes(approved_hashes)
        prior = self.load(
            calendar=calendar, base_valid_through=base_valid_through, verify_evidence=True
        )
        approval = self.evidence.approval()
        identity = {
            "record_type": "catch_up_v1",
            "sequence": len(prior) + 1,
            "first_session": str(first_session),
            "last_session": str(last_session),
            "authority_hashes": hashes,
            "audit_sha256": approval["audit_sha256"],
            "approval_sha256": self.evidence.approval_sha256,
            "membership_successor_sha256": self.evidence.successor_sha256,
            "operator": operator,
            "recorded_at": recorded_at.isoformat(),
            "previous_hash": prior[-1].content_hash if prior else "",
        }
        value = {**identity, "content_hash": _digest(identity)}
        self.evidence.verify_record(value, verify_review=True)
        record = CatchUpAttestation(
            len(prior) + 1,
            first_session,
            last_session,
            hashes,
            approval["audit_sha256"],
            self.evidence.approval_sha256,
            self.evidence.successor_sha256,
            operator,
            recorded_at,
            identity["previous_hash"],
            value["content_hash"],
        )
        self._coverage((*prior, record), calendar, base_valid_through)
        return record

    def _append(
        self, prepare: Callable[[], Record], calendar: CalendarLedger, base: date
    ) -> Record:
        # Pure validation happens before the ephemeral exclusive writer lock exists.
        prepare()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".writer.lock")
        owned = False
        try:
            with lock.open("x", encoding="ascii"):
                owned = True
                record = prepare()  # fresh head/evidence checks under exclusive ownership
                line = (
                    json.dumps(_value(record), sort_keys=True, separators=(",", ":")) + "\n"
                ).encode("ascii")
                with self.path.open("ab") as handle:
                    if handle.write(line) != len(line):
                        raise OSError(
                            "incomplete attestation append; preserve evidence, do not retry"
                        )
                    handle.flush()
                    os.fsync(handle.fileno())
                fresh = AuthorityAttestations(self.path, evidence=self.evidence).load(
                    calendar=calendar, base_valid_through=base, verify_evidence=True
                )
                if not fresh or fresh[-1].content_hash != record.content_hash:
                    raise ValueError("attestation independent reload differs")
                return fresh[-1]
        finally:
            if owned:
                lock.unlink()

    def append(
        self,
        session: date,
        approved_hashes: dict[str, str],
        audit_file: Path,
        *,
        operator: str,
        recorded_at: datetime,
        calendar: CalendarLedger,
        base_valid_through: date,
        expected_audit_sha256: str | None = None,
    ) -> Attestation:
        record = self._append(
            lambda: self.validate_append(
                session,
                approved_hashes,
                audit_file,
                operator=operator,
                recorded_at=recorded_at,
                calendar=calendar,
                base_valid_through=base_valid_through,
                expected_audit_sha256=expected_audit_sha256,
            ),
            calendar,
            base_valid_through,
        )
        if not isinstance(record, Attestation):
            raise ValueError("daily append returned wrong record type")
        return record

    def append_catchup(
        self,
        first_session: date,
        last_session: date,
        approved_hashes: dict[str, str],
        *,
        recorded_at: datetime,
        calendar: CalendarLedger,
        base_valid_through: date,
        operator: str = "DS",
    ) -> CatchUpAttestation:
        record = self._append(
            lambda: self.validate_catchup(
                first_session,
                last_session,
                approved_hashes,
                recorded_at=recorded_at,
                calendar=calendar,
                base_valid_through=base_valid_through,
                operator=operator,
            ),
            calendar,
            base_valid_through,
        )
        if not isinstance(record, CatchUpAttestation):
            raise ValueError("catch-up append returned wrong record type")
        return record
