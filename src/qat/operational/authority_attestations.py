"""Append-only daily audit attestations for fixed, DS-approved authorities.

The four authority files remain immutable under their approved SHA-256 hashes.
This separate OPERATIONAL ledger extends their effective validity one ASX
session at a time; it never changes an authority's original hash chain.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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


class AuthorityAttestations:
    """Strict reader and single-session append writer for the private ledger."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[Attestation, ...]:
        _outside_git(self.path)
        if not self.path.exists():
            return ()
        if not self.path.is_file() or self.path.is_symlink() or self.path.is_junction():
            raise ValueError("authority attestation ledger is not a regular file")
        raw = self.path.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise ValueError("authority attestation ledger has an incomplete record")
        previous = ""
        records: list[Attestation] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict) or set(value) != _FIELDS:
                    raise ValueError("invalid attestation fields")
                session = date.fromisoformat(value["session"])
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
                    or recorded_at.astimezone(SYDNEY).date() != session
                    or value["previous_hash"] != previous
                    or (records and session <= records[-1].session)
                    or _hash(value["content_hash"])
                    != _digest({key: item for key, item in value.items() if key != "content_hash"})
                ):
                    raise ValueError("broken attestation hash chain")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"broken attestation hash chain at record {number}") from error
            records.append(
                Attestation(
                    number,
                    session,
                    hashes,
                    audit,
                    operator,
                    recorded_at,
                    previous,
                    value["content_hash"],
                )
            )
            previous = value["content_hash"]
        return tuple(records)

    def require_current(
        self,
        session: date,
        approved_hashes: dict[str, str],
        calendar: CalendarLedger,
        base_valid_through: date,
    ) -> str:
        """Return the current attestation hash or refuse any gap or mismatch."""
        expected = _hashes(approved_hashes)
        sessions = tuple(
            row.session for row in calendar.sessions if base_valid_through < row.session <= session
        )
        if session <= base_valid_through:
            return ""
        if not sessions or sessions[-1] != session:
            raise ValueError("missing session in approved ASX calendar")
        records = self.load()
        recorded = tuple(
            row.session for row in records if base_valid_through < row.session <= session
        )
        if recorded != sessions:
            raise ValueError("missing session in authority attestation ledger")
        if records[-1].session != session or records[-1].authority_hashes != expected:
            raise ValueError("current authority attestation names a different hash or session")
        return records[-1].content_hash

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
        prior = self.load()
        expected = tuple(
            row.session for row in calendar.sessions if base_valid_through < row.session <= session
        )
        if not expected or expected[-1] != session:
            raise ValueError("missing session in approved ASX calendar")
        if tuple(row.session for row in prior if row.session > base_valid_through) != expected[:-1]:
            raise ValueError("duplicate or missing session in authority attestation ledger")
        identity = {
            "sequence": len(prior) + 1,
            "session": session.isoformat(),
            "authority_hashes": hashes,
            "audit_sha256": audit_hash,
            "operator": operator,
            "recorded_at": recorded_at.isoformat(),
            "previous_hash": prior[-1].content_hash if prior else "",
        }
        record = {**identity, "content_hash": _digest(identity)}
        line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return self.load()[-1]
