"""Offline afternoon namespace and exact time gates; no broker connection."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import pytest
from test_phase1_oca_exit_handoff_paper_probe import SYDNEY, api


@pytest.mark.parametrize(
    "hour,minute,allowed", [(13, 44, False), (13, 45, True), (14, 14, True), (14, 15, False)]
)
def test_november3_pm_start_boundaries(hour, minute, allowed):
    p = api()
    stamp = datetime(2026, 11, 3, hour, minute, tzinfo=SYDNEY)
    if allowed:
        p.session_window(date(2026, 11, 3), stamp)
    else:
        with pytest.raises(ValueError):
            p.session_window(date(2026, 11, 3), stamp)


@pytest.mark.parametrize("day", [4, 5])
def test_fallback_start_and_hard_end_unchanged(day):
    p = api()
    session = date(2026, 11, day)
    p.session_window(session, datetime(2026, 11, day, 11, 30, tzinfo=SYDNEY))
    for hour, minute in [(11, 29), (12, 0)]:
        with pytest.raises(ValueError):
            p.session_window(session, datetime(2026, 11, day, hour, minute, tzinfo=SYDNEY))
    p.session_window(session, datetime(2026, 11, day, 15, 29, 59, tzinfo=SYDNEY), starting=False)
    with pytest.raises(ValueError):
        p.session_window(session, datetime(2026, 11, day, 15, 30, tzinfo=SYDNEY), starting=False)


def test_pm_directory_approval_and_attempt_are_separate(tmp_path, monkeypatch):
    p = api()
    session = date(2026, 11, 3)
    morning = tmp_path / "phase1-oca-exit-handoff-20261103"
    morning.mkdir()
    sentinel = morning / "oca-20261103-attempt.lock"
    sentinel.write_bytes(b"preserved morning attempt\n")
    pm = tmp_path / "phase1-oca-exit-handoff-20261103-pm"
    pm.mkdir()
    terms = {
        "account": "DUFAKE",
        "approved_by": "DS",
        "approval_date": "2026-11-03",
        "session": "2026-11-03",
        "symbol": "BHP.AX",
        "operator": "DS",
        "cap_per_order_aud": "800",
    }
    path = pm / "approval.json"
    path.write_text(json.dumps(terms))
    monkeypatch.setattr(p, "ACCOUNT_SHA256", hashlib.sha256(b"DUFAKE").hexdigest())
    assert (
        p.load_approval(path, hashlib.sha256(path.read_bytes()).hexdigest(), pm, session)
        == "DUFAKE"
    )
    p.claim_attempt(pm, session)
    assert (pm / "oca-20261103-pm-attempt.lock").is_file()
    with pytest.raises(FileExistsError):
        p.claim_attempt(pm, session)
    with pytest.raises(ValueError):
        p.checked_output(morning, session)
    assert sentinel.read_bytes() == b"preserved morning attempt\n"
    assert sorted(x.name for x in morning.iterdir()) == ["oca-20261103-attempt.lock"]


def test_pm_hard_end_and_wrong_output_roots(tmp_path):
    p = api()
    session = date(2026, 11, 3)
    p.session_window(session, datetime(2026, 11, 3, 15, 29, 59, tzinfo=SYDNEY), starting=False)
    with pytest.raises(ValueError):
        p.session_window(session, datetime(2026, 11, 3, 15, 30, tzinfo=SYDNEY), starting=False)
    for name in ["phase1-oca-exit-handoff-20261103", "phase1-oca-exit-handoff-20261104"]:
        with pytest.raises(ValueError):
            p.checked_output(tmp_path / name, session)
    for suffix in ["20261027", "20261027-pm", "20261028", "20261102", "20261103"]:
        old = tmp_path / f"phase1-oca-exit-handoff-{suffix}"
        nested = old / "phase1-oca-exit-handoff-20261103-pm"
        with pytest.raises(ValueError):
            p.claim_attempt(nested, session)
        assert not old.exists()
