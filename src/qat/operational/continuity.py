"""Independently pinned DS evidence and restriction-only active membership.

No broker, writer, approval creation or source download is imported here.
The reviewed manifest is opaque bytes: no machine claim of audit completeness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from qat.operational.history import CalendarLedger, Membership, digest
from qat.operational.membership_scope import ActiveMembers, validate_active_members

FILES = ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
RETIREMENT = date(2026, 10, 30)
EFFECTIVE = date(2026, 11, 2)
APPROVAL_FIELDS = {
    "schema",
    "approved_by",
    "signing_date",
    "first_session",
    "last_session",
    "authority_hashes",
    "audit_sha256",
    "membership_successor_sha256",
    "expected_tip_sequence",
    "expected_tip_content_hash",
}
SUCCESSOR_FIELDS = {
    "schema",
    "base_membership_file_sha256",
    "approved_by",
    "signing_date",
    "restrictions",
    "evidence_sha256s",
}


def checked_hash(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("invalid continuity SHA-256")
    return value


def checked_hashes(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(FILES):
        raise ValueError("continuity requires exactly four authority hashes")
    return {name: checked_hash(value[name]) for name in FILES}


def checked_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("invalid continuity date")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("continuity dates must be ISO dates")
    return parsed


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate continuity JSON key")
        result[name] = value
    return result


def private_bytes(path: Path, expected_hash: str) -> bytes:
    checked_hash(expected_hash)
    if (
        not path.is_absolute()
        or not path.is_file()
        or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
        or any((p / ".git").exists() for p in path.parents)
        or path.stat().st_nlink != 1
    ):
        raise ValueError("continuity evidence must be a regular private outside-Git file")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("continuity evidence differs from independently pinned SHA-256")
    return raw


def _document(path: Path, expected_hash: str, fields: set[str]) -> dict[str, Any]:
    value = json.loads(private_bytes(path, expected_hash), object_pairs_hook=_unique)
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid continuity evidence fields")
    return value


def _hash_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("continuity evidence hashes required")
    values = tuple(checked_hash(item) for item in value)
    if len(set(values)) != len(values):
        raise ValueError("duplicate continuity evidence hash")
    return values


@dataclass(frozen=True, slots=True)
class ContinuityEvidence:
    approval_file: Path
    approval_sha256: str
    successor_file: Path | None = None
    successor_sha256: str | None = None
    audit_file: Path | None = None

    def approval(self) -> dict[str, Any]:
        value = _document(self.approval_file, self.approval_sha256, APPROVAL_FIELDS)
        if value["schema"] != "qat-authority-catchup-approval-v1" or value["approved_by"] != "DS":
            raise ValueError("catch-up requires DS approval")
        first, last, signed = (
            checked_date(value[k]) for k in ("first_session", "last_session", "signing_date")
        )
        if first > last or signed < last:
            raise ValueError("catch-up approval range or signing date invalid")
        checked_hashes(value["authority_hashes"])
        checked_hash(value["audit_sha256"])
        if value["membership_successor_sha256"] is not None:
            checked_hash(value["membership_successor_sha256"])
        seq = value["expected_tip_sequence"]
        if type(seq) is not int or seq < 0:
            raise ValueError("invalid approved predecessor sequence")
        if seq:
            checked_hash(value["expected_tip_content_hash"])
        elif value["expected_tip_content_hash"] != "":
            raise ValueError("invalid approved empty predecessor")
        return value

    def successor(self, base_file_hash: str, *, recorded_on: date | None = None) -> dict[str, Any]:
        if self.successor_file is None or self.successor_sha256 is None:
            raise ValueError("independently pinned membership successor required")
        value = _document(self.successor_file, self.successor_sha256, SUCCESSOR_FIELDS)
        if (
            value["schema"] != "asx-membership-restriction-v1"
            or value["approved_by"] != "DS"
            or checked_hash(value["base_membership_file_sha256"]) != checked_hash(base_file_hash)
        ):
            raise ValueError("membership successor base or DS approval differs")
        signed = checked_date(value["signing_date"])
        if recorded_on is not None and signed > recorded_on:
            raise ValueError("membership successor signing date is in the future")
        evidence = _hash_list(value["evidence_sha256s"])
        restrictions = value["restrictions"]
        # This reviewed interim route removes only MFG; BJY or other changes need review.
        if not isinstance(restrictions, list) or len(restrictions) != 1:
            raise ValueError("one approved MFG restriction required")
        item = restrictions[0]
        if not isinstance(item, dict) or set(item) != {
            "symbol",
            "last_active_session",
            "effective_from",
            "reason",
            "source_sha256s",
        }:
            raise ValueError("invalid membership restriction fields")
        if (
            item["symbol"] != "MFG.AX"
            or checked_date(item["last_active_session"]) != RETIREMENT
            or checked_date(item["effective_from"]) != EFFECTIVE
            or not isinstance(item["reason"], str)
            or not item["reason"].strip()
            or not set(_hash_list(item["source_sha256s"])) <= set(evidence)
        ):
            raise ValueError("membership restriction cannot rename, add or extend membership")
        return value

    def verify_record(self, value: dict[str, Any], *, verify_review: bool = False) -> None:
        from qat.operational.history import SYDNEY

        approval = self.approval()
        recorded = datetime.fromisoformat(value["recorded_at"])
        if recorded.tzinfo is None:
            raise ValueError("aware catch-up recorded_at required")
        if (
            value["approval_sha256"] != self.approval_sha256
            or value["operator"] != "DS"
            or value["first_session"] != approval["first_session"]
            or value["last_session"] != approval["last_session"]
            or value["authority_hashes"] != approval["authority_hashes"]
            or value["audit_sha256"] != approval["audit_sha256"]
            or value["membership_successor_sha256"] != approval["membership_successor_sha256"]
            or value["membership_successor_sha256"] != self.successor_sha256
            or value["previous_hash"] != approval["expected_tip_content_hash"]
            or value["sequence"] != approval["expected_tip_sequence"] + 1
            or checked_date(approval["signing_date"]) > recorded.astimezone(SYDNEY).date()
        ):
            raise ValueError("catch-up record differs from pinned DS approval terms")
        if value["membership_successor_sha256"] is not None:
            self.successor(
                approval["authority_hashes"]["membership.json"],
                recorded_on=recorded.astimezone(SYDNEY).date(),
            )
        if checked_date(value["last_session"]) > RETIREMENT and self.successor_sha256 is None:
            raise ValueError("post-retirement catch-up requires the approved successor")
        if verify_review:
            if self.audit_file is None:
                raise ValueError("review evidence file required for dry-run/apply/verification")
            private_bytes(self.audit_file, value["audit_sha256"])


def evidence_from_settings(settings: Any) -> ContinuityEvidence | None:
    approval = getattr(settings, "phase3_catchup_approval_file", "")
    approval_hash = getattr(settings, "phase3_catchup_approval_sha256", "")
    successor = getattr(settings, "phase3_membership_successor_file", "")
    successor_hash = getattr(settings, "phase3_membership_successor_sha256", "")
    audit = getattr(settings, "phase3_catchup_audit_file", "")
    if not any((approval, approval_hash, successor, successor_hash, audit)):
        return None
    if not approval or not approval_hash or bool(successor) != bool(successor_hash):
        raise ValueError("complete independently pinned continuity evidence configuration required")
    return ContinuityEvidence(
        Path(approval),
        checked_hash(approval_hash),
        Path(successor) if successor else None,
        checked_hash(successor_hash) if successor_hash else None,
        Path(audit) if audit else None,
    )


@dataclass(frozen=True, slots=True)
class VerifiedMembershipSource:
    base_file_sha256: str
    calendar: CalendarLedger
    evidence: ContinuityEvidence | None = None
    bound_successor_sha256: str | None = None

    def resolve(
        self, membership: Membership, session: date, *, attested_through: date | None = None
    ) -> ActiveMembers:
        checked_hash(self.base_file_sha256)
        if session not in {row.session for row in self.calendar.sessions}:
            raise ValueError("active membership requires an approved ASX session")
        symbols = tuple(
            s
            for s in membership.symbols
            if membership.is_current(s, session, attested_through=attested_through)
        )
        successor_hash = None
        if self.bound_successor_sha256 is not None:
            if (
                self.evidence is None
                or self.bound_successor_sha256 != self.evidence.successor_sha256
            ):
                raise ValueError("membership successor is not independently pinned")
            successor = self.evidence.successor(self.base_file_sha256)
            days = tuple(row.session for row in self.calendar.sessions)
            if (
                RETIREMENT not in days
                or EFFECTIVE not in days
                or days.index(EFFECTIVE) != days.index(RETIREMENT) + 1
                or "MFG.AX" not in membership.symbols
            ):
                raise ValueError(
                    "membership restriction boundary differs from approved calendar/base"
                )
            if session >= EFFECTIVE:
                symbols = tuple(s for s in symbols if s != successor["restrictions"][0]["symbol"])
            successor_hash = self.bound_successor_sha256
        if session > RETIREMENT and successor_hash is None:
            raise ValueError(
                "active_membership_successor_required: post-retirement scope is unverified"
            )
        fingerprint = digest(
            {
                "domain": "qat-active-membership-v1",
                "session": session,
                "base_membership_file_sha256": self.base_file_sha256,
                "base_membership_content_hash": membership.content_hash,
                "successor_sha256": successor_hash,
                "symbols": symbols,
            }
        )
        return validate_active_members(
            membership,
            session,
            ActiveMembers(session, symbols, membership.content_hash, fingerprint),
            attested_through=attested_through,
        )


EVIDENCE_ARGUMENTS = (
    ("--catchup-approval-file", "phase3_catchup_approval_file"),
    ("--catchup-approval-sha256", "phase3_catchup_approval_sha256"),
    ("--membership-successor-file", "phase3_membership_successor_file"),
    ("--membership-successor-sha256", "phase3_membership_successor_sha256"),
    ("--catchup-audit-file", "phase3_catchup_audit_file"),
)


def add_continuity_arguments(parser: Any) -> None:
    for flag, destination in EVIDENCE_ARGUMENTS:
        parser.add_argument(flag, dest=destination, default=None)


def continuity_values(namespace: Any) -> dict[str, str]:
    return {
        destination: getattr(namespace, destination)
        for _, destination in EVIDENCE_ARGUMENTS
        if getattr(namespace, destination, None) is not None
    }
