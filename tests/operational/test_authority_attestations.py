"""The daily validity ledger extends fixed, approved authority files."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from qat.operational.authority_attestations import AuthorityAttestations

SYDNEY = ZoneInfo("Australia/Sydney")
FILES = ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
HASHES = {name: hashlib.sha256(name.encode()).hexdigest() for name in FILES}
CALENDAR = SimpleNamespace(
    sessions=tuple(
        SimpleNamespace(session=day)
        for day in (date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27))
    )
)
BASE = date(2026, 10, 23)


def _append(ledger: AuthorityAttestations, day: date, evidence: Path) -> None:
    evidence.write_text(f"ASX audit {day}", encoding="utf-8")
    ledger.append(
        day,
        HASHES,
        evidence,
        operator="DS",
        recorded_at=datetime(day.year, day.month, day.day, 16, 30, tzinfo=SYDNEY),
        calendar=CALENDAR,
        base_valid_through=BASE,
    )


def test_normal_daily_advance_preserves_prior_records(tmp_path: Path) -> None:
    ledger = AuthorityAttestations(tmp_path / "OPERATIONAL" / "authority_attestations.jsonl")
    ledger.path.parent.mkdir()
    _append(ledger, date(2026, 10, 26), tmp_path / "audit-26.json")
    first = ledger.path.read_bytes()
    _append(ledger, date(2026, 10, 27), tmp_path / "audit-27.json")
    assert ledger.path.read_bytes().startswith(first)
    assert ledger.require_current(date(2026, 10, 27), HASHES, CALENDAR, BASE)
    assert len(ledger.load()) == 2


def test_missing_session_refuses_and_cannot_be_appended(tmp_path: Path) -> None:
    ledger = AuthorityAttestations(tmp_path / "authority_attestations.jsonl")
    with pytest.raises(ValueError, match="missing session"):
        ledger.require_current(date(2026, 10, 26), HASHES, CALENDAR, BASE)
    with pytest.raises(ValueError, match="missing session"):
        _append(ledger, date(2026, 10, 27), tmp_path / "audit-27.json")


def test_different_approved_hash_refuses_all(tmp_path: Path) -> None:
    ledger = AuthorityAttestations(tmp_path / "authority_attestations.jsonl")
    _append(ledger, date(2026, 10, 26), tmp_path / "audit-26.json")
    changed = dict(HASHES)
    changed["halts.jsonl"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        ledger.require_current(date(2026, 10, 26), changed, CALENDAR, BASE)


def test_new_approved_event_hash_keeps_prior_attestation_in_chain(tmp_path: Path) -> None:
    ledger = AuthorityAttestations(tmp_path / "authority_attestations.jsonl")
    _append(ledger, date(2026, 10, 26), tmp_path / "audit-26.json")
    changed = dict(HASHES)
    changed["halts.jsonl"] = "0" * 64
    ledger.append(
        date(2026, 10, 27),
        changed,
        tmp_path / "audit-26.json",
        operator="DS",
        recorded_at=datetime(2026, 10, 27, 16, 30, tzinfo=SYDNEY),
        calendar=CALENDAR,
        base_valid_through=BASE,
    )
    assert ledger.require_current(date(2026, 10, 27), changed, CALENDAR, BASE)
    with pytest.raises(ValueError, match="different hash"):
        ledger.require_current(date(2026, 10, 27), HASHES, CALENDAR, BASE)


def test_broken_chain_refuses_even_if_last_session_matches(tmp_path: Path) -> None:
    ledger = AuthorityAttestations(tmp_path / "authority_attestations.jsonl")
    _append(ledger, date(2026, 10, 26), tmp_path / "audit-26.json")
    _append(ledger, date(2026, 10, 27), tmp_path / "audit-27.json")
    raw = ledger.path.read_text(encoding="utf-8")
    ledger.path.write_text(raw.replace("DS", "XX", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="hash chain"):
        ledger.require_current(date(2026, 10, 27), HASHES, CALENDAR, BASE)


def test_duplicate_session_and_missing_audit_refuse(tmp_path: Path) -> None:
    ledger = AuthorityAttestations(tmp_path / "authority_attestations.jsonl")
    audit = tmp_path / "audit-26.json"
    _append(ledger, date(2026, 10, 26), audit)
    with pytest.raises(ValueError, match="duplicate|session"):
        _append(ledger, date(2026, 10, 26), audit)
    audit.unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        ledger.append(
            date(2026, 10, 27),
            HASHES,
            audit,
            operator="DS",
            recorded_at=datetime(2026, 10, 27, 16, 30, tzinfo=SYDNEY),
            calendar=CALENDAR,
            base_valid_through=BASE,
        )
