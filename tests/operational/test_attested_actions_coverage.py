"""Offline regression for the 23 October files and 26 October attestation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from ib_async import BarData

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary
from qat.operational.authority_attestations import AuthorityAttestations
from qat.operational.history import HistoryStore, assess_history
from qat.operational.ibkr_history import IBKRHistoricalBarSource
from qat.operational.shadow import Phase3ShadowRunner
from qat.operational.shadow_record import ShadowRecord

SHADOW_SYMBOLS = tuple(
    sorted(
        f"{name}.AX"
        for name in ("SUN", "MFG", "CBA", "BHP", "CSL", "WES", "WOW", "TLS", "WDS", "TCL")
    )
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/phase3_shadow_readonly_check.py"
SPEC = importlib.util.spec_from_file_location("attested_coverage_readonly", SCRIPT)
assert SPEC and SPEC.loader
readonly = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readonly
SPEC.loader.exec_module(readonly)
BASE = date(2026, 10, 23)
MONDAY = date(2026, 10, 26)


def authority_copy(tmp_path: Path):
    """Portable temporary files with tonight's dates; no private source dependency."""
    root = tmp_path / "authorities"
    root.mkdir()
    calendar = {
        "schema": "asx-calendar-v1",
        "version": 1,
        "published_on": str(BASE),
        "coverage_start": "2023-10-01",
        "coverage_end": "2026-10-28",
        "valid_through": str(BASE),
        "source": "https://www.asx.com.au/markets/trading-calendar",
        "fixture": False,
        "sessions": [
            {"session": day, "open": f"{day}T10:00:00+11:00"}
            for day in ("2023-10-26", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28")
        ],
        "closures": [],
    }
    membership = {
        "schema": "asx200-membership-v2",
        "version": 2,
        "published_on": str(BASE),
        "valid_through": str(BASE),
        "fixture": False,
        "managed_symbols": [],
        "entries": [
            {
                "symbol": symbol,
                "effective_from": "2023-10-23",
                "effective_to": None,
                "citations": ["https://www.ssga.com/stw", "https://www.blackrock.com/au/ioz"],
            }
            for symbol in sorted(SHADOW_SYMBOLS)
        ],
    }
    halts = {
        "schema": "asx-halts-v1",
        "version": 1,
        "published_on": str(BASE),
        "valid_through": str(BASE),
        "fixture": False,
    }
    actions = {
        "schema": "asx-corporate-actions-v2",
        "version": 2,
        "published_on": str(BASE),
        "coverage_start": "2023-10-01",
        "coverage_end": str(BASE),
        "valid_through": str(BASE),
        "source": "https://www.asx.com.au/markets/announcements",
        "fixture": False,
        "events": [],
        "capital_returns": [],
        "dividend_scope": "unheld_out_of_scope",
    }
    for name, value in zip(
        readonly.AUTHORITY_FILES, (calendar, membership, halts, actions), strict=True
    ):
        (root / name).write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
        )
    hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in readonly.AUTHORITY_FILES
    }
    loaded = readonly.validate_approved_authorities(root, hashes, BASE)
    operational = tmp_path / "OPERATIONAL"
    HistoryStore(operational, repository_root=Path(__file__).parents[2], protected_roots=())
    audit = tmp_path / "audit.json"
    audit.write_text('{"session":"2026-10-26","authority_change_required":false}')
    ledger = AuthorityAttestations(operational / "authority_attestations.jsonl")
    ledger.append(
        MONDAY,
        hashes,
        audit,
        operator="DS",
        recorded_at=datetime.fromisoformat("2026-10-26T16:30:00+11:00"),
        calendar=loaded[0],
        base_valid_through=BASE,
    )
    return root, hashes, operational, loaded


class OfflineIB:
    def __init__(self, session: date):
        self.session = session

    async def connectAsync(self, host, port, clientId, readonly, timeout):
        assert (host, port, clientId, readonly) == ("127.0.0.1", 4002, 99, True)

    def managedAccounts(self):
        return ["DU123456"]

    async def qualifyContractsAsync(self, contract):
        return [contract]

    async def reqHistoricalDataAsync(self, contract, **kwargs):
        return [
            BarData(
                date=self.session,
                open=56.0,
                high=56.0,
                low=55.38,
                close=55.62,
                volume=6705974.0,
                average=55.8,
                barCount=1000,
            )
        ]

    def disconnect(self):
        pass


class OfflineAccountBroker:
    async def account(self):
        return AccountSummary(100000.0, 90000.0, 90000.0, 0.0)


async def no_wait(_seconds):
    pass


def offline_source(session, *args, **kwargs):
    return IBKRHistoricalBarSource(
        *args,
        **kwargs,
        client_factory=lambda: OfflineIB(session),
        now=lambda: datetime.fromisoformat(f"{session}T17:30:00+11:00"),
        sleep=no_wait,
    )


def settings_for(root, hashes, operational):
    return Settings(
        _env_file=None,
        broker="ibkr",
        ibkr_account_id="DU123456",
        phase3_shadow_enabled=True,
        phase3_operational_root=str(operational),
        phase3_authorities_dir=str(root),
        phase3_calendar_sha256=hashes["calendar.json"],
        phase3_membership_sha256=hashes["membership.json"],
        phase3_halts_sha256=hashes["halts.jsonl"],
        phase3_actions_sha256=hashes["actions.json"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["readonly", "configured"])
async def test_october_23_files_and_verified_october_26_attestation_pass_actions_coverage(
    tmp_path, monkeypatch, entrypoint, historical_membership_scope
):
    root, hashes, operational, _ = authority_copy(tmp_path)
    immutable = {
        path: path.read_bytes()
        for path in (*root.iterdir(), operational / "authority_attestations.jsonl")
    }
    settings = settings_for(root, hashes, operational)
    observed = datetime.fromisoformat("2026-10-26T17:30:00+11:00")
    store = HistoryStore(operational, repository_root=Path(__file__).parents[2], protected_roots=())
    if entrypoint == "readonly":
        record = readonly.approved_shadow_record(operational)
        await readonly.run_approved_once(
            MONDAY,
            settings,
            root,
            hashes,
            store,
            record,
            readonly.AccountSnapshot(Decimal("100000"), Decimal("90000"), observed),
            now=lambda: observed,
            source_factory=lambda *args, **kwargs: offline_source(MONDAY, *args, **kwargs),
            active_membership=historical_membership_scope,
        )
    else:
        monkeypatch.setattr(
            "qat.operational.shadow.IBKRHistoricalBarSource",
            lambda *args, **kwargs: offline_source(MONDAY, *args, **kwargs),
        )
        await Phase3ShadowRunner(
            settings,
            OfflineAccountBroker(),
            object(),
            now=lambda: observed,
            active_membership=historical_membership_scope,
        ).run_once(MONDAY)
    events = ShadowRecord(operational / "shadow.jsonl").events
    assert events and all(event["kind"] == "abstention" for event in events)
    # Short offline history still abstains for gaps; neither actions-age check may fail.
    assert "corporate action authority does not cover session" not in str(events)
    assert "corporate_action_coverage" not in str(events)
    assert sum(len(store.decision_bars(symbol, MONDAY)) for symbol in SHADOW_SYMBOLS) == 10
    assert all(path.read_bytes() == raw for path, raw in immutable.items())


@pytest.mark.parametrize(
    ("session", "attested", "covered"),
    [
        (date(2026, 10, 22), None, True),
        (BASE, None, True),
        (MONDAY, MONDAY, True),
        (date(2026, 10, 27), MONDAY, False),
        (MONDAY, None, False),
    ],
)
def test_source_and_history_share_effective_actions_end(tmp_path, session, attested, covered):
    _, _, _, (calendar, membership, halts, actions) = authority_copy(tmp_path)
    settings = Settings(_env_file=None, broker="ibkr", ibkr_account_id="DU123456")
    extension = {} if attested is None else {"attested_through": attested}
    source = offline_source(session, settings, actions, halts, audit=lambda _: None, **extension)
    if covered:
        assert source.fetch(session, ("BHP.AX",))[0].session == session
    else:
        with pytest.raises(ValueError, match="does not cover session"):
            source.fetch(session, ("BHP.AX",))
    quality = assess_history(
        "BHP.AX",
        session,
        calendar,
        membership,
        halts,
        (),
        (),
        actions,
        attested_through=attested,
    )
    assert ("corporate_action_coverage" not in quality.reasons) is covered


def test_attestation_never_extends_the_actions_coverage_start(tmp_path):
    _, _, _, (calendar, membership, halts, actions) = authority_copy(tmp_path)
    actions = replace(actions, coverage_start=date(2023, 10, 27))
    settings = Settings(_env_file=None, broker="ibkr", ibkr_account_id="DU123456")
    source = offline_source(
        date(2023, 10, 26),
        settings,
        actions,
        halts,
        audit=lambda _: None,
        attested_through=MONDAY,
    )
    assert source.fetch(date(2023, 10, 26), ("BHP.AX",)) == ()
    quality = assess_history(
        "BHP.AX",
        MONDAY,
        calendar,
        membership,
        halts,
        (),
        (),
        actions,
        attested_through=MONDAY,
    )
    assert "corporate_action_coverage" in quality.reasons


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["broken_chain", "changed_actions_hash", "after_latest", "missing"]
)
async def test_existing_loader_refusal_still_produces_no_card(tmp_path, monkeypatch, fault):
    root, hashes, operational, _ = authority_copy(tmp_path)
    ledger = operational / "authority_attestations.jsonl"
    session = date(2026, 10, 27) if fault == "after_latest" else MONDAY
    if fault == "broken_chain":
        ledger.write_text(ledger.read_text().replace('"operator":"DS"', '"operator":"XX"'))
    elif fault == "changed_actions_hash":
        action = root / "actions.json"
        action.write_text(action.read_text() + " ")
    elif fault == "missing":
        ledger.unlink()
    immutable = {path: path.read_bytes() for path in (*root.iterdir(), *operational.iterdir())}
    with pytest.raises(ValueError):
        readonly.validate_approved_authorities(root, hashes, session, operational_root=operational)

    class NoCardSource:
        def __init__(self, *args, **kwargs):
            raise AssertionError("refused authority reached the card source")

    class NoNetworkRawProbe:
        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, *_args):
            return ()

    monkeypatch.setattr("qat.operational.shadow.IBKRHistoricalBarSource", NoCardSource)
    monkeypatch.setattr("qat.operational.ibkr_history.IBKRRawBarProbe", NoNetworkRawProbe)
    runner = Phase3ShadowRunner(settings_for(root, hashes, operational), object(), object())
    await runner.run_once(session)
    event = ShadowRecord(operational / "shadow.jsonl").events[-1]
    assert event["kind"] == "abstention"
    assert event["detail"]["reason"].startswith("authority_unavailable:")
    assert runner.cards == ()
    assert all(path.read_bytes() == raw for path, raw in immutable.items())
