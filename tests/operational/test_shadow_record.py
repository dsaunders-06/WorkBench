"""The Phase 3 shadow trail cannot silently overwrite cards or abstentions."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from qat.config import Settings
from qat.operational import history as h
from qat.operational.shadow import Phase3ShadowRunner, ShadowRecord

FIXTURES = Path(__file__).parent / "fixtures"


def test_cards_and_abstentions_append_and_verify_after_restart(tmp_path):
    path = tmp_path / "OPERATIONAL" / "shadow.jsonl"
    path.parent.mkdir()
    first = ShadowRecord(path)
    card = first.append("card", date(2026, 10, 21), {"symbol": "BHP.AX", "quantity": 0})
    refusal = first.append(
        "abstention", date(2026, 10, 21), {"symbol": "MFG.AX", "reasons": ["not_final"]}
    )
    restarted = ShadowRecord(path)
    assert [event["kind"] for event in restarted.events] == ["card", "abstention"]
    assert refusal["previous_hash"] == card["content_hash"]
    assert restarted.events[-1]["content_hash"] == refusal["content_hash"]


def test_shadow_record_refuses_truncated_or_changed_chain(tmp_path):
    path = tmp_path / "OPERATIONAL" / "shadow.jsonl"
    path.parent.mkdir()
    record = ShadowRecord(path)
    record.append("abstention", date(2026, 10, 21), {"reason": "source_missing"})
    row = json.loads(path.read_text())
    row["detail"]["reason"] = "fabricated"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="shadow chain"):
        ShadowRecord(path)


@pytest.mark.asyncio
async def test_shadow_run_uses_adapter_and_records_missing_history_abstention(
    tmp_path, monkeypatch
):
    authorities = tmp_path / "authorities"
    authorities.mkdir()
    for filename in ("calendar.json", "membership.json", "actions.json"):
        payload = json.loads((FIXTURES / filename).read_text())
        payload["fixture"] = False
        if filename == "membership.json":
            payload["managed_symbols"] = []
        (authorities / filename).write_text(json.dumps(payload))
    (authorities / "halts.jsonl").write_text(
        json.dumps(
            {
                "schema": "asx-halts-v1",
                "version": 1,
                "published_on": "2026-01-06",
                "fixture": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    raw = json.loads((FIXTURES / "bar.json").read_text())
    bar = h.parse_bar(raw)

    class OfflineSource:
        backfill = ()

        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, session, symbols):
            assert session == date(2026, 1, 6)
            assert symbols == ("BHP.AX",)
            return (bar,)

    monkeypatch.setattr("qat.operational.shadow.IBKRHistoricalBarSource", OfflineSource)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market_data_source="yfinance",
        fundamentals_source="yfinance",
        phase3_shadow_enabled=True,
        phase3_operational_root=str(tmp_path / "OPERATIONAL"),
        phase3_authorities_dir=str(authorities),
    )

    class OfflineBroker:
        async def account(self):
            return SimpleNamespace(net_liquidation=100000.0, cash=100000.0)

    broker = OfflineBroker()
    runner = Phase3ShadowRunner(
        settings,
        broker,
        object(),
        now=lambda: datetime.fromisoformat("2026-01-06T17:30:00+11:00"),
    )
    assert await runner.run_once(date(2026, 1, 6)) is False
    events = ShadowRecord(tmp_path / "OPERATIONAL" / "shadow.jsonl").events
    assert events and events[-1]["kind"] == "abstention"
    assert "three_year_history" in str(events[-1]["detail"])


@pytest.mark.asyncio
async def test_shadow_abstains_on_revised_final_ohlc_and_keeps_first_bar(tmp_path, monkeypatch):
    authorities = tmp_path / "authorities"
    authorities.mkdir()
    for filename in ("calendar.json", "membership.json", "actions.json"):
        payload = json.loads((FIXTURES / filename).read_text())
        payload["fixture"] = False
        if filename == "membership.json":
            payload["managed_symbols"] = []
        (authorities / filename).write_text(json.dumps(payload))
    (authorities / "halts.jsonl").write_text(
        json.dumps(
            {
                "schema": "asx-halts-v1",
                "version": 1,
                "published_on": "2026-01-06",
                "fixture": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    original = h.parse_bar(json.loads((FIXTURES / "bar.json").read_text()))
    next_bar = {"value": original}

    class OfflineSource:
        backfill = ()

        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, _session, _symbols):
            return (next_bar["value"],)

    monkeypatch.setattr("qat.operational.shadow.IBKRHistoricalBarSource", OfflineSource)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        phase3_shadow_enabled=True,
        phase3_operational_root=str(tmp_path / "OPERATIONAL"),
        phase3_authorities_dir=str(authorities),
    )

    class OfflineBroker:
        async def account(self):
            return SimpleNamespace(net_liquidation=0.0, cash=0.0)

    runner = Phase3ShadowRunner(
        settings,
        OfflineBroker(),
        object(),
        now=lambda: datetime.fromisoformat("2026-01-06T17:30:00+11:00"),
    )
    assert await runner.run_once(date(2026, 1, 6)) is True
    next_bar["value"] = replace(
        original,
        raw=replace(original.raw, close=original.raw.close + Decimal("0.01")),
        analytical=replace(original.analytical, close=original.analytical.close + Decimal("0.01")),
    )
    assert await runner.run_once(date(2026, 1, 6)) is True
    event = ShadowRecord(tmp_path / "OPERATIONAL" / "shadow.jsonl").events[-1]
    assert event["detail"]["reason"] == "bar_revision_pending_ds_review"
    store = h.HistoryStore(
        tmp_path / "OPERATIONAL",
        repository_root=Path(__file__).resolve().parents[2],
        protected_roots=(),
    )
    assert store.decision_bars("BHP.AX", date(2026, 1, 6))[-1].bar.raw == original.raw


@pytest.mark.asyncio
async def test_missing_real_authorities_probes_raw_bars_but_cannot_make_cards(
    tmp_path, monkeypatch
):
    observed = []

    class OfflineRawProbe:
        def __init__(self, _settings, *, audit):
            self.audit = audit

        def fetch(self, session, symbols):
            observed.append((session, symbols))
            self.audit({"kind": "ibkr_history_observation", "symbol": "BHP.AX"})
            return tuple({"symbol": symbol, "close": "62.43", "stable": True} for symbol in symbols)

    monkeypatch.setattr("qat.operational.shadow.IBKRRawBarProbe", OfflineRawProbe)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        ibkr_account_id="DU123456",
        phase3_shadow_enabled=True,
        phase3_operational_root=str(tmp_path / "OPERATIONAL"),
        phase3_authorities_dir=str(tmp_path / "missing-authorities"),
    )
    runner = Phase3ShadowRunner(
        settings,
        object(),
        object(),
        now=lambda: datetime.fromisoformat("2026-10-21T17:30:00+11:00"),
    )
    assert await runner.run_once(date(2026, 10, 21)) is True
    assert observed == [(date(2026, 10, 21), ("SUN.AX", "MFG.AX", "BHP.AX", "CBA.AX", "WGX.AX"))]
    event = ShadowRecord(tmp_path / "OPERATIONAL" / "shadow.jsonl").events[-1]
    assert event["kind"] == "abstention"
    assert event["detail"]["reason"].startswith("authority_unavailable:")
    assert event["detail"]["raw_bars"][0]["symbol"] == "SUN.AX"
    assert runner.cards == ()


@pytest.mark.asyncio
async def test_raw_probe_failure_records_abstention_and_retries(tmp_path, monkeypatch):
    class FailingProbe:
        def __init__(self, _settings, *, audit):
            pass

        def fetch(self, _session, _symbols):
            raise RuntimeError("recorded IBKR request failure")

    monkeypatch.setattr("qat.operational.shadow.IBKRRawBarProbe", FailingProbe)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        ibkr_account_id="DU123456",
        phase3_shadow_enabled=True,
        phase3_operational_root=str(tmp_path / "OPERATIONAL"),
        phase3_authorities_dir=str(tmp_path / "missing-authorities"),
    )
    runner = Phase3ShadowRunner(settings, object(), object())
    assert await runner.run_once(date(2026, 10, 21)) is False
    event = ShadowRecord(tmp_path / "OPERATIONAL" / "shadow.jsonl").events[-1]
    assert event["kind"] == "abstention"
    assert event["detail"]["raw_probe_error"] == "recorded IBKR request failure"
