"""Catch-up authority continuity is append-only; every file here is a tmp copy."""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from qat.operational import history as h
from qat.operational.authority_attestations import AuthorityAttestations

BASE = date(2026, 10, 23)
FIRST = date(2026, 10, 28)
LAST = date(2026, 11, 3)
NOW = datetime.fromisoformat("2026-11-03T18:00:00+11:00")
FIVE = (FIRST, date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2), LAST)


def api():
    assert importlib.util.find_spec("qat.operational.continuity"), "catch-up verifier absent"
    return importlib.import_module("qat.operational.continuity")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def case(tmp_path):
    authorities = tmp_path / "authorities"
    authorities.mkdir()
    names = tuple(
        sorted(
            f"{s}.AX"
            for s in ("SUN", "MFG", "CBA", "BHP", "CSL", "WES", "WOW", "TLS", "WDS", "TCL")
        )
    )
    days = [
        "2026-10-23",
        "2026-10-26",
        "2026-10-27",
        "2026-10-28",
        "2026-10-29",
        "2026-10-30",
        "2026-11-02",
        "2026-11-03",
        "2026-11-04",
        "2026-11-05",
    ]
    write(
        authorities / "calendar.json",
        dict(
            schema="asx-calendar-v1",
            version=1,
            published_on=str(BASE),
            coverage_start=str(BASE),
            coverage_end=days[-1],
            source="https://www.asx.com.au/markets/trading-calendar",
            fixture=False,
            valid_through=str(BASE),
            sessions=[dict(session=d, open=f"{d}T10:00:00+11:00") for d in days],
            closures=[],
        ),
    )
    write(
        authorities / "membership.json",
        dict(
            schema="asx200-membership-v2",
            version=2,
            published_on=str(BASE),
            valid_through=str(BASE),
            fixture=False,
            managed_symbols=[],
            entries=[
                dict(
                    symbol=s,
                    effective_from=str(BASE),
                    effective_to=None,
                    citations=["https://www.ssga.com/stw", "https://www.blackrock.com/au/ioz"],
                )
                for s in names
            ],
        ),
    )
    write(
        authorities / "actions.json",
        dict(
            schema="asx-corporate-actions-v1",
            version=1,
            published_on=str(BASE),
            coverage_start=str(BASE),
            coverage_end=str(BASE),
            valid_through=str(BASE),
            source="https://www.asx.com.au/markets/announcements",
            fixture=False,
            events=[],
        ),
    )
    write(
        authorities / "halts.jsonl",
        dict(
            schema="asx-halts-v1",
            version=1,
            published_on=str(BASE),
            valid_through=str(BASE),
            fixture=False,
        ),
    )
    halts = h.append_halt(
        authorities / "halts.jsonl",
        "MFG.AX",
        BASE,
        BASE,
        "broker_record",
        "IBKR:offline-halt-evidence",
    )
    hashes = {p.name: sha(p) for p in authorities.iterdir()}
    cal = h.load_calendar(authorities / "calendar.json")
    membership = h.load_membership(authorities / "membership.json")
    operational = tmp_path / "OPERATIONAL"
    store = h.HistoryStore(
        operational, repository_root=Path(__file__).parents[2], protected_roots=()
    )
    store.accept_halts(halts)
    template = h.parse_bar(
        json.loads((Path(__file__).parent / "fixtures" / "bar.json").read_text())
    )
    stamp = datetime.fromisoformat("2026-10-27T17:30:00+11:00")
    store.ingest(
        (replace(template, symbol="MFG.AX", session=date(2026, 10, 26), retrieved_at=stamp),),
        cal,
        received_at=stamp,
    )
    ledger = AuthorityAttestations(operational / "authority_attestations.jsonl")
    for d in [date(2026, 10, 26), date(2026, 10, 27)]:
        audit = tmp_path / f"audit-{d}.txt"
        audit.write_text(f"Reviewed daily audit {d}")
        ledger.append(
            d,
            hashes,
            audit,
            operator="DS",
            recorded_at=datetime.combine(d, datetime.min.time(), h.SYDNEY).replace(
                hour=16, minute=30
            ),
            calendar=cal,
            base_valid_through=BASE,
        )
    prefix = ledger.path.read_bytes()
    prior = ledger.load()[-1]
    review = tmp_path / "catchup-review.txt"
    review.write_text("Auditor-reviewed per-session manifest; deliberately not parsed as JSON.")
    successor = tmp_path / "membership-restriction.json"
    write(
        successor,
        dict(
            schema="asx-membership-restriction-v1",
            base_membership_file_sha256=hashes["membership.json"],
            approved_by="DS",
            signing_date="2026-11-02",
            restrictions=[
                dict(
                    symbol="MFG.AX",
                    last_active_session="2026-10-30",
                    effective_from="2026-11-02",
                    reason="DS interim retirement; no BJY mapping",
                    source_sha256s=["a" * 64],
                )
            ],
            evidence_sha256s=["a" * 64],
        ),
    )
    approval = tmp_path / "catchup-approval.json"
    write(
        approval,
        dict(
            schema="qat-authority-catchup-approval-v1",
            approved_by="DS",
            signing_date="2026-11-03",
            first_session=str(FIRST),
            last_session=str(LAST),
            authority_hashes=hashes,
            audit_sha256=sha(review),
            membership_successor_sha256=sha(successor),
            expected_tip_sequence=prior.sequence,
            expected_tip_content_hash=prior.content_hash,
        ),
    )
    evidence = api().ContinuityEvidence(
        approval_file=approval,
        approval_sha256=sha(approval),
        successor_file=successor,
        successor_sha256=sha(successor),
        audit_file=review,
    )
    ledger = AuthorityAttestations(ledger.path, evidence=evidence)
    return SimpleNamespace(
        root=authorities,
        hashes=hashes,
        cal=cal,
        membership=membership,
        store=store,
        ledger=ledger,
        prefix=prefix,
        review=review,
        approval=approval,
        successor=successor,
        evidence=evidence,
    )


def kwargs(c):
    return dict(recorded_at=NOW, calendar=c.cal, base_valid_through=BASE)


def append(c):
    return c.ledger.append_catchup(FIRST, LAST, c.hashes, **kwargs(c))


def repin(c, *, approval=False, successor=False):
    c.evidence = replace(
        c.evidence,
        approval_sha256=sha(c.approval) if approval else c.evidence.approval_sha256,
        successor_sha256=sha(c.successor) if successor else c.evidence.successor_sha256,
    )
    c.ledger = AuthorityAttestations(c.ledger.path, evidence=c.evidence)


def test_legacy_two_records_and_five_session_catchup_then_daily(tmp_path):
    c = case(tmp_path)
    original = {p: p.read_bytes() for p in c.root.iterdir()}
    database = c.store.database.read_bytes()
    with sqlite3.connect(c.store.database) as conn:
        rows = conn.execute("SELECT * FROM bars").fetchall()
        watermark = conn.execute("SELECT * FROM halt_acceptance").fetchall()
    prepared = c.ledger.validate_catchup(FIRST, LAST, c.hashes, **kwargs(c))
    assert c.ledger.path.read_bytes() == c.prefix
    record = append(c)
    assert record.content_hash == prepared.content_hash
    assert c.ledger.path.read_bytes().startswith(c.prefix)
    assert c.ledger.covered_sessions(c.cal, BASE)[-5:] == FIVE
    assert len(c.ledger.load(calendar=c.cal, base_valid_through=BASE, verify_evidence=True)) == 3
    assert c.ledger.require_current(LAST, c.hashes, c.cal, BASE) == record.content_hash
    audit = tmp_path / "daily-4.txt"
    audit.write_text("Reviewed 4 November")
    daily = c.ledger.append(
        date(2026, 11, 4),
        c.hashes,
        audit,
        operator="DS",
        recorded_at=datetime.fromisoformat("2026-11-04T16:30:00+11:00"),
        calendar=c.cal,
        base_valid_through=BASE,
    )
    assert daily.sequence == 4 and daily.previous_hash == record.content_hash
    assert c.ledger.require_current(date(2026, 11, 4), c.hashes, c.cal, BASE) == daily.content_hash
    assert c.ledger.path.read_bytes().splitlines(keepends=True)[:2] == c.prefix.splitlines(
        keepends=True
    )
    assert all(p.read_bytes() == v for p, v in original.items())
    assert c.store.database.read_bytes() == database
    with sqlite3.connect(c.store.database) as conn:
        assert conn.execute("SELECT * FROM bars").fetchall() == rows
        assert conn.execute("SELECT * FROM halt_acceptance").fetchall() == watermark


@pytest.mark.parametrize(
    "first,last",
    [
        (date(2026, 10, 29), LAST),
        (date(2026, 10, 27), LAST),
        (date(2026, 10, 31), LAST),
        (LAST, FIRST),
        (FIRST, date(2026, 11, 4)),
    ],
)
def test_range_gap_overlap_non_session_and_future_refused(tmp_path, first, last):
    c = case(tmp_path)
    v = json.loads(c.approval.read_text())
    v.update(first_session=str(first), last_session=str(last))
    write(c.approval, v)
    repin(c, approval=True)
    with pytest.raises(ValueError):
        c.ledger.validate_catchup(first, last, c.hashes, **kwargs(c))
    assert c.ledger.path.read_bytes() == c.prefix


@pytest.mark.parametrize(
    "field,value",
    [
        ("signing_date", "2026-11-02"),
        ("signing_date", "2026-11-04"),
        ("expected_tip_sequence", 1),
        ("expected_tip_content_hash", "0" * 64),
        ("approved_by", "OTHER"),
        ("extra", "not allowed"),
    ],
)
def test_pinned_approval_terms_refused(tmp_path, field, value):
    c = case(tmp_path)
    v = json.loads(c.approval.read_text())
    v[field] = value
    write(c.approval, v)
    repin(c, approval=True)
    with pytest.raises(ValueError):
        append(c)
    assert c.ledger.path.read_bytes() == c.prefix


@pytest.mark.parametrize("changed", ["review", "approval", "successor"])
def test_evidence_changed_after_dry_run_refuses_append(tmp_path, changed):
    c = case(tmp_path)
    c.ledger.validate_catchup(FIRST, LAST, c.hashes, **kwargs(c))
    p = getattr(c, changed)
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(ValueError):
        append(c)
    assert c.ledger.path.read_bytes() == c.prefix


def test_ordinary_load_ignores_review_bytes_but_independent_verify_rechecks(tmp_path):
    c = case(tmp_path)
    append(c)
    c.review.unlink()
    assert len(c.ledger.load(calendar=c.cal, base_valid_through=BASE)) == 3
    with pytest.raises((ValueError, OSError)):
        c.ledger.load(calendar=c.cal, base_valid_through=BASE, verify_evidence=True)


@pytest.mark.parametrize("changed", ["approval", "successor"])
def test_ordinary_load_rechecks_pinned_evidence(tmp_path, changed):
    c = case(tmp_path)
    append(c)
    p = getattr(c, changed)
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(ValueError):
        c.ledger.load(calendar=c.cal, base_valid_through=BASE)


def test_no_independent_pins_no_catchup_load(tmp_path):
    c = case(tmp_path)
    append(c)
    unpinned = AuthorityAttestations(c.ledger.path)
    with pytest.raises(ValueError):
        unpinned.load(calendar=c.cal, base_valid_through=BASE)


def test_duplicate_and_changed_current_hash_refused(tmp_path):
    c = case(tmp_path)
    append(c)
    before = c.ledger.path.read_bytes()
    with pytest.raises(ValueError):
        append(c)
    assert c.ledger.path.read_bytes() == before
    changed = dict(c.hashes)
    changed["membership.json"] = "0" * 64
    with pytest.raises(ValueError):
        c.ledger.require_current(LAST, changed, c.cal, BASE)


@pytest.mark.parametrize("fault", ["base", "add_BJY", "extend_MFG", "gap", "future_signing"])
def test_successor_cannot_rename_add_reenter_or_diverge(tmp_path, fault):
    c = case(tmp_path)
    v = json.loads(c.successor.read_text())
    if fault == "base":
        v["base_membership_file_sha256"] = "0" * 64
    elif fault == "add_BJY":
        v["restrictions"][0]["symbol"] = "BJY.AX"
    elif fault == "extend_MFG":
        v["restrictions"][0]["last_active_session"] = "2026-11-03"
    elif fault == "gap":
        v["restrictions"][0]["effective_from"] = "2026-11-03"
    else:
        v["signing_date"] = "2026-11-04"
    write(c.successor, v)
    repin(c, successor=True)
    approval = json.loads(c.approval.read_text())
    approval["membership_successor_sha256"] = sha(c.successor)
    write(c.approval, approval)
    repin(c, approval=True)
    with pytest.raises(ValueError):
        append(c)


def test_broken_legacy_prefix_refused_without_repair(tmp_path):
    c = case(tmp_path)
    c.ledger.path.write_bytes(c.prefix.replace(b'"operator":"DS"', b'"operator":"XX"', 1))
    before = c.ledger.path.read_bytes()
    with pytest.raises(ValueError):
        append(c)
    assert c.ledger.path.read_bytes() == before


@pytest.mark.parametrize("session,count", [(date(2026, 10, 30), 10), (date(2026, 11, 2), 9)])
def test_verified_successor_scope_has_no_rename_or_managed_widening(tmp_path, session, count):
    c = case(tmp_path)
    record = append(c)
    source = api().VerifiedMembershipSource(
        c.hashes["membership.json"], c.cal, c.evidence, record.membership_successor_sha256
    )
    selected = source.resolve(c.membership, session, attested_through=session)
    assert len(selected.symbols) == count
    assert ("MFG.AX" in selected.symbols) == (count == 10)
    assert "BJY.AX" not in selected.symbols
    assert selected.base_membership_hash == c.membership.content_hash


def test_post_retirement_missing_or_unbound_successor_refused(tmp_path):
    c = case(tmp_path)
    for source in [
        api().VerifiedMembershipSource(c.hashes["membership.json"], c.cal),
        api().VerifiedMembershipSource(c.hashes["membership.json"], c.cal, c.evidence, None),
    ]:
        with pytest.raises(ValueError):
            source.resolve(c.membership, LAST, attested_through=LAST)


def test_existing_writer_lock_is_not_removed_or_retried(tmp_path):
    c = case(tmp_path)
    lock = c.ledger.path.with_name(c.ledger.path.name + ".writer.lock")
    lock.write_text("another writer")
    with pytest.raises(FileExistsError):
        append(c)
    assert lock.read_text() == "another writer" and c.ledger.path.read_bytes() == c.prefix


def test_changed_tip_after_preview_refuses(tmp_path):
    c = case(tmp_path)
    c.ledger.validate_catchup(FIRST, LAST, c.hashes, **kwargs(c))
    audit = tmp_path / "audit-28.txt"
    audit.write_text("approved ordinary 28 October audit")
    c.ledger.append(
        FIRST,
        c.hashes,
        audit,
        operator="DS",
        recorded_at=datetime.fromisoformat("2026-10-28T16:30:00+11:00"),
        calendar=c.cal,
        base_valid_through=BASE,
    )
    before = c.ledger.path.read_bytes()
    with pytest.raises(ValueError):
        append(c)
    assert c.ledger.path.read_bytes() == before


def load_writer(name):
    import importlib.util
    import sys

    directory = Path(__file__).parents[2] / "scripts"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location("test_" + name, directory / (name + ".py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def writer_args(c):
    args = [
        "--operational-root",
        str(c.ledger.path.parent),
        "--authorities-dir",
        str(c.root),
        "--audit-file",
        str(c.review),
        "--audit-sha256",
        sha(c.review),
        "--catchup-approval-file",
        str(c.approval),
        "--catchup-approval-sha256",
        c.evidence.approval_sha256,
        "--membership-successor-file",
        str(c.successor),
        "--membership-successor-sha256",
        c.evidence.successor_sha256,
    ]
    for name, value in c.hashes.items():
        args.extend(["--" + name.replace(".", "-") + "-sha256", value])
    return args


def test_catchup_and_daily_executable_dryrun_apply_share_all_checks(tmp_path, monkeypatch, capsys):
    import sys

    c = case(tmp_path)
    catchup = load_writer("attest_phase3_authorities_catchup")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(catchup, "datetime", Clock)
    args = writer_args(c) + ["--first-session", str(FIRST), "--last-session", str(LAST)]
    monkeypatch.setattr(sys, "argv", ["catchup", *args])
    assert catchup.main() == 0
    assert c.ledger.path.read_bytes() == c.prefix
    assert json.loads(capsys.readouterr().out)["result"] == "dry_run"
    monkeypatch.setattr(sys, "argv", ["catchup", *args, "--apply"])
    assert catchup.main() == 0
    assert json.loads(capsys.readouterr().out)["result"] == "applied"
    assert len(c.ledger.load(calendar=c.cal, base_valid_through=BASE, verify_evidence=True)) == 3
    daily = load_writer("attest_phase3_authorities")

    class DailyClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat("2026-11-04T16:30:00+11:00")

    monkeypatch.setattr(daily, "datetime", DailyClock)
    audit = tmp_path / "daily4-review.txt"
    audit.write_text("reviewed 4 November")
    args = writer_args(c)
    idx = args.index("--audit-file")
    args[idx + 1] = str(audit)
    idx = args.index("--audit-sha256")
    args[idx + 1] = sha(audit)
    args.extend(
        ["--catchup-audit-file", str(c.review), "--operator", "DS", "--session", "2026-11-04"]
    )
    before = c.ledger.path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["daily", *args])
    assert daily.main() == 0
    assert c.ledger.path.read_bytes() == before
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["daily", *args, "--apply"])
    assert daily.main() == 0
    capsys.readouterr()
    assert c.ledger.require_current(date(2026, 11, 4), c.hashes, c.cal, BASE)


@pytest.mark.parametrize("missing_account", [False, True])
def test_shadow_cli_resolves_once_and_never_retries_a_pass(
    tmp_path, monkeypatch, capsys, missing_account
):
    import sys

    from qat.config import Settings

    c = case(tmp_path)
    append(c)
    mod = load_writer("phase3_shadow_readonly_check")
    stamp = datetime.fromisoformat("2026-11-03T17:45:00+11:00")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return stamp

    monkeypatch.setattr(mod, "datetime", Clock)
    settings = Settings(
        _env_file=None,
        market="ASX",
        broker="ibkr",
        ibkr_account_id="DUFAKE",
        trading_mode="paper",
        execution_mode="recommend",
        phase3_shadow_enabled=True,
        phase3_operational_root=str(c.ledger.path.parent),
        phase3_authorities_dir=str(c.root),
        phase3_catchup_approval_file=str(c.approval),
        phase3_catchup_approval_sha256=c.evidence.approval_sha256,
        phase3_membership_successor_file=str(c.successor),
        phase3_membership_successor_sha256=c.evidence.successor_sha256,
        **{f"phase3_{k.split('.')[0]}_sha256": v for k, v in c.hashes.items()},
    )
    monkeypatch.setattr(mod, "Settings", lambda **kwargs: settings)

    async def account(*args, **kwargs):
        if missing_account:
            return None
        return mod.AccountSnapshot(h.Decimal("100000"), h.Decimal("90000"), stamp)

    monkeypatch.setattr(mod, "read_account_snapshot", account)
    resolutions = []
    requests = []
    passes = []
    actual_resolve = api().VerifiedMembershipSource.resolve

    def resolve(self, *args, **kwargs):
        resolutions.append(1)
        return actual_resolve(self, *args, **kwargs)

    monkeypatch.setattr(api().VerifiedMembershipSource, "resolve", resolve)
    template = h.parse_bar(
        json.loads((Path(__file__).parent / "fixtures" / "bar.json").read_text())
    )

    class Source:
        backfill = ()

        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, day, symbols):
            requests.append(symbols)
            return tuple(
                replace(template, symbol=s, session=day, retrieved_at=stamp) for s in symbols
            )

    actual_pass = mod.run_approved_once

    async def once(*args, **kwargs):
        passes.append(1)
        return await actual_pass(*args, **kwargs, source_factory=Source)

    monkeypatch.setattr(mod, "run_approved_once", once)

    async def forbidden(*args):
        pytest.fail("CLI attempted an unapproved repeat pass")

    monkeypatch.setattr(mod.asyncio, "sleep", forbidden)
    args = [
        "shadow",
        "--session",
        str(LAST),
        "--operational-root",
        str(c.ledger.path.parent),
        "--authorities-dir",
        str(c.root),
    ]
    for name, value in c.hashes.items():
        args.extend(["--" + name.replace(".", "-") + "-sha256", value])
    monkeypatch.setattr(sys, "argv", args)
    if missing_account:
        with pytest.raises(ValueError, match="account snapshot"):
            mod.main()
        assert not passes and not requests and len(resolutions) == 1
        return
    assert mod.main() == 1
    assert len(resolutions) == 1 and len(passes) == 1 and len(requests) == 1
    assert len(requests[0]) == 9 and "MFG.AX" not in requests[0]
    capsys.readouterr()


def test_one_fsync_and_one_success_under_concurrent_attempts(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from qat.operational import authority_attestations as module

    c = case(tmp_path)
    calls = []
    actual_fsync = module.os.fsync

    def counted(fd):
        calls.append(fd)
        actual_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", counted)
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()
        try:
            return append(c).content_hash
        except (ValueError, FileExistsError):
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sum(value is not None for value in results) == 1
    assert len(calls) == 1
    assert len(c.ledger.load(calendar=c.cal, base_valid_through=BASE)) == 3
    assert c.ledger.path.read_bytes().startswith(c.prefix)


def test_evidence_change_between_lock_validations_is_refused(tmp_path, monkeypatch):
    c = case(tmp_path)
    actual = c.ledger.validate_catchup
    count = 0

    def changed(*args, **kwargs):
        nonlocal count
        count += 1
        record = actual(*args, **kwargs)
        if count == 1:
            c.approval.write_bytes(c.approval.read_bytes() + b" ")
        return record

    monkeypatch.setattr(c.ledger, "validate_catchup", changed)
    with pytest.raises(ValueError):
        append(c)
    assert c.ledger.path.read_bytes() == c.prefix
    assert not c.ledger.path.with_name(c.ledger.path.name + ".writer.lock").exists()


def test_nontrading_session_cannot_be_resolved(tmp_path):
    c = case(tmp_path)
    record = append(c)
    source = api().VerifiedMembershipSource(
        c.hashes["membership.json"], c.cal, c.evidence, record.membership_successor_sha256
    )
    with pytest.raises(ValueError, match="ASX session"):
        source.resolve(c.membership, date(2026, 10, 31), attested_through=LAST)


def test_daily_after_retirement_requires_ledger_bound_successor(tmp_path):
    c = case(tmp_path)
    for day in [date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)]:
        audit = tmp_path / f"ordinary-{day}.txt"
        audit.write_text("reviewed ordinary audit")
        c.ledger.append(
            day,
            c.hashes,
            audit,
            operator="DS",
            recorded_at=datetime.combine(day, datetime.min.time(), h.SYDNEY).replace(
                hour=16, minute=30
            ),
            calendar=c.cal,
            base_valid_through=BASE,
        )
    audit = tmp_path / "ordinary-Nov2.txt"
    audit.write_text("no successor has been bound in the ledger")
    before = c.ledger.path.read_bytes()
    with pytest.raises(ValueError, match="successor"):
        c.ledger.validate_append(
            date(2026, 11, 2),
            c.hashes,
            audit,
            operator="DS",
            recorded_at=datetime.fromisoformat("2026-11-02T16:30:00+11:00"),
            calendar=c.cal,
            base_valid_through=BASE,
        )
    assert c.ledger.path.read_bytes() == before


@pytest.mark.parametrize("field", ["signed_at", "expected_ledger_sha256", "operational_root"])
def test_dropped_approval_fields_are_not_silently_accepted(tmp_path, field):
    c = case(tmp_path)
    v = json.loads(c.approval.read_text())
    v[field] = "dropped"
    write(c.approval, v)
    repin(c, approval=True)
    with pytest.raises(ValueError):
        append(c)
    assert c.ledger.path.read_bytes() == c.prefix


def test_duplicate_approval_json_keys_refused(tmp_path):
    c = case(tmp_path)
    raw = c.approval.read_text().strip()
    c.approval.write_text(raw[:-1] + ',"approved_by":"DS"}\n')
    repin(c, approval=True)
    with pytest.raises(ValueError, match="duplicate"):
        append(c)
    assert c.ledger.path.read_bytes() == c.prefix


@pytest.mark.parametrize("fault", ["unknown_type", "extra_field", "truncated"])
def test_range_schema_and_partial_line_are_fail_closed(tmp_path, fault):
    c = case(tmp_path)
    append(c)
    lines = c.ledger.path.read_bytes().splitlines(keepends=True)
    if fault == "truncated":
        c.ledger.path.write_bytes(b"".join(lines)[:-1])
    else:
        row = json.loads(lines[-1])
        if fault == "unknown_type":
            row["record_type"] = "catch_up_v2"
        else:
            row["extra"] = True
        row["content_hash"] = h.digest({k: v for k, v in row.items() if k != "content_hash"})
        lines[-1] = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        c.ledger.path.write_bytes(b"".join(lines))
    before = c.ledger.path.read_bytes()
    with pytest.raises(ValueError):
        c.ledger.load(calendar=c.cal, base_valid_through=BASE)
    assert c.ledger.path.read_bytes() == before


def test_hardlinked_review_is_refused(tmp_path):
    import os

    c = case(tmp_path)
    alias = tmp_path / "linked-review.txt"
    try:
        os.link(c.review, alias)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="private outside-Git"):
        append(c)
    assert c.ledger.path.read_bytes() == c.prefix


def test_writer_rechecks_authority_bytes_after_parsing(tmp_path, monkeypatch):
    c = case(tmp_path)
    daily = load_writer("attest_phase3_authorities")
    original = daily.load_membership

    def changed(path):
        result = original(path)
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(daily, "load_membership", changed)
    with pytest.raises(ValueError, match="changed while loading"):
        daily.validate_inputs(
            LAST,
            c.ledger.path.parent,
            c.root,
            c.hashes,
            c.review,
            sha(c.review),
            NOW,
            evidence=c.evidence,
            catch_up=True,
        )
    assert c.ledger.path.read_bytes() == c.prefix
