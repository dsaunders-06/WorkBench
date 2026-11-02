"""Date-active shadow scope, using temporary authorities and a format-free provider."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from qat.operational import history as h
from qat.operational.adapter import EvaluationParameters, OperationalAdapter

SCRIPT = Path(__file__).parents[2] / "scripts" / "phase3_shadow_readonly_check.py"
spec = importlib.util.spec_from_file_location("membership_successor_readonly", SCRIPT)
assert spec and spec.loader
readonly = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = readonly
spec.loader.exec_module(readonly)

TEN = tuple(
    sorted(
        f"{s}.AX" for s in ("SUN", "MFG", "CBA", "BHP", "CSL", "WES", "WOW", "TLS", "WDS", "TCL")
    )
)
FRIDAY = date(2026, 10, 30)
MONDAY = date(2026, 11, 2)


def scope_api():
    assert importlib.util.find_spec(
        "qat.operational.membership_scope"
    ), "active-members interface absent"
    return importlib.import_module("qat.operational.membership_scope")


def authorities(tmp_path):
    root = tmp_path / "authorities"
    root.mkdir()
    days = ["2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"]
    calendar = dict(
        schema="asx-calendar-v1",
        version=1,
        published_on="2026-10-29",
        coverage_start=days[0],
        coverage_end=days[-1],
        source="https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar",
        fixture=False,
        valid_through="2026-11-03",
        sessions=[dict(session=d, open=f"{d}T10:00:00+11:00") for d in days],
        closures=[],
    )
    # Original base stays open-ended: the provider decides scope, without selecting a file format.
    membership = dict(
        schema="asx200-membership-v2",
        version=2,
        published_on="2026-10-29",
        valid_through="2026-11-03",
        fixture=False,
        managed_symbols=[],
        entries=[
            dict(
                symbol=s,
                effective_from="2026-10-29",
                effective_to=None,
                citations=["https://www.ssga.com/stw", "https://www.blackrock.com/au/ioz"],
            )
            for s in TEN
        ],
    )
    actions = json.loads((Path(__file__).parent / "fixtures" / "actions.json").read_text())
    actions.update(
        fixture=False,
        published_on="2026-10-29",
        coverage_end="2026-11-03",
        valid_through="2026-11-03",
    )
    for name, value in [
        ("calendar.json", calendar),
        ("membership.json", membership),
        ("actions.json", actions),
    ]:
        (root / name).write_text(json.dumps(value))
    (root / "halts.jsonl").write_text(
        json.dumps(
            dict(
                schema="asx-halts-v1",
                version=1,
                published_on="2026-10-29",
                valid_through="2026-11-03",
                fixture=False,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    loaded = readonly.validate_approved_authorities(root, hashes, MONDAY)
    return root, hashes, loaded


class SelectedScope:
    """A verifier double, deliberately independent of any successor file representation."""

    def __init__(self):
        self.calls = 0

    def resolve(self, membership, session, *, attested_through=None):
        self.calls += 1
        names = tuple(
            s
            for s in TEN
            if membership.is_current(s, session, attested_through=attested_through)
            and (s != "MFG.AX" or session <= FRIDAY)
        )
        return scope_api().ActiveMembers(session, names, membership.content_hash, "f" * 64)


def store_for(tmp_path):
    return h.HistoryStore(
        tmp_path / "OPERATIONAL", repository_root=Path(__file__).parents[2], protected_roots=()
    )


def params():
    from qat.domain.strategies.authoritative_swing.sizing import exact_cost_profile

    return EvaluationParameters(
        Decimal("100000"), Decimal("90000"), exact_cost_profile("ASX", "fixed"), None
    )


@pytest.mark.asyncio
async def test_unconfigured_active_scope_abstains_before_source_creation(tmp_path):
    root, hashes, _ = authorities(tmp_path)
    store = store_for(tmp_path)
    observed = []

    class Source:
        backfill = ()

        def __init__(self, *args, **kwargs):
            observed.append("created")

        def fetch(self, *args):
            observed.append("requested")
            return ()

    record = readonly.approved_shadow_record(tmp_path / "OPERATIONAL")
    account = readonly.AccountSnapshot(
        Decimal("100000"), Decimal("90000"), datetime.fromisoformat("2026-11-02T17:31:00+11:00")
    )
    assert (
        await readonly.run_approved_once(
            MONDAY,
            SimpleNamespace(phase3_operational_root=str(tmp_path / "OPERATIONAL")),
            root,
            hashes,
            store,
            record,
            account,
            now=lambda: account.observed_at,
            source_factory=Source,
        )
        is False
    )
    assert observed == []
    assert "active_membership" in str(record.events[-1]["detail"])


@pytest.mark.parametrize("session,count", [(FRIDAY, 10), (MONDAY, 9)])
def test_adapter_evaluates_only_resolved_active_members(tmp_path, session, count):
    _, _, (cal, membership, halts, actions) = authorities(tmp_path)
    selected = SelectedScope().resolve(membership, session)
    store = store_for(tmp_path)
    adapter = OperationalAdapter(store, cal, membership, halts, actions, active_members=selected)
    snapshot = adapter.freeze(session, params())
    assert tuple(x.symbol for x in snapshot.active_inputs) == selected.symbols
    assert len(snapshot.active_inputs) == count
    assert snapshot.active_members == selected
    result = adapter.run(
        snapshot,
        now=datetime.combine(session, datetime.min.time(), h.SYDNEY).replace(hour=17, minute=45),
    )
    assert {x.symbol for x in result.abstentions} == set(selected.symbols)
    assert not result.candidates


@pytest.mark.asyncio
@pytest.mark.parametrize("session,count", [(FRIDAY, 10), (MONDAY, 9)])
async def test_history_request_uses_one_resolved_scope(tmp_path, session, count):
    root, hashes, _ = authorities(tmp_path)
    store = store_for(tmp_path)
    record = readonly.approved_shadow_record(tmp_path / "OPERATIONAL")
    provider = SelectedScope()
    observed = []
    stamp = datetime.combine(session, datetime.min.time(), h.SYDNEY).replace(hour=17, minute=45)
    template = h.parse_bar(
        json.loads((Path(__file__).parent / "fixtures" / "bar.json").read_text())
    )

    class Source:
        backfill = ()

        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, day, symbols):
            observed.append((day, symbols))
            return tuple(
                replace(template, symbol=s, session=day, retrieved_at=stamp) for s in symbols
            )

    account = readonly.AccountSnapshot(Decimal("100000"), Decimal("90000"), stamp)
    await readonly.run_approved_once(
        session,
        SimpleNamespace(
            phase3_operational_root=str(tmp_path / "OPERATIONAL"),
            ibkr_pricing_model="fixed",
            phase3_liquidity_max_participation=None,
        ),
        root,
        hashes,
        store,
        record,
        account,
        now=lambda: stamp,
        source_factory=Source,
        active_membership=provider,
    )
    assert provider.calls == 1
    assert len(observed) == 1 and len(observed[0][1]) == count
    assert ("MFG.AX" in observed[0][1]) == (session == FRIDAY)
    assert {r["detail"].get("symbol") for r in record.events} == set(observed[0][1])


def test_unapproved_membership_hash_refused(tmp_path):
    root, hashes, _ = authorities(tmp_path)
    hashes["membership.json"] = "0" * 64
    with pytest.raises(ValueError, match="approved hash mismatch"):
        readonly.validate_approved_authorities(root, hashes, MONDAY)


@pytest.mark.asyncio
async def test_outside_membership_abstains_without_request(tmp_path):
    root, hashes, _ = authorities(tmp_path)
    store = store_for(tmp_path)
    record = readonly.approved_shadow_record(tmp_path / "OPERATIONAL")
    account = readonly.AccountSnapshot(
        Decimal("100000"), Decimal("90000"), datetime.fromisoformat("2026-11-04T17:31:00+11:00")
    )

    def forbidden(*args, **kwargs):
        pytest.fail("out-of-scope membership reached a source")

    assert (
        await readonly.run_approved_once(
            date(2026, 11, 4),
            SimpleNamespace(phase3_operational_root=str(tmp_path / "OPERATIONAL")),
            root,
            hashes,
            store,
            record,
            account,
            source_factory=forbidden,
            active_membership=SelectedScope(),
        )
        is False
    )
    assert "authority_unavailable" in str(record.events[-1]["detail"])


def test_managed_member_cannot_broaden_active_scope(tmp_path):
    _, _, (cal, membership, halts, actions) = authorities(tmp_path)
    membership = replace(membership, managed_symbols=("MFG.AX",))
    selected = SelectedScope().resolve(membership, MONDAY)
    adapter = OperationalAdapter(
        store_for(tmp_path), cal, membership, halts, actions, active_members=selected
    )
    snapshot = adapter.freeze(MONDAY, params())
    assert "MFG.AX" not in {x.symbol for x in snapshot.active_inputs}
    retained = next(x for x in snapshot.symbols if x.symbol == "MFG.AX")
    assert not retained.quality.new_cards_allowed
    assert snapshot.membership.is_current("MFG.AX", MONDAY)


@pytest.mark.parametrize("fault", ["session", "base", "foreign", "empty"])
def test_invalid_interface_selection_refused(tmp_path, fault):
    _, _, (_, membership, _, _) = authorities(tmp_path)
    scope = scope_api()
    selected = SelectedScope().resolve(membership, MONDAY)
    selected = replace(
        selected,
        **{
            "session": {"session": FRIDAY},
            "base": {"base_membership_hash": "0" * 64},
            "foreign": {"symbols": ("BJY.AX",)},
            "empty": {"symbols": ()},
        }[fault],
    )
    with pytest.raises(ValueError, match="active membership"):
        scope.validate_active_members(membership, MONDAY, selected)


@pytest.mark.asyncio
async def test_configured_runner_freezes_exact_resolved_scope(tmp_path, monkeypatch):
    from qat.config import Settings
    from qat.operational import shadow

    root, hashes, _ = authorities(tmp_path)
    selected = []
    provider = SelectedScope()
    original_resolve = provider.resolve

    def resolve(*args, **kwargs):
        result = original_resolve(*args, **kwargs)
        selected.append(result)
        return result

    provider.resolve = resolve
    stamp = datetime.fromisoformat("2026-11-02T17:45:00+11:00")
    template = h.parse_bar(
        json.loads((Path(__file__).parent / "fixtures" / "bar.json").read_text())
    )

    class Source:
        backfill = ()

        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, day, symbols):
            assert "MFG.AX" not in symbols
            return tuple(
                replace(template, symbol=s, session=day, retrieved_at=stamp) for s in symbols
            )

    class Broker:
        async def account(self):
            return SimpleNamespace(net_liquidation=100000.0, cash=90000.0)

    actual_adapter = shadow.OperationalAdapter

    def checked_adapter(*args, **kwargs):
        assert kwargs.get("active_members") is selected[0]
        return actual_adapter(*args, **kwargs)

    monkeypatch.setattr(shadow, "OperationalAdapter", checked_adapter)
    monkeypatch.setattr(shadow, "IBKRHistoricalBarSource", Source)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        phase3_shadow_enabled=True,
        phase3_operational_root=str(tmp_path / "OPERATIONAL"),
        phase3_authorities_dir=str(root),
        **{f"phase3_{k.split('.')[0]}_sha256": v for k, v in hashes.items()},
    )
    runner = shadow.Phase3ShadowRunner(
        settings, Broker(), object(), now=lambda: stamp, active_membership=provider
    )
    await runner.run_once(MONDAY)
    assert provider.calls == 1
    assert "MFG.AX" not in {x.symbol for x in runner.abstentions}


def test_recomputed_snapshot_cannot_mix_another_session_scope(tmp_path):
    _, _, (cal, membership, halts, actions) = authorities(tmp_path)
    selected = SelectedScope().resolve(membership, MONDAY)
    adapter = OperationalAdapter(
        store_for(tmp_path), cal, membership, halts, actions, active_members=selected
    )
    snapshot = adapter.freeze(MONDAY, params())
    wrong = replace(snapshot, active_members=replace(selected, session=FRIDAY))
    wrong = replace(wrong, content_hash=h.digest(wrong.identity()))
    result = adapter.run(wrong, now=datetime.fromisoformat("2026-11-02T17:45:00+11:00"))
    assert len(result.abstentions) == 1 and result.abstentions[0].symbol is None
    assert "active_membership" in str(result.abstentions[0].reasons)
