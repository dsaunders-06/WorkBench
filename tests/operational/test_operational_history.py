"""Offline tests for the operational history boundary."""

import hashlib
import importlib.util
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
HALT_FIXTURE = FIXTURES / "halts.jsonl"
ACTION_FIXTURE = FIXTURES / "actions.json"


def api():
    from qat.operational import history

    return history


def authorities():
    h = api()
    return h.load_calendar(FIXTURES / "calendar.json"), h.load_membership(
        FIXTURES / "membership.json"
    )


def test_membership_v2_preserves_per_symbol_dates_and_two_issuer_citations(tmp_path):
    h = api()
    stw = "https://www.ssga.com/library-content/products/fund-data/etfs/apac/holdings-daily-au-en-stw.xlsx"
    ioz = "https://www.blackrock.com/au/products/251852/ishares-core-s-p-asx-200-etf/1478358644060.ajax?dataType=fund&fileName=IOZ_holdings&fileType=csv"
    payload = {
        "schema": "asx200-membership-v2",
        "version": 2,
        "published_on": "2026-10-23",
        "valid_through": "2026-10-23",
        "fixture": False,
        "managed_symbols": [],
        "entries": [
            {
                "symbol": symbol,
                "effective_from": "2026-10-21",
                "effective_to": None,
                "citations": [stw, ioz],
            }
            for symbol in ("BHP.AX", "SUN.AX")
        ],
    }
    payload["entries"][1]["effective_to"] = "2026-10-22"
    path = tmp_path / "membership.json"
    path.write_text(json.dumps(payload))
    membership = h.load_membership(path)
    assert membership.symbols == ("BHP.AX", "SUN.AX")
    assert membership.valid_through == date(2026, 10, 23)
    assert membership.is_current("BHP.AX", date(2026, 10, 21))
    assert membership.is_current("BHP.AX", date(2026, 10, 23))
    assert not membership.is_current("SUN.AX", date(2026, 10, 23))
    assert not membership.is_current("BHP.AX", date(2026, 10, 20))
    assert not membership.is_current("BHP.AX", date(2026, 10, 24))
    assert membership.is_current("BHP.AX", date(2026, 10, 26), attested_through=date(2026, 10, 26))
    assert not membership.is_current(
        "SUN.AX", date(2026, 10, 26), attested_through=date(2026, 10, 26)
    )
    quality = h.assess_history(
        "BHP.AX",
        date(2026, 10, 26),
        h.load_calendar(FIXTURES / "calendar.json"),
        membership,
        h.load_halts(HALT_FIXTURE),
        (),
        (),
        attested_through=date(2026, 10, 26),
    )
    assert "membership_stale" not in quality.reasons
    assert membership.entries[0].citations == (stw, ioz)
    payload["entries"][0]["citations"][1] = "https://blackrock.com.evil.test/holdings"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="citation"):
        h.load_membership(path)


@pytest.mark.parametrize(
    ("filename", "loader"),
    [
        ("calendar.json", "load_calendar"),
        ("membership.json", "load_membership"),
        ("actions.json", "load_actions"),
    ],
)
def test_real_json_authorities_require_valid_through(tmp_path, filename, loader):
    h = api()
    payload = json.loads((FIXTURES / filename).read_text())
    payload["fixture"] = False
    path = tmp_path / filename
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="valid_through"):
        getattr(h, loader)(path)


def test_real_halt_validity_is_bound_into_append_chain(tmp_path):
    h = api()
    path = tmp_path / "halts.jsonl"
    missing = {
        "schema": "asx-halts-v1",
        "version": 1,
        "published_on": "2026-10-22",
        "fixture": False,
    }
    path.write_bytes(h.canonical_payload(missing) + b"\n")
    with pytest.raises(ValueError, match="valid_through"):
        h.load_halts(path)
    header = {
        "schema": "asx-halts-v1",
        "version": 1,
        "published_on": "2026-10-22",
        "valid_through": "2026-10-23",
        "fixture": False,
    }
    path.write_bytes(h.canonical_payload(header) + b"\n")
    accepted = h.append_halt(
        path,
        "MFG.AX",
        date(2026, 3, 2),
        date(2026, 3, 2),
        "asx_notice",
        "https://announcements.asx.com.au/asxpdf/20260302/pdf/06wy6h899cx8sz.pdf",
    )
    assert accepted.valid_through == date(2026, 10, 23)
    assert len(h.load_halts(path).entries) == 1
    changed = path.read_text().replace("2026-10-23", "2026-10-24", 1)
    path.write_text(changed)
    with pytest.raises(ValueError, match="broken append chain"):
        h.load_halts(path)


def test_halt_notice_supporting_delivery_is_hash_bound_but_not_an_authority(tmp_path):
    h = api()
    path = tmp_path / "halts.jsonl"
    header = {
        "schema": "asx-halts-v1",
        "version": 1,
        "published_on": "2026-10-23",
        "valid_through": "2026-10-23",
        "fixture": False,
    }
    path.write_bytes(h.canonical_payload(header) + b"\n")
    notice = (
        "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=03066996"
    )
    lift = "https://announcements.asx.com.au/asxpdf/20260303/pdf/06wzyrt8g4hswg.pdf"
    delivery = "https://cdn-api.markitdigital.com/apiman-gateway/ASX/asx-research/1.0/file/2924-03063204-2A1657132%26v%3Dundefined"
    ledger = h.append_halt(
        path,
        "MFG.AX",
        date(2026, 3, 2),
        date(2026, 3, 2),
        "asx_notice",
        notice,
        lift_citation=lift,
        delivery_url=delivery,
        delivery_document_id="2924-03063204-2A1657132",
        delivery_sha256="c3ae734a37752b2790738a3a513ec1644daccb2628ba3dd7f309ba6c53a7e9a2",
    )
    entry = ledger.entries[0]
    assert entry.evidence_reference == notice
    assert entry.lift_citation == lift
    assert entry.delivery_url == delivery
    assert h.load_halts(path).entries[0] == entry
    with pytest.raises(ValueError, match="invalid halt entry"):
        h.append_halt(
            path,
            "SUN.AX",
            date(2026, 3, 3),
            date(2026, 3, 3),
            "asx_notice",
            delivery,
        )
    tampered = path.read_text().replace("c3ae734a", "f3ae734a")
    path.write_text(tampered)
    with pytest.raises(ValueError, match="broken append chain"):
        h.load_halts(path)


def test_action_authority_records_unheld_dividend_scope(tmp_path):
    h = api()
    payload = {
        "schema": "asx-corporate-actions-v2",
        "version": 2,
        "published_on": "2026-10-23",
        "coverage_start": "2023-10-22",
        "coverage_end": "2026-10-23",
        "valid_through": "2026-10-23",
        "source": "https://asxonline.com/public/notices/2025/february/0128.25.02.html",
        "fixture": False,
        "events": [],
        "capital_returns": [],
        "dividend_scope": "unheld_out_of_scope",
    }
    path = tmp_path / "actions.json"
    path.write_text(json.dumps(payload))
    assert h.load_actions(path).dividend_scope == "unheld_out_of_scope"
    payload["dividend_scope"] = "unverified"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid ASX corporate-action authority"):
        h.load_actions(path)


def make_store(tmp_path):
    h = api()
    cal, members = authorities()
    return (
        h.HistoryStore(
            tmp_path / "OPERATIONAL",
            repository_root=Path(__file__).resolve().parents[2],
            protected_roots=(tmp_path / "research", tmp_path / "promotion"),
        ),
        cal,
        members,
    )


def bar(session=date(2026, 1, 6), **changes):
    h = api()
    raw = json.loads((FIXTURES / "bar.json").read_text())
    raw["session"] = session.isoformat()
    raw["retrieved_at"] = session.isoformat() + "T17:30:00+11:00"
    # Retrieval timezone must match the offset, including winter DST.
    from zoneinfo import ZoneInfo

    raw["retrieved_at"] = datetime.combine(
        session, datetime.min.time().replace(hour=17, minute=30), ZoneInfo("Australia/Sydney")
    ).isoformat()
    return replace(h.parse_bar(raw), **changes)


def ingest(store, bars, cal, *, received_at=None):
    receipt = received_at or max(b.retrieved_at for b in bars)
    return store.ingest(bars, cal, received_at=receipt)


def populate(store, cal, *, symbol="BHP.AX", omit=None):
    values = tuple(
        bar(s.session, symbol=symbol)
        for s in cal.sessions
        if s.session <= date(2026, 1, 6) and s.session != omit
    )
    return ingest(store, values, cal)


def test_extra_year_is_recorded_as_dropped_not_as_a_history_block(tmp_path):
    from zoneinfo import ZoneInfo

    from qat.domain.market_calendar import is_trading_day
    from qat.operational.ibkr_history import filter_backfill_to_calendar

    h = api()
    store, original, members = make_store(tmp_path)
    start = date(2023, 10, 22)
    session = date(2026, 10, 23)
    day = start
    sessions = []
    while day <= session:
        if is_trading_day("ASX", day):
            sessions.append(
                h.Session(
                    day,
                    datetime.combine(
                        day, datetime.min.time().replace(hour=10), ZoneInfo("Australia/Sydney")
                    ),
                )
            )
        day += timedelta(days=1)
    cal = replace(
        original,
        coverage_start=start,
        coverage_end=session,
        sessions=tuple(sessions),
        closures=(),
    )
    fetched = (bar(date(2022, 10, 24)),) + tuple(bar(s.session) for s in sessions)

    accepted = filter_backfill_to_calendar(fetched, cal, audit=store.log)
    ingest(store, accepted, cal)
    result = store.check("BHP.AX", session, cal, members, h.load_halts(HALT_FIXTURE))

    assert len(accepted) == len(sessions)
    assert accepted[0].session == sessions[0].session
    with store._connect() as conn:
        events = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM audit")]
    assert not {"ingest_block", "unexpected_session"}.intersection(row["kind"] for row in events)
    assert not {"unexpected_session", "gaps", "three_year_history"}.intersection(result.reasons)
    assert [row for row in events if row["kind"] == "history_before_calendar_dropped"] == [
        {
            "kind": "history_before_calendar_dropped",
            "symbol": "BHP.AX",
            "count": 1,
            "coverage_start": start.isoformat(),
        }
    ]


def test_history_feature_exists():
    assert api().OPERATIONAL == "OPERATIONAL"


def test_append_correction_deadline_and_restart(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    first = ingest(store, (original,), cal)[0]
    deadline = datetime.fromisoformat("2026-01-07T10:00:00+11:00")
    corrected = replace(original, retrieved_at=deadline, finalised=False)
    second = ingest(store, (corrected,), cal)[0]
    late = ingest(
        store, (replace(original, retrieved_at=deadline + timedelta(microseconds=1)),), cal
    )[0]
    assert [r.version for r in store.versions("BHP.AX", original.session)] == [1, 2, 3]
    assert first.accepted and second.accepted and not late.accepted
    assert first.label == "OPERATIONAL" and first.content_hash != second.content_hash
    reopened, _, _ = make_store(tmp_path)
    assert reopened.decision_bars("BHP.AX", original.session)[-1].version == 2
    with sqlite3.connect(store.database) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM bars")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE bars SET version=99")


def test_shadow_freezes_first_final_bar_and_records_every_revision(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    revised_volume = replace(
        original,
        raw=replace(original.raw, volume=original.raw.volume + 1),
        analytical=replace(original.analytical, volume=original.raw.volume + 1),
    )
    store.ingest(
        (revised_volume,), cal, received_at=original.retrieved_at, shadow_freeze_final=True
    )
    assert store.decision_bars("BHP.AX", original.session)[-1].bar.raw == original.raw
    assert store.shadow_revision_pending(("BHP.AX",)) == ()
    severe = replace(
        original,
        raw=replace(original.raw, close=original.raw.close + Decimal("0.01")),
        analytical=replace(original.analytical, close=original.analytical.close + Decimal("0.01")),
    )
    store.ingest((severe,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    assert store.shadow_revision_pending(("BHP.AX",)) == ("BHP.AX",)
    revisions = [json.loads(line) for line in store.audit_bytes().splitlines()]
    assert [event["kind"] for event in revisions] == ["shadow_bar_revision", "shadow_bar_revision"]
    assert revisions[0]["review_required"] is False
    assert revisions[1]["review_required"] is True
    assert [r.accepted for r in store.versions("BHP.AX", original.session)] == [True, False, False]


def test_shadow_backfills_an_older_new_session_without_calling_it_a_revision(tmp_path):
    store, calendar, _ = make_store(tmp_path)
    current = bar(date(2026, 1, 6))
    older = bar(date(2023, 1, 3))
    store.ingest((current,), calendar, received_at=current.retrieved_at, shadow_freeze_final=True)

    stored = store.ingest(
        (older,), calendar, received_at=current.retrieved_at, shadow_freeze_final=True
    )

    assert len(stored) == 1
    assert stored[0].accepted and stored[0].version == 1
    assert store.versions("BHP.AX", date(2023, 1, 3))[0].bar.session == date(2023, 1, 3)
    assert store.versions("BHP.AX", date(2026, 1, 6))[0].accepted
    assert b"shadow_bar_revision" not in store.audit_bytes()


def test_shadow_volume_revision_over_point_one_percent_requires_review(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    increased = original.raw.volume + max(2, original.raw.volume // 100)
    revised = replace(
        original,
        raw=replace(original.raw, volume=increased),
        analytical=replace(original.analytical, volume=increased),
    )
    store.ingest((revised,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    assert store.shadow_revision_pending(("BHP.AX",)) == ("BHP.AX",)


def test_shadow_volume_revision_at_point_one_percent_is_logged_without_abstention(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    increased = original.raw.volume + original.raw.volume // 1000
    revised = replace(
        original,
        raw=replace(original.raw, volume=increased),
        analytical=replace(original.analytical, volume=increased),
    )
    store.ingest((revised,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    assert store.shadow_revision_pending(("BHP.AX",)) == ()
    assert json.loads(store.audit_bytes().splitlines()[-1])["volume_change_percent"] == "0.1"


def test_shadow_analytical_ohlc_revision_alone_requires_review(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    revised = replace(
        original,
        analytical=replace(original.analytical, close=original.analytical.close + Decimal("0.01")),
    )
    store.ingest((revised,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    assert store.shadow_revision_pending(("BHP.AX",)) == ("BHP.AX",)
    event = json.loads(store.audit_bytes().splitlines()[-1])
    assert event["ohlc_changed"] is False
    assert event["analytical_ohlc_changed"] is True


def test_shadow_revision_review_keeps_original_and_clears_only_one_session(tmp_path):
    store, cal, _ = make_store(tmp_path)
    first = bar()
    other = bar(date(2026, 1, 7))
    for original in (first, other):
        store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
        changed = replace(
            original,
            raw=replace(original.raw, close=original.raw.close + Decimal("0.01")),
            analytical=replace(
                original.analytical, close=original.analytical.close + Decimal("0.01")
            ),
        )
        store.ingest((changed,), cal, received_at=changed.retrieved_at, shadow_freeze_final=True)
    revision = store.versions(first.symbol, first.session)[-1]
    reviewed = store.review_shadow_revision(
        first.symbol,
        first.session,
        decision="keep_original",
        expected_revision_hash=revision.content_hash,
        operator="DS",
        reason="ASX announcement and first IBKR bar agree",
        reviewed_at=first.retrieved_at + timedelta(minutes=1),
    )
    assert reviewed.content_hash == store.versions(first.symbol, first.session)[0].content_hash
    assert store.shadow_revision_pending((first.symbol,)) == (first.symbol,)
    events = [json.loads(line) for line in store.audit_bytes().splitlines()]
    assert events[-1]["kind"] == "shadow_bar_revision_review"
    assert events[-1]["operator"] == "DS"
    assert events[-1]["reason"] == "ASX announcement and first IBKR bar agree"
    assert [record.accepted for record in store.versions(first.symbol, first.session)] == [
        True,
        False,
    ]
    assert store.shadow_revision_pending((first.symbol,), sessions=(first.session,)) == ()
    assert store.shadow_revision_pending((first.symbol,), sessions=(other.session,)) == (
        first.symbol,
    )


def test_shadow_revision_review_accepts_exact_bar_and_new_revision_reblocks(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    revised = replace(
        original,
        raw=replace(original.raw, close=original.raw.close + Decimal("0.01")),
        analytical=replace(original.analytical, close=original.analytical.close + Decimal("0.01")),
    )
    observed = store.ingest(
        (revised,), cal, received_at=revised.retrieved_at, shadow_freeze_final=True
    )[0]
    accepted = store.review_shadow_revision(
        original.symbol,
        original.session,
        decision="accept_revised",
        expected_revision_hash=observed.content_hash,
        operator="DS",
        reason="Verified against ASX notice",
        reviewed_at=original.retrieved_at + timedelta(minutes=1),
    )
    assert accepted.accepted
    assert accepted.version == 3
    assert accepted.bar == revised
    assert store.decision_bars(original.symbol, original.session)[-1] == accepted
    assert store.shadow_revision_pending((original.symbol,)) == ()
    restarted, _, _ = make_store(tmp_path)
    assert restarted.decision_bars(original.symbol, original.session)[-1] == accepted
    assert restarted.shadow_revision_pending((original.symbol,)) == ()
    # A repeat observation of the accepted bar is not a new discrepancy.
    store.ingest((revised,), cal, received_at=revised.retrieved_at, shadow_freeze_final=True)
    assert store.shadow_revision_pending((original.symbol,)) == ()
    later = replace(
        revised,
        raw=replace(revised.raw, close=revised.raw.close + Decimal("0.01")),
        analytical=replace(revised.analytical, close=revised.analytical.close + Decimal("0.01")),
    )
    store.ingest((later,), cal, received_at=later.retrieved_at, shadow_freeze_final=True)
    assert store.shadow_revision_pending((original.symbol,)) == (original.symbol,)


def test_shadow_review_clears_all_prior_revisions_but_not_another_symbol(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    peer = replace(original, symbol="CBA.AX")
    for current in (original, peer):
        store.ingest((current,), cal, received_at=current.retrieved_at, shadow_freeze_final=True)
        for cents in ("0.01", "0.02"):
            revised = replace(
                current,
                raw=replace(current.raw, close=current.raw.close + Decimal(cents)),
                analytical=replace(
                    current.analytical, close=current.analytical.close + Decimal(cents)
                ),
            )
            store.ingest(
                (revised,), cal, received_at=revised.retrieved_at, shadow_freeze_final=True
            )
    latest = store.versions(original.symbol, original.session)[-1]
    store.review_shadow_revision(
        original.symbol,
        original.session,
        decision="keep_original",
        expected_revision_hash=latest.content_hash,
        operator="DS",
        reason="Both revisions checked against the primary source",
        reviewed_at=original.retrieved_at + timedelta(minutes=1),
    )
    assert store.shadow_revision_pending((original.symbol, peer.symbol)) == (peer.symbol,)


def test_shadow_revision_review_rejects_stale_hash_or_non_ds_without_write(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    revised = replace(
        original,
        raw=replace(original.raw, close=original.raw.close + Decimal("0.01")),
        analytical=replace(original.analytical, close=original.analytical.close + Decimal("0.01")),
    )
    store.ingest((revised,), cal, received_at=revised.retrieved_at, shadow_freeze_final=True)
    before = (store.audit_bytes(), store.versions(original.symbol, original.session))
    for operator, revision_hash, reason in (
        ("operator", store.versions(original.symbol, original.session)[-1].content_hash, "valid"),
        ("DS", "0" * 64, "valid"),
        ("DS", store.versions(original.symbol, original.session)[-1].content_hash, " "),
    ):
        with pytest.raises(ValueError):
            store.review_shadow_revision(
                original.symbol,
                original.session,
                decision="keep_original",
                expected_revision_hash=revision_hash,
                operator=operator,
                reason=reason,
                reviewed_at=original.retrieved_at + timedelta(minutes=1),
            )
    assert (store.audit_bytes(), store.versions(original.symbol, original.session)) == before


def test_review_script_previews_then_applies_one_decision(tmp_path, capsys):
    script = Path(__file__).resolve().parents[2] / "scripts" / "review_shadow_bar_revision.py"
    spec = importlib.util.spec_from_file_location("review_shadow_bar_revision", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store, cal, _ = make_store(tmp_path)
    original = bar()
    store.ingest((original,), cal, received_at=original.retrieved_at, shadow_freeze_final=True)
    revised = replace(
        original,
        raw=replace(original.raw, close=original.raw.close + Decimal("0.01")),
        analytical=replace(original.analytical, close=original.analytical.close + Decimal("0.01")),
    )
    observed = store.ingest(
        (revised,), cal, received_at=revised.retrieved_at, shadow_freeze_final=True
    )[0]
    args = [
        "--operational-root",
        str(tmp_path / "OPERATIONAL"),
        "--symbol",
        original.symbol,
        "--session",
        original.session.isoformat(),
        "--decision",
        "keep_original",
        "--expected-revision-hash",
        observed.content_hash,
        "--operator",
        "DS",
        "--reason",
        "ASX and IBKR agree with original",
    ]
    before = store.audit_bytes()
    assert module.main(args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["mode"] == "preview"
    assert preview["observed_bar"]["raw"]["close"] == str(revised.raw.close)
    assert store.audit_bytes() == before
    assert module.main([*args, "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["mode"] == "apply" and applied["pending_after"] is False
    assert store.shadow_revision_pending((original.symbol,)) == ()
    with pytest.raises(ValueError, match="no pending revision"):
        module.main([*args, "--apply"])


def test_asx_official_announcement_hosts_and_spoofs(tmp_path):
    h = api()
    for source in (
        "https://www.asx.com.au/markets/",
        "https://asxonline.com/public/notices/2025/february/0128.25.02.html",
        "https://www.asxonline.com/public/notices/2025/february/0128.25.02.html",
        "https://announcements.asx.com.au/asxpdf/20260302/pdf/example.pdf",
    ):
        assert h.is_asx_authority_url(source)
    for source in (
        "http://www.asx.com.au/notices",
        "https://www.asx.com.au.evil.test/notices",
        "https://www.asx.com.au@evil.test/notices",
        "https://company-announcements.afr.com/asx/mfg/notice.pdf",
    ):
        assert not h.is_asx_authority_url(source)


def test_capital_return_authority_is_cited_but_never_adjusts_split_factor(tmp_path):
    h = api()
    payload = json.loads(ACTION_FIXTURE.read_text())
    payload["schema"] = "asx-corporate-actions-v2"
    payload["version"] = 2
    payload["capital_returns"] = [
        {
            "symbol": "SUN.AX",
            "ex_session": "2025-02-17",
            "amount_per_share": "3.00",
            "evidence_reference": "https://asxonline.com/public/notices/2025/february/0128.25.02.html",
        }
    ]
    path = tmp_path / "actions-v2.json"
    path.write_text(json.dumps(payload))
    actions = h.load_actions(path)
    assert actions.capital_returns[0].amount_per_share == Decimal("3.00")
    assert actions.split_events("SUN.AX", date(2025, 2, 18)) == ()
    assert actions.events == ()


def test_complete_history_and_managed_departed_symbol(tmp_path):
    store, cal, members = make_store(tmp_path)
    populate(store, cal)
    assert store.check(
        "BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
    ).eligible
    populate(store, cal, symbol="OLD.AX")
    result = store.check("OLD.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE))
    assert result.eligible and not result.new_cards_allowed
    assert not store.check(
        "UNKNOWN", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
    ).eligible


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"finalised": False}, "not_final"),
        ({"source": "Yahoo"}, "source_not_ibkr"),
        ({"currency": "USD"}, "exchange_currency"),
        ({"actions_verified": False}, "corporate_actions_unverified"),
        ({"dividend": Decimal("-1")}, "dividend_invalid"),
    ],
)
def test_integrity_blocks_bad_symbol(tmp_path, mutation, reason):
    store, cal, members = make_store(tmp_path)
    populate(store, cal)
    ingest(store, (bar(**mutation),), cal)
    result = store.check("BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE))
    assert not result.eligible and reason in result.reasons
    assert reason in store.audit_bytes().decode()


def test_gap_stale_and_insufficient_history(tmp_path):
    store, cal, members = make_store(tmp_path)
    populate(store, cal, omit=date(2025, 12, 30))
    result = store.check("BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE))
    assert "gaps" in result.reasons
    assert (
        "stale_last_session"
        in store.check(
            "BHP.AX", date(2026, 1, 7), cal, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )
    other, _, _ = make_store(tmp_path / "short")
    ingest(other, (bar(),), cal)
    assert (
        "three_year_history"
        in other.check(
            "BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )


@pytest.mark.parametrize("price", ["0.0985", "0.1025", "2.005"])
def test_as_traded_half_asx_step_is_valid_in_each_price_band(price):
    h = api()
    value = Decimal(price)
    prices = h.Ohlcv(value, value, value, value, 1000)
    candidate = replace(bar(), raw=prices, analytical=prices)
    assert "raw_tick_invalid" not in h._bar_reasons(candidate)


@pytest.mark.parametrize("price", ["0.09825", "0.10125", "2.0025", "5.001"])
def test_as_traded_quarter_step_and_other_off_grid_prices_block(price):
    h = api()
    value = Decimal(price)
    prices = h.Ohlcv(value, value, value, value, 1000)
    candidate = replace(bar(), raw=prices, analytical=prices)
    assert "raw_tick_invalid" in h._bar_reasons(candidate)


def test_bad_prices_tick_and_split_dividend_continuity(tmp_path):
    h = api()
    for price, reason in [
        ("0", "ohlcv_invalid"),
        ("5.001", "raw_tick_invalid"),
        ("6", "ohlcv_invalid"),
    ]:
        store, cal, members = make_store(tmp_path / price)
        populate(store, cal)
        bad = replace(bar(), raw=replace(bar().raw, close=Decimal(price)))
        ingest(store, (bad,), cal)
        assert (
            reason
            in store.check(
                "BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
            ).reasons
        )
    store, cal, members = make_store(tmp_path / "split")
    populate(store, cal)
    ingest(store, (replace(bar(), factor=h.SplitFactor(1, 2)),), cal)
    assert (
        "split_price_mismatch"
        in store.check(
            "BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )
    # Dividend-adjusted analytical prices must fail, even if the raw close is valid.
    ingest(
        store,
        (
            replace(
                bar(),
                dividend=Decimal("0.1"),
                analytical=replace(bar().analytical, close=Decimal("4.65")),
            ),
        ),
        cal,
    )
    assert (
        "split_price_mismatch"
        in store.check(
            "BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )


def test_duplicate_order_and_calendar_conflict_block(tmp_path):
    store, cal, members = make_store(tmp_path)
    populate(store, cal)
    ingest(store, (bar(), bar()), cal)
    assert (
        "duplicates"
        in store.check(
            "BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )
    store2, _, _ = make_store(tmp_path / "order")
    ingest(store2, (bar(), bar(date(2026, 1, 5))), cal)
    assert (
        "ordering"
        in store2.check(
            "BHP.AX", date(2026, 1, 6), cal, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )
    store3, _, _ = make_store(tmp_path / "calendar")
    populate(store3, cal)
    changed = replace(
        cal, sessions=tuple(s for s in cal.sessions if s.session != date(2025, 12, 30))
    )
    assert (
        "calendar_conflict"
        in store3.check(
            "BHP.AX", date(2026, 1, 6), changed, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )


def test_namespace_refuses_repo_research_promotion_and_foreign_store(tmp_path):
    h = api()
    repo = Path(__file__).resolve().parents[2]
    for root in (
        repo / "OPERATIONAL",
        tmp_path / "research" / "OPERATIONAL",
        tmp_path / "promotion" / "OPERATIONAL",
    ):
        with pytest.raises(ValueError):
            h.HistoryStore(
                root,
                repository_root=repo,
                protected_roots=(tmp_path / "research", tmp_path / "promotion"),
            )
        assert not root.exists()
    foreign = tmp_path / "foreign" / "OPERATIONAL"
    foreign.mkdir(parents=True)
    (foreign / "history.sqlite3").write_bytes(b"sealed research")
    with pytest.raises(ValueError):
        h.HistoryStore(foreign, repository_root=repo, protected_roots=())
    assert (foreign / "history.sqlite3").read_bytes() == b"sealed research"


def test_authority_loaders_fail_closed(tmp_path):
    h = api()
    raw = json.loads((FIXTURES / "calendar.json").read_text())
    raw["sessions"].append(raw["sessions"][-1])
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        h.load_calendar(path)
    raw = json.loads((FIXTURES / "calendar.json").read_text())
    raw["closures"] = [{"session": "2025-12-30", "notice": ""}]
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        h.load_calendar(path)
    raw = json.loads((FIXTURES / "membership.json").read_text())
    raw["version"] = 0
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        h.load_membership(path)


def test_source_failure_abstains_and_yahoo_never_substitutes(tmp_path):
    h = api()
    store, cal, _ = make_store(tmp_path)
    failure = h.ingest_session(
        store,
        cal,
        date(2026, 1, 6),
        ("BHP.AX",),
        h.FakeIBKRSource((), failure="offline failure"),
        received_at=bar().retrieved_at,
    )
    assert failure.abstained and failure.reasons == ("ibkr_source_failure:offline failure",)

    class Yahoo:
        def compare(self, bars):
            return ("BHP.AX:discrepancy",)

    result = h.ingest_session(
        store,
        cal,
        date(2026, 1, 6),
        ("BHP.AX",),
        h.FakeIBKRSource((bar(),)),
        Yahoo(),
        received_at=bar().retrieved_at,
    )
    assert not result.abstained
    assert "BHP.AX:discrepancy" in store.audit_bytes().decode()
    assert store.decision_bars("BHP.AX", date(2026, 1, 6))[-1].bar.source == "IBKR"


def test_namespace_cannot_be_redirected_after_open(tmp_path):
    store, _, _ = make_store(tmp_path)
    marker = store.database.parent / "namespace.json"
    marker.write_text('{"namespace":"RESEARCH","schema":1}')
    with pytest.raises(ValueError):
        store.decision_bars("BHP.AX", date(2026, 1, 6))


def test_hash_tampering_is_fail_closed(tmp_path):
    store, cal, _ = make_store(tmp_path)
    ingest(store, (bar(),), cal)
    with sqlite3.connect(store.database) as conn:
        conn.execute("DROP TRIGGER bars_no_update")
        conn.execute("UPDATE bars SET hash='corrupt'")
    with pytest.raises(ValueError):
        store.decision_bars("BHP.AX", date(2026, 1, 6))


def test_recorded_split_is_consistent_and_no_float_is_admitted(tmp_path):
    h = api()
    store, cal, members = make_store(tmp_path)
    original = bar()
    half = h.SplitFactor(1, 2)
    adjusted = replace(
        original.analytical,
        open=Decimal("2.25"),
        high=Decimal("2.5"),
        low=Decimal("2"),
        close=Decimal("2.375"),
    )
    records = tuple(
        (
            replace(bar(s.session), factor=half, analytical=adjusted)
            if s.session < original.session
            else replace(
                original,
                raw=replace(
                    original.raw,
                    open=Decimal("2.25"),
                    high=Decimal("2.5"),
                    low=Decimal("2"),
                    close=Decimal("2.375"),
                ),
                analytical=adjusted,
                split_ratio=half,
            )
        )
        for s in cal.sessions
        if s.session <= original.session
    )
    ingest(store, records, cal)
    # 2.375 is a bad raw ASX tick above $2, independently of split continuity.
    assert (
        "split_continuity"
        not in store.check(
            "BHP.AX", original.session, cal, members, api().load_halts(HALT_FIXTURE)
        ).reasons
    )
    with pytest.raises(ValueError):
        replace(original, raw=replace(original.raw, close=4.75))


def test_authority_missing_coverage_and_stale_membership(tmp_path):
    store, cal, members = make_store(tmp_path)
    populate(store, cal)
    assert (
        "membership_stale"
        in store.check(
            "BHP.AX",
            date(2026, 1, 6),
            cal,
            replace(members, effective_to=date(2026, 1, 5)),
            api().load_halts(HALT_FIXTURE),
        ).reasons
    )
    assert (
        "calendar_coverage"
        in store.check(
            "BHP.AX",
            date(2026, 1, 6),
            replace(
                cal,
                coverage_start=date(2023, 1, 7),
                sessions=tuple(s for s in cal.sessions if s.session >= date(2023, 1, 7)),
            ),
            members,
            api().load_halts(HALT_FIXTURE),
        ).reasons
    )


def test_missing_source_bars_record_symbol_reason_even_when_history_exists(tmp_path):
    h = api()
    store, cal, _ = make_store(tmp_path)
    populate(store, cal)
    result = h.ingest_session(
        store,
        cal,
        date(2026, 1, 6),
        ("BHP.AX",),
        h.FakeIBKRSource(()),
        received_at=bar().retrieved_at,
    )
    assert not result.abstained
    assert result.reasons == ("BHP.AX:missing",)


def test_complete_three_year_window_when_anniversary_is_weekend(tmp_path):
    store, cal, members = make_store(tmp_path)
    values = tuple(
        bar(s.session) for s in cal.sessions if date(2023, 1, 9) <= s.session <= date(2026, 1, 7)
    )
    ingest(store, values, cal)
    assert store.check(
        "BHP.AX", date(2026, 1, 7), cal, members, api().load_halts(HALT_FIXTURE)
    ).eligible


def test_calendar_rejects_non_asx_authority(tmp_path):
    h = api()
    raw = json.loads((FIXTURES / "calendar.json").read_text())
    raw["source"] = "https://example.com/untrusted-calendar"
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        h.load_calendar(path)


def test_test_network_guard_denies_external_and_loopback_connections():
    import socket

    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="network access"):
            sock.connect(("127.0.0.1", 7497))
    with pytest.raises(AssertionError, match="network access"):
        socket.getaddrinfo("vendor.invalid", 443)


def test_correction_uses_receipt_time_not_vendor_retrieval_time(tmp_path):
    store, cal, _ = make_store(tmp_path)
    original = bar()
    deadline = datetime.fromisoformat("2026-01-07T10:00:00+11:00")
    ingest(store, (original,), cal)
    late = ingest(
        store,
        (replace(original, finalised=False),),
        cal,
        received_at=deadline + timedelta(seconds=1),
    )[0]
    assert not late.accepted
    assert store.decision_bars("BHP.AX", original.session)[-1].bar.finalised


def test_halt_authority_appends_without_rewriting_and_rejects_tampering(tmp_path):
    h = api()
    path = tmp_path / "halts.jsonl"
    path.write_bytes(HALT_FIXTURE.read_bytes())
    original = path.read_bytes()
    first = h.append_halt(
        path,
        "OLD.AX",
        date(2025, 12, 30),
        date(2025, 12, 30),
        "asx_notice",
        "https://www.asx.com.au/fixture/halt-123",
    )
    assert path.read_bytes().startswith(original)
    assert first.entries[0].symbol == "OLD.AX"
    second = h.append_halt(
        path,
        "BHP.AX",
        date(2026, 1, 6),
        date(2026, 1, 6),
        "broker_record",
        "IBKR:fixture-record-42",
        interruption_type="suspension",
    )
    assert second.entries[1].interruption_type == "suspension"
    assert second.entries[1].previous_hash == first.entries[0].content_hash
    with pytest.raises(ValueError):
        h.append_halt(
            path,
            "OLD.AX",
            date(2025, 12, 30),
            date(2025, 12, 30),
            "asx_notice",
            "https://www.asx.com.au/fixture/duplicate",
        )
    altered = path.read_text().replace("fixture-record-42", "fixture-record-43")
    path.write_text(altered)
    with pytest.raises(ValueError):
        h.load_halts(path)
    path.write_text(
        altered.replace("fixture-record-43", "fixture-record-42").replace(
            '"published_on":"2026-01-06"', '"published_on":"2026-01-07"'
        )
    )
    with pytest.raises(ValueError):
        h.load_halts(path)


def test_store_rejects_halt_ledger_truncation_and_fork_across_restart(tmp_path):
    h = api()
    store, cal, members = make_store(tmp_path)
    path = tmp_path / "halts.jsonl"
    path.write_bytes(HALT_FIXTURE.read_bytes())
    empty = h.load_halts(path)
    store.accept_halts(empty)
    first = h.append_halt(
        path,
        "OLD.AX",
        date(2025, 12, 30),
        date(2025, 12, 30),
        "asx_notice",
        "https://www.asx.com.au/fixture/halt-123",
    )
    store.accept_halts(first)
    restarted = h.HistoryStore(
        store.database.parent,
        repository_root=Path(__file__).resolve().parents[2],
        protected_roots=(tmp_path / "research", tmp_path / "promotion"),
    )
    with pytest.raises(ValueError, match="halt ledger rollback"):
        restarted.accept_halts(empty)
    fork_path = tmp_path / "fork.jsonl"
    fork_path.write_bytes(HALT_FIXTURE.read_bytes())
    fork = h.append_halt(
        fork_path,
        "OLD.AX",
        date(2025, 12, 30),
        date(2025, 12, 30),
        "broker_record",
        "IBKR:different-record",
    )
    with pytest.raises(ValueError, match="halt ledger rollback"):
        restarted.accept_halts(fork)
    extension = h.append_halt(
        path,
        "BHP.AX",
        date(2026, 1, 6),
        date(2026, 1, 6),
        "broker_record",
        "IBKR:fixture-record-42",
    )
    restarted.accept_halts(extension)
    with sqlite3.connect(store.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM halt_acceptance").fetchone()[0] == 3
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM halt_acceptance")


def test_asx_action_authority_and_exact_derived_raw(tmp_path):
    h = api()
    actions = h.load_actions(ACTION_FIXTURE)
    assert actions.schema == "asx-corporate-actions-v1"
    assert actions.events == ()
    analytical = h.Ohlcv(Decimal("2.3765"), Decimal("2.5"), Decimal("2.25"), Decimal("2.4"), 100000)
    derived = h.derive_pre_split_bar(bar(date(2025, 12, 1)), analytical, h.SplitFactor(1, 2))
    assert derived.raw_provenance == "DERIVED"
    assert derived.raw.open == Decimal("4.753")
    assert derived.raw.volume == 50000
    assert derived.raw.open % h.tick_size(derived.raw.open, "ASX") != 0
    assert "raw_tick_invalid" not in h._bar_reasons(derived)
    assert "inverse_non_exact" not in h._bar_reasons(derived)
    with pytest.raises(ValueError, match="inverse_non_exact"):
        h.derive_pre_split_bar(
            bar(date(2025, 12, 1)), replace(analytical, volume=100001), h.SplitFactor(1, 2)
        )


def test_sun_fractional_analytical_volume_is_exact_and_round_trips(tmp_path):
    h = api()
    analytical = h.Ohlcv(
        Decimal("23.393"),
        Decimal("23.722"),
        Decimal("23.276"),
        Decimal("23.452"),
        Decimal("2658069.5589"),
    )
    derived = h.derive_pre_split_bar(
        bar(date(2025, 2, 14), symbol="SUN.AX"), analytical, h.SplitFactor(10000, 8511)
    )
    assert derived.raw_provenance == "DERIVED"
    assert derived.raw.volume == 3123099
    assert derived.analytical.volume == Decimal("2658069.5589")
    engine_adjusted = h.to_engine_adjusted(derived)
    assert engine_adjusted.volume == 2658070
    assert type(engine_adjusted.volume) is int
    assert derived.raw.volume == 3123099
    assert derived.analytical.volume == Decimal("2658069.5589")
    assert "inverse_non_exact" not in h._bar_reasons(derived)
    assert "raw_tick_invalid" not in h._bar_reasons(derived)
    assert json.loads(h._bar_payload(derived))["analytical"]["volume"] == "2658069.5589"

    store, cal, _ = make_store(tmp_path)
    saved = ingest(store, (derived,), cal)[0]
    loaded = store.versions("SUN.AX", date(2025, 2, 14))[0]
    assert loaded.content_hash == saved.content_hash
    assert loaded.bar.analytical.volume == Decimal("2658069.5589")
    assert h._bar_payload(loaded.bar) == h._bar_payload(derived)

    with pytest.raises(ValueError, match="inverse_non_exact"):
        h.derive_pre_split_bar(
            bar(date(2025, 2, 14), symbol="SUN.AX"),
            replace(analytical, volume=2658070),
            h.SplitFactor(10000, 8511),
        )
    with pytest.raises(ValueError, match="inverse_non_exact"):
        h.derive_pre_split_bar(
            bar(date(2025, 2, 14), symbol="SUN.AX"),
            replace(analytical, volume=Decimal("1.5")),
            h.SplitFactor(10000, 8511),
        )


def test_fractional_volume_rejected_for_as_traded_and_binary_float():
    h = api()
    value = bar()
    with pytest.raises(ValueError):
        replace(value, analytical=replace(value.analytical, volume=Decimal("2.5")))
    with pytest.raises(ValueError):
        replace(value, analytical=replace(value.analytical, volume=2.5))
    fixture = json.loads((FIXTURES / "bar.json").read_text())
    fixture["analytical"]["volume"] = "2.5"
    with pytest.raises(ValueError):
        h.parse_bar(fixture)
    fixture["raw_provenance"] = "DERIVED"
    parsed = h.parse_bar(fixture)
    assert parsed.analytical.volume == Decimal("2.5")
    fixture["analytical"]["volume"] = 2.5
    with pytest.raises(ValueError):
        h.parse_bar(fixture)


def test_existing_as_traded_payload_hash_is_unchanged():
    h = api()
    fixture = json.loads((FIXTURES / "bar.json").read_text())
    payload = h._bar_payload(h.parse_bar(fixture))
    assert hashlib.sha256(payload).hexdigest() == (
        "f3a9f81a37204f311e3142bb7ea611d8ada594c2ef786b8902d2974a0c44059d"
    )


@pytest.mark.parametrize(
    ("volume", "factor", "expected"),
    [
        ("2.5", (2, 5), 2),
        ("3.5", (2, 7), 4),
    ],
)
def test_engine_adjusted_volume_uses_half_even_at_ties(volume, factor, expected):
    h = api()
    analytical = h.Ohlcv(
        Decimal("2.4"), Decimal("2.5"), Decimal("2.25"), Decimal("2.4"), Decimal(volume)
    )
    derived = h.derive_pre_split_bar(bar(), analytical, h.SplitFactor(*factor))
    assert derived.raw.volume == 1
    assert h.to_engine_adjusted(derived).volume == expected


@pytest.mark.parametrize("volume", ["NaN", "Infinity", "0", "-1"])
def test_fractional_derived_volume_must_be_finite_and_positive(volume):
    h = api()
    fixture = json.loads((FIXTURES / "bar.json").read_text())
    fixture["raw_provenance"] = "DERIVED"
    fixture["analytical"]["volume"] = volume
    with pytest.raises((ValueError, TypeError)):
        h.parse_bar(fixture)


def test_derived_bar_with_inexact_inverse_blocks_symbol(tmp_path):
    h = api()
    store, cal, members = make_store(tmp_path)
    populate(store, cal)
    bad = replace(
        bar(date(2025, 12, 1)),
        analytical=h.Ohlcv(
            Decimal("2.375"), Decimal("2.5"), Decimal("2.25"), Decimal("2.4"), 100001
        ),
        raw=h.Ohlcv(Decimal("4.75"), Decimal("5"), Decimal("4.5"), Decimal("4.8"), 50000),
        factor=h.SplitFactor(1, 2),
        raw_provenance="DERIVED",
    )
    ingest(store, (bad,), cal)
    result = store.check("BHP.AX", date(2026, 1, 6), cal, members, h.load_halts(HALT_FIXTURE))
    assert not result.eligible and "inverse_non_exact" in result.reasons


def test_real_action_authority_requires_derived_pre_split_bars_and_exact_ex_date(tmp_path):
    h = api()
    store, cal, members = make_store(tmp_path)
    populate(store, cal)
    sessions = [s.session for s in cal.sessions if s.session <= date(2026, 1, 6)]
    event = h.CorporateAction(
        "BHP.AX",
        sessions[-22],
        h.SplitFactor(1, 2),
        Decimal("0.25"),
        "https://www.asx.com.au/markets/trade-our-cash-market/announcements",
    )
    authority = replace(h.load_actions(ACTION_FIXTURE), fixture=False, events=(event,))
    result = store.check(
        "BHP.AX", date(2026, 1, 6), cal, members, h.load_halts(HALT_FIXTURE), authority
    )
    assert not result.eligible
    assert "corporate_action_factor_mismatch" in result.reasons
    assert "corporate_action_ex_date_mismatch" in result.reasons
    short = replace(authority, coverage_start=date(2024, 1, 1))
    assert (
        "corporate_action_coverage"
        in store.check(
            "BHP.AX", date(2026, 1, 6), cal, members, h.load_halts(HALT_FIXTURE), short
        ).reasons
    )


def test_real_action_authority_accepts_complete_exact_split_history(tmp_path):
    h = api()
    store, cal, members = make_store(tmp_path)
    sessions = [s.session for s in cal.sessions if s.session <= date(2026, 1, 6)]
    ex_session = sessions[-22]
    ratio = h.SplitFactor(1, 2)
    event = h.CorporateAction(
        "BHP.AX",
        ex_session,
        ratio,
        Decimal("0.25"),
        "https://www.asx.com.au/markets/trade-our-cash-market/announcements",
    )
    authority = replace(h.load_actions(ACTION_FIXTURE), fixture=False, events=(event,))
    values = []
    for session in sessions:
        value = bar(session)
        if session < ex_session:
            value = h.derive_pre_split_bar(value, value.analytical, ratio)
        elif session == ex_session:
            value = replace(value, split_ratio=ratio, dividend=Decimal("0.25"))
        values.append(value)
    ingest(store, tuple(values), cal)
    result = store.check(
        "BHP.AX", date(2026, 1, 6), cal, members, h.load_halts(HALT_FIXTURE), authority
    )
    assert result.eligible and result.reasons == ()


def test_only_ibkr_trades_series_is_valid(tmp_path):
    h = api()
    store, cal, members = make_store(tmp_path)
    populate(store, cal)
    ingest(store, (replace(bar(), series="ADJUSTED_LAST"),), cal)
    result = store.check("BHP.AX", date(2026, 1, 6), cal, members, h.load_halts(HALT_FIXTURE))
    assert "series_not_trades" in result.reasons


def test_documented_history_halt_is_not_gap_even_for_managed_symbol(tmp_path):
    h = api()
    store, cal, members = make_store(tmp_path)
    gap = date(2025, 12, 30)
    populate(store, cal, symbol="OLD.AX", omit=gap)
    path = tmp_path / "halts.jsonl"
    path.write_bytes(HALT_FIXTURE.read_bytes())
    ledger = h.append_halt(
        path,
        "OLD.AX",
        gap,
        gap,
        "broker_record",
        "IBKR:fixture-halt-19",
    )
    result = store.check("OLD.AX", date(2026, 1, 6), cal, members, ledger)
    assert result.eligible and not result.new_cards_allowed
    assert "gaps" not in result.reasons
    assert "stale_last_session" not in result.reasons
    separate_store, _, _ = make_store(tmp_path / "undocumented")
    populate(separate_store, cal, symbol="OLD.AX", omit=gap)
    without_notice = separate_store.check(
        "OLD.AX", date(2026, 1, 6), cal, members, h.load_halts(HALT_FIXTURE)
    )
    assert "gaps" in without_notice.reasons


def test_partial_ibkr_fetch_records_symbol_gap_not_session_failure(tmp_path):
    h = api()
    store, cal, _ = make_store(tmp_path)
    populate(store, cal, symbol="BHP.AX")
    result = h.ingest_session(
        store,
        cal,
        date(2026, 1, 6),
        ("BHP.AX", "NEW.AX"),
        h.FakeIBKRSource((bar(),)),
        received_at=bar().retrieved_at,
    )
    assert not result.abstained
    assert b'"status":"partial"' in store.audit_bytes()
    assert b'"kind":"source_failure"' not in store.audit_bytes()
