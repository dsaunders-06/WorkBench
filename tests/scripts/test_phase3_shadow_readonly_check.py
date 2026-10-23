"""The no-authority shadow check cannot start outside its approved window."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase3_shadow_readonly_check.py"
spec = importlib.util.spec_from_file_location("phase3_shadow_readonly_check", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_readonly_check_requires_window_and_missing_authorities(tmp_path):
    session = date(2026, 10, 22)
    authorities = tmp_path / "missing-authorities"
    module.validate_window(
        session, datetime.fromisoformat("2026-10-22T17:30:00+11:00"), authorities
    )
    with pytest.raises(ValueError, match="17:30"):
        module.validate_window(
            session, datetime.fromisoformat("2026-10-22T17:29:59+11:00"), authorities
        )
    with pytest.raises(ValueError, match="17:30"):
        module.validate_window(
            session, datetime.fromisoformat("2026-10-22T20:00:00+11:00"), authorities
        )
    authorities.mkdir()
    (authorities / "actions.json").write_text("{}")
    with pytest.raises(ValueError, match="authorities appeared"):
        module.validate_window(
            session, datetime.fromisoformat("2026-10-22T17:30:00+11:00"), authorities
        )


def test_readonly_surface_refuses_every_broker_access():
    with pytest.raises(RuntimeError, match="cannot access place_order"):
        _ = module._NoTradingSurface().place_order


def test_approved_check_imports_no_qat_order_oms_or_approval_modules():
    code = """
import builtins
import importlib.util
import pathlib
import sys
blocked = ('qat.domain.oms', 'qat.data.broker.adapter', 'qat.operational.cards')
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if any(name == prefix or name.startswith(prefix + '.') for prefix in blocked):
        raise AssertionError('trading or approval import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
spec = importlib.util.spec_from_file_location('readonly_check', pathlib.Path(sys.argv[1]))
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert not any(any(name == prefix or name.startswith(prefix + '.') for prefix in blocked)
               for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_approved_hashes_require_exact_four_files_and_current_real_authorities(tmp_path):
    authorities = tmp_path / "authorities"
    authorities.mkdir()
    names = ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
    for name in names:
        (authorities / name).write_text("{}")
    hashes = {
        name: module.hashlib.sha256((authorities / name).read_bytes()).hexdigest() for name in names
    }
    with pytest.raises(ValueError, match="real|schema|calendar|membership|halts|actions"):
        module.validate_approved_authorities(authorities, hashes, date(2026, 10, 23))
    hashes["calendar.json"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        module.validate_approved_authorities(authorities, hashes, date(2026, 10, 23))
    (authorities / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="exactly four"):
        module.validate_approved_authorities(authorities, hashes, date(2026, 10, 23))


def test_approved_hashes_load_exact_ten_symbol_real_authorities(tmp_path):
    fixtures = Path(__file__).resolve().parents[1] / "operational" / "fixtures"
    root = tmp_path / "authorities"
    root.mkdir()
    session = date(2026, 1, 6)
    for name in ("calendar.json", "actions.json"):
        payload = json.loads((fixtures / name).read_text())
        payload["fixture"] = False
        payload["valid_through"] = session.isoformat()
        (root / name).write_text(json.dumps(payload))
    membership = {
        "schema": "asx200-membership-v2",
        "version": 2,
        "published_on": session.isoformat(),
        "valid_through": session.isoformat(),
        "fixture": False,
        "managed_symbols": [],
        "entries": [
            {
                "symbol": symbol,
                "effective_from": session.isoformat(),
                "effective_to": None,
                "citations": ["https://www.ssga.com/stw", "https://www.blackrock.com/au/ioz"],
            }
            for symbol in sorted(module.SHADOW_SYMBOLS)
        ],
    }
    (root / "membership.json").write_text(json.dumps(membership))
    (root / "halts.jsonl").write_text(
        json.dumps(
            {
                "schema": "asx-halts-v1",
                "version": 1,
                "published_on": session.isoformat(),
                "valid_through": session.isoformat(),
                "fixture": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    hashes = {
        name: module.hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in module.AUTHORITY_FILES
    }
    loaded = module.validate_approved_authorities(root, hashes, session)
    assert all(not item.fixture and item.valid_through == session for item in loaded)
    with pytest.raises(ValueError, match="valid through"):
        module.validate_approved_authorities(root, hashes, date(2026, 1, 7))


def test_account_equity_comes_from_one_checked_readonly_summary_request():
    class Client:
        def __init__(self):
            self.connect_args = None
            self.summary_calls = 0
            self.disconnected = False

        async def connectAsync(self, host, port, **kwargs):
            self.connect_args = host, port, kwargs

        def managedAccounts(self):
            return ["DU123456"]

        async def accountSummaryAsync(self):
            self.summary_calls += 1
            return [
                SimpleNamespace(
                    account="DU123456", tag="NetLiquidation", currency="AUD", value="123456.78"
                ),
                SimpleNamespace(
                    account="DU123456", tag="TotalCashValue", currency="AUD", value="120000.00"
                ),
            ]

        def disconnect(self):
            self.disconnected = True

    client = Client()
    settings = SimpleNamespace(
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        ibkr_account_id="DU123456",
        market="ASX",
        broker="ibkr",
        trading_mode="paper",
    )
    coroutine = module.read_account_snapshot(settings, client_factory=lambda: client)
    with pytest.raises(StopIteration) as done:
        coroutine.send(None)
    snapshot = done.value.value
    assert str(snapshot.equity) == "123456.78"
    assert str(snapshot.cash) == "120000.00"
    assert snapshot.observed_at.tzinfo is not None
    assert client.summary_calls == 1
    assert client.connect_args == (
        "127.0.0.1",
        4002,
        {"clientId": 99, "readonly": True, "timeout": 15},
    )
    assert client.disconnected


def test_shadow_event_keeps_unvalidated_card_and_abstention_reason(tmp_path):
    root = tmp_path / "OPERATIONAL"
    root.mkdir()
    record = module.approved_shadow_record(root)
    card = record.append(
        "card",
        date(2026, 10, 23),
        {"symbol": "BHP.AX", "label": "unvalidated strategy, no demonstrated edge", "quantity": 3},
    )
    abstention = record.append(
        "abstention", date(2026, 10, 23), {"symbol": "MFG.AX", "reasons": ["documented_halt"]}
    )
    assert abstention["previous_hash"] == card["content_hash"]
    assert json.loads((root / "shadow.jsonl").read_text().splitlines()[0])["detail"][
        "label"
    ].startswith("unvalidated")


def test_approved_result_records_every_card_and_abstention_without_orders(tmp_path):
    record = module.approved_shadow_record(tmp_path / "OPERATIONAL")
    account = module.AccountSnapshot(
        module.Decimal("100000"),
        module.Decimal("90000"),
        datetime.fromisoformat("2026-10-23T17:31:00+11:00"),
    )
    candidate = SimpleNamespace(
        symbol="BHP.AX",
        label="unvalidated strategy, no demonstrated edge",
        entry_limit_raw=module.Decimal("50"),
        structural_stop_raw=module.Decimal("45"),
        evidence=SimpleNamespace(quantity=10),
    )
    abstention = SimpleNamespace(symbol="MFG.AX", reasons=("documented_halt",))
    result = SimpleNamespace(candidates=(candidate,), abstentions=(abstention,))
    module.record_approved_result(record, date(2026, 10, 23), result, (), account)
    events = module.approved_shadow_record(tmp_path / "OPERATIONAL").events
    assert [(row["kind"], row["detail"]["symbol"]) for row in events] == [
        ("abstention", "MFG.AX"),
        ("card", "BHP.AX"),
    ]
    assert events[-1]["detail"]["label"] == "unvalidated strategy, no demonstrated edge"
    assert events[-1]["detail"]["quantity"] == 10
    assert events[-1]["detail"]["account_observed_at"] == "2026-10-23T17:31:00+11:00"


def test_revised_symbol_is_abstained_and_never_recorded_as_card(tmp_path):
    record = module.approved_shadow_record(tmp_path / "OPERATIONAL")
    account = module.AccountSnapshot(
        module.Decimal("100000"),
        module.Decimal("90000"),
        datetime.fromisoformat("2026-10-23T17:31:00+11:00"),
    )
    candidate = SimpleNamespace(
        symbol="BHP.AX",
        label="unvalidated strategy, no demonstrated edge",
        entry_limit_raw=module.Decimal("50"),
        structural_stop_raw=module.Decimal("45"),
        evidence=SimpleNamespace(quantity=10),
    )
    result = SimpleNamespace(candidates=(candidate,), abstentions=())
    module.record_approved_result(record, date(2026, 10, 23), result, ("BHP.AX",), account)
    events = module.approved_shadow_record(tmp_path / "OPERATIONAL").events
    assert len(events) == 1
    assert events[0]["kind"] == "abstention"
    assert events[0]["detail"]["reasons"] == ["bar_revision_pending_ds_review"]


def test_approved_path_evaluates_unvalidated_candidates_without_trading_imports(
    monkeypatch, tmp_path
):
    session = date(2026, 10, 23)
    record = module.approved_shadow_record(tmp_path / "OPERATIONAL")
    account = module.AccountSnapshot(
        module.Decimal("100000"),
        module.Decimal("90000"),
        datetime.fromisoformat("2026-10-23T17:31:00+11:00"),
    )
    candidate = SimpleNamespace(
        symbol="BHP.AX",
        label="unvalidated strategy, no demonstrated edge",
        entry_limit_raw=module.Decimal("50"),
        structural_stop_raw=module.Decimal("45"),
        evidence=SimpleNamespace(quantity=10),
    )
    bar = SimpleNamespace(finalised=True)
    source = SimpleNamespace(
        backfill=(), fetch=lambda _day, _names: tuple(bar for _ in module.SHADOW_SYMBOLS)
    )
    store = SimpleNamespace(log=lambda _event: None, shadow_revision_pending=lambda _names: ())
    calls = []

    class Adapter:
        def __init__(self, *_args):
            calls.append("adapter")

        def attempt_primary(self, *_args, **kwargs):
            assert kwargs["shadow_freeze_final"] is True
            calls.append("history")
            return SimpleNamespace(abstained=False)

        def freeze(self, _session, parameters):
            assert parameters.equity == account.equity
            calls.append("freeze")
            return object()

        def run(self, _snapshot, *, now):
            assert now.tzinfo is not None
            calls.append("run")
            return SimpleNamespace(candidates=(candidate,), abstentions=())

    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(module, "validate_approved_authorities", lambda *_: (None,) * 4)
    monkeypatch.setattr(module, "OperationalAdapter", Adapter)
    monkeypatch.setattr(module.asyncio, "to_thread", immediate)
    coroutine = module.run_approved_once(
        session,
        SimpleNamespace(ibkr_pricing_model="fixed", phase3_liquidity_max_participation=None),
        tmp_path,
        {},
        store,
        record,
        account,
        now=lambda: account.observed_at,
        source_factory=lambda *_args, **_kwargs: source,
    )
    with pytest.raises(StopIteration) as done:
        coroutine.send(None)
    assert done.value.value is True
    assert calls == ["adapter", "history", "freeze", "run"]
    assert record.events[0]["kind"] == "card"
    assert record.events[0]["detail"]["label"] == "unvalidated strategy, no demonstrated edge"


def test_approved_path_drops_pre_calendar_bars_before_ingest(monkeypatch, tmp_path):
    session = date(2026, 10, 23)
    start = date(2023, 10, 22)
    record = module.approved_shadow_record(tmp_path / "OPERATIONAL")
    account = module.AccountSnapshot(
        module.Decimal("100000"),
        module.Decimal("90000"),
        datetime.fromisoformat("2026-10-23T17:31:00+11:00"),
    )
    old = SimpleNamespace(symbol="BHP.AX", session=date(2022, 10, 24), finalised=True)
    first = SimpleNamespace(symbol="BHP.AX", session=date(2023, 10, 23), finalised=True)
    source = SimpleNamespace(
        backfill=(old, first),
        fetch=lambda _day, _names: tuple(
            SimpleNamespace(finalised=True) for _ in module.SHADOW_SYMBOLS
        ),
    )
    ingested = []
    events = []
    store = SimpleNamespace(
        log=events.append,
        decision_bars=lambda _symbol, _session: (),
        ingest=lambda bars, *_args, **_kwargs: ingested.extend(bars),
        shadow_revision_pending=lambda _names: (),
    )

    class Adapter:
        def __init__(self, *_args):
            pass

        def attempt_primary(self, *_args, **_kwargs):
            return SimpleNamespace(abstained=True, reasons={"BHP.AX": ("test_abstention",)})

    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        module,
        "validate_approved_authorities",
        lambda *_: (SimpleNamespace(coverage_start=start), None, None, None),
    )
    monkeypatch.setattr(module, "OperationalAdapter", Adapter)
    monkeypatch.setattr(module.asyncio, "to_thread", immediate)
    coroutine = module.run_approved_once(
        session,
        SimpleNamespace(),
        tmp_path,
        {},
        store,
        record,
        account,
        source_factory=lambda *_args, **_kwargs: source,
    )
    with pytest.raises(StopIteration):
        coroutine.send(None)

    assert ingested == [first]
    assert events == [
        {
            "kind": "history_before_calendar_dropped",
            "symbol": "BHP.AX",
            "count": 1,
            "coverage_start": start.isoformat(),
        }
    ]
