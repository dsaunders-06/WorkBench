"""Offline tests for the operational history boundary."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
HALT_FIXTURE = FIXTURES / "halts.jsonl"


def api():
    from qat.operational import history

    return history


def authorities():
    h = api()
    return h.load_calendar(FIXTURES / "calendar.json"), h.load_membership(
        FIXTURES / "membership.json"
    )


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
    without_notice = store.check(
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
