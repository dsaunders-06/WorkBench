"""Offline adapter behavior over frozen operational inputs and real pure engine."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from test_operational_history import bar, ingest, make_store, populate

SESSION = date(2026, 1, 6)
NOW = datetime.fromisoformat("2026-01-06T17:30:00+11:00")


def api():
    from qat.operational import adapter

    return adapter


def prepared(tmp_path, *, qualified=False, managed=True):
    h = __import__("qat.operational.history", fromlist=["history"])
    store, cal, members = make_store(tmp_path)
    if qualified:
        values = []
        for i, s in enumerate(cal.sessions):
            if s.session > SESSION:
                continue
            close = Decimal("10") + Decimal(i) / 1000
            analytical = h.Ohlcv(
                close - Decimal(".004"),
                close + Decimal(".002"),
                close - Decimal(".012"),
                close,
                100000,
            )
            raw = h.Ohlcv(
                *(
                    x * 10
                    for x in (analytical.open, analytical.high, analytical.low, analytical.close)
                ),
                100000,
            )
            values.append(
                replace(bar(s.session), raw=raw, analytical=analytical, factor=h.SplitFactor(1, 10))
            )
        ingest(store, tuple(values), cal)
    else:
        populate(store, cal)
    if managed:
        populate(store, cal, symbol="OLD.AX")
    else:
        members = replace(members, managed_symbols=())
    a = api()
    costs = a.ExactCostProfile(
        "fixture-v1", "fixture zero costs", Decimal(0), Decimal(0), "AUD", False, Decimal(0)
    )
    liquidity = a.LiquidityProfile("fixture-v1", Decimal(".1"), Decimal(0), Decimal(0))
    adapter = a.OperationalAdapter(store, cal, members)
    parameters = a.EvaluationParameters(Decimal("100000"), Decimal("100000"), costs, liquidity)
    snapshot = adapter.freeze(SESSION, parameters)
    return adapter, snapshot, store, cal, members, parameters


def test_adapter_feature_exists():
    assert api().LABEL == "unvalidated strategy, no demonstrated edge"


@pytest.mark.parametrize(
    "now", [NOW - timedelta(microseconds=1), datetime.fromisoformat("2026-01-06T06:29:59+00:00")]
)
def test_before_1730_sydney_refuses_engine(tmp_path, now, monkeypatch):
    a, snapshot, *_ = prepared(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("engine called before finality")

    monkeypatch.setattr(api().AuthoritativeSwingEngine, "evaluate", forbidden)
    result = a.run(snapshot, now=now)
    assert not result.candidates
    assert result.abstentions[0].reasons == ("before_1730_sydney",)


def test_all_required_bars_must_be_final(tmp_path, monkeypatch):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True)
    ingest(store, (bar(finalised=False, symbol="OLD.AX"),), cal)
    snapshot = a.freeze(SESSION, params)

    def forbidden(*args, **kwargs):
        raise AssertionError("engine called with unfinished required bar")

    monkeypatch.setattr(api().AuthoritativeSwingEngine, "evaluate", forbidden)
    result = a.run(snapshot, now=NOW)
    assert not result.candidates
    assert any("required_bars_not_final" in r.reasons for r in result.abstentions)


def test_qualified_real_engine_candidate_has_evidence_expiry_and_label(tmp_path):
    a, snapshot, *_ = prepared(tmp_path, qualified=True)
    result = a.run(snapshot, now=NOW)
    assert len(result.candidates) == 1
    card = result.candidates[0]
    assert card.symbol == "BHP.AX" and card.session == SESSION
    assert card.label == "unvalidated strategy, no demonstrated edge"
    assert card.expires_at == datetime.fromisoformat("2026-01-07T10:00:00+11:00")
    assert isinstance(card.entry_limit_raw, Decimal)
    assert card.structural_stop_raw < card.entry_limit_raw
    assert card.evidence.pattern_decisions and card.evidence.setup_rules
    assert card.evidence.quantity > 0
    assert card.source_records[-1].version == 1 and len(card.source_records[-1].content_hash) == 64
    assert all(r.label == "OPERATIONAL" for r in card.source_records)
    assert card.snapshot_hash == snapshot.content_hash
    with pytest.raises(FrozenInstanceError):
        card.label = "validated"
    assert any(
        r.symbol == "OLD.AX" and "departed_managed_symbol" in r.reasons for r in result.abstentions
    )


def test_frozen_snapshot_ignores_later_corrections_and_changes_hash_for_new_snapshot(tmp_path):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True)
    before = a.run(snapshot, now=NOW).to_bytes()
    record = store.decision_bars("BHP.AX", SESSION)[-1]
    corrected = replace(record.bar, finalised=False, retrieved_at=NOW + timedelta(minutes=1))
    ingest(store, (corrected,), cal)
    assert a.run(snapshot, now=NOW).to_bytes() == before
    newer = a.freeze(SESSION, params)
    assert newer.content_hash != snapshot.content_hash
    assert not a.run(newer, now=NOW + timedelta(minutes=1)).candidates


def test_byte_determinism_across_decimal_contexts(tmp_path):
    a, snapshot, *_ = prepared(tmp_path, qualified=True)
    with localcontext() as ctx:
        ctx.prec = 6
        left = a.run(snapshot, now=NOW).to_bytes()
    with localcontext() as ctx:
        ctx.prec = 60
        right = a.run(snapshot, now=NOW + timedelta(minutes=1)).to_bytes()
    assert left == right
    assert (
        json.loads(left)["candidates"][0]["label"] == "unvalidated strategy, no demonstrated edge"
    )


def test_abstention_and_blocked_symbols_create_no_candidate(tmp_path):
    a, snapshot, store, cal, members, params = prepared(tmp_path, managed=False)
    result = a.run(snapshot, now=NOW)
    assert not result.candidates and result.abstentions
    assert "adapter_abstention" in store.audit_bytes().decode()
    ingest(store, (bar(actions_verified=False),), cal)
    result = a.run(a.freeze(SESSION, params), now=NOW)
    assert not result.candidates
    assert "corporate_actions_unverified" in result.abstentions[0].reasons


def test_source_failure_blocks_even_with_previous_final_bar(tmp_path):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True, managed=False)
    h = __import__("qat.operational.history", fromlist=["history"])
    h.ingest_session(
        store,
        cal,
        SESSION,
        ("BHP.AX",),
        h.FakeIBKRSource((), failure="unavailable"),
        received_at=NOW,
    )
    result = a.run(a.freeze(SESSION, params), now=NOW)
    assert not result.candidates
    assert "ibkr_source_failure" in result.abstentions[0].reasons


def test_invalid_time_expiry_unknown_session_and_tampered_snapshot(tmp_path):
    a, snapshot, *_ = prepared(tmp_path, qualified=True)
    with pytest.raises(ValueError):
        a.run(snapshot, now=datetime(2026, 1, 6, 17, 30))
    expired = a.run(snapshot, now=datetime.fromisoformat("2026-01-07T10:00:00+11:00"))
    assert not expired.candidates and expired.abstentions[0].reasons == ("session_expired",)
    tampered = replace(snapshot, content_hash="wrong")
    result = a.run(tampered, now=NOW)
    assert not result.candidates and result.abstentions[0].reasons == ("snapshot_hash_mismatch",)


def test_hash_corrupt_store_abstains(tmp_path):
    a, snapshot, store, cal, members, params = prepared(tmp_path)
    import sqlite3

    with sqlite3.connect(store.database) as conn:
        conn.execute("DROP TRIGGER bars_no_update")
        conn.execute("UPDATE bars SET hash='bad'")
    result = a.run(a.freeze(SESSION, params), now=NOW)
    assert not result.candidates and result.abstentions[0].reasons == ("store_integrity_failure",)


def test_required_history_gap_blocks_only_affected_symbol_after_finality(tmp_path):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True, managed=False)
    members = replace(members, symbols=("BHP.AX", "NEW.AX"))
    populate(store, cal, symbol="NEW.AX", omit=date(2025, 12, 30))
    a = api().OperationalAdapter(store, cal, members)
    result = a.run(a.freeze(SESSION, params), now=NOW)
    assert [c.symbol for c in result.candidates] == ["BHP.AX"]
    assert result.abstentions[0].symbol == "NEW.AX" and "gaps" in result.abstentions[0].reasons


def test_session_outside_calendar_and_missing_next_open_abstain(tmp_path):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True, managed=False)
    unknown = a.freeze(date(2026, 1, 8), params)
    result = a.run(unknown, now=datetime.fromisoformat("2026-01-08T17:30:00+11:00"))
    assert not result.candidates
    assert result.abstentions[0].reasons == ("calendar_session_or_next_open_missing",)
    last = a.freeze(date(2026, 1, 7), params)
    result = a.run(last, now=datetime.fromisoformat("2026-01-07T17:30:00+11:00"))
    assert not result.candidates
    assert result.abstentions[0].reasons == ("calendar_session_or_next_open_missing",)


def test_engine_failure_is_a_recorded_deterministic_abstention(tmp_path, monkeypatch):
    a, snapshot, *_ = prepared(tmp_path, qualified=True, managed=False)

    def failing(*args, **kwargs):
        raise ArithmeticError("fixture failure")

    monkeypatch.setattr(api().AuthoritativeSwingEngine, "evaluate", failing)
    result = a.run(snapshot, now=NOW)
    assert not result.candidates
    assert result.abstentions[0].reasons == ("engine_failure:ArithmeticError",)
    assert result.to_bytes() == a.run(snapshot, now=NOW).to_bytes()


def test_snapshot_read_is_frozen_before_later_source_failure(tmp_path, monkeypatch):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True, managed=False)
    original = store._decode
    fired = False

    def interleaved(row):
        nonlocal fired
        if not fired:
            fired = True
            store.log(
                {"kind": "source_failure", "session": SESSION.isoformat(), "result": "late failure"}
            )
        return original(row)

    monkeypatch.setattr(store, "_decode", interleaved)
    old = a.freeze(SESSION, params)
    assert not old.source_failed
    assert a.freeze(SESSION, params).source_failed
    assert len(a.run(old, now=NOW).candidates) == 1


def test_non_decimal_parameters_are_refused(tmp_path):
    a, snapshot, *_ = prepared(tmp_path, managed=False)
    with pytest.raises(ValueError):
        replace(snapshot.parameters, equity=100000.0)


def test_unfinished_required_symbol_has_its_own_recorded_reason(tmp_path):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True)
    ingest(store, (bar(symbol="OLD.AX", finalised=False),), cal)
    result = a.run(a.freeze(SESSION, params), now=NOW)
    assert not result.candidates
    assert any(r.symbol == "OLD.AX" and "not_final" in r.reasons for r in result.abstentions)


@pytest.mark.parametrize("recovery_symbols", [("OLD.AX",), ()])
def test_source_failure_cannot_be_cleared_by_an_unrelated_success(tmp_path, recovery_symbols):
    a, snapshot, store, cal, members, params = prepared(tmp_path, qualified=True)
    h = __import__("qat.operational.history", fromlist=["history"])
    h.ingest_session(
        store,
        cal,
        SESSION,
        ("BHP.AX",),
        h.FakeIBKRSource((), failure="BHP failure"),
        received_at=NOW,
    )
    values = (bar(symbol="OLD.AX"),) if recovery_symbols else ()
    h.ingest_session(
        store, cal, SESSION, recovery_symbols, h.FakeIBKRSource(values), received_at=NOW
    )
    result = a.run(a.freeze(SESSION, params), now=NOW)
    assert not result.candidates
    assert "ibkr_source_failure" in result.abstentions[0].reasons
