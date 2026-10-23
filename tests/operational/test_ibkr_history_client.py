"""Offline replay of the 12 October all-hours TRADES probe."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import pytest

from qat.config import Settings
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor
from qat.operational.history import ActionLedger, CorporateAction, HaltEntry, HaltLedger, digest
from qat.operational.ibkr_history import IBKRHistoricalBarSource, IBKRRawBarProbe, _default_client


def test_readonly_contract_mapping_matches_existing_asx_contracts():
    from qat.data.broker.ib_readonly import to_asx_stock_contract
    from qat.data.broker.ib_translate import to_ib_contract

    for symbol in ("SUN", "MFG", "CBA", "BHP", "CSL", "WES", "WOW", "TLS", "WDS", "TCL"):
        assert to_asx_stock_contract(f"{symbol}.AX") == to_ib_contract(f"{symbol}.AX", "ASX")


SESSION = date(2026, 10, 12)
OBSERVED = datetime.fromisoformat("2026-10-12T17:30:00+11:00")


@dataclass(frozen=True)
class RecordedBar:
    # phase3-close_window-20261012T070714088412Z.json, all-hours TRADES.
    date: date = SESSION
    open: float = 61.8
    high: float = 62.76
    low: float = 61.8
    close: float = 62.43
    volume: float = 4574071.0
    barCount: int = 1


class FakeIB:
    def __init__(
        self,
        first: RecordedBar | list[RecordedBar],
        second: RecordedBar | list[RecordedBar] | None = None,
    ) -> None:
        first_rows = first if isinstance(first, list) else [first]
        second_rows = second if isinstance(second, list) else ([second] if second else first_rows)
        self.responses = [first_rows, second_rows]
        self.requests: list[dict[str, object]] = []
        self.account_reads = 0
        self.connected = False

    async def connectAsync(self, host, port, clientId, readonly, timeout):
        assert (host, port, readonly) == ("127.0.0.1", 4002, True)
        self.connected = True

    def managedAccounts(self):
        self.account_reads += 1
        return ["DU123456"]

    async def qualifyContractsAsync(self, contract):
        return [contract]

    async def reqHistoricalDataAsync(self, contract, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)

    def disconnect(self):
        self.connected = False


def source(client: FakeIB, *, audit=None, sleep=None, now=OBSERVED, actions=None, halts=None):
    async def no_wait(_seconds):
        return None

    return IBKRHistoricalBarSource(
        Settings(_env_file=None, broker="ibkr", ibkr_account_id="DU123456"),
        actions
        or ActionLedger(
            "asx-corporate-actions-v1",
            1,
            SESSION,
            date(2023, 10, 1),
            SESSION,
            "https://www.asx.com.au/markets",
            False,
            (),
        ),
        halts or HaltLedger("asx-halts-v1", 1, SESSION, False, ()),
        audit=audit or (lambda _: None),
        client_factory=lambda: client,
        now=lambda: now,
        sleep=sleep or no_wait,
    )


def test_recorded_all_hours_bar_is_final_only_after_matching_second_read():
    client = FakeIB(RecordedBar())
    observations = []
    waits = []

    async def no_wait(seconds):
        waits.append(seconds)

    bars = source(client, audit=observations.append, sleep=no_wait).fetch(SESSION, ("BHP.AX",))

    assert len(bars) == 1
    assert bars[0].raw.close == Decimal("62.43")
    assert bars[0].raw.volume == 4574071
    assert bars[0].finalised is True
    assert bars[0].raw_provenance == "AS_TRADED"
    assert len(client.requests) == 2
    assert all(
        req["whatToShow"] == "TRADES"
        and req["useRTH"] is False
        and req["barSizeSetting"] == "1 day"
        for req in client.requests
    )
    assert waits == [15.0]
    assert client.account_reads == 4  # qualify and history, on both observations
    assert observations[0]["float_hex"]["close"] == (62.43).hex()
    assert client.connected is False


def test_history_request_has_margin_before_the_first_required_session():
    earliest_required = RecordedBar(date=date(2023, 10, 12))
    client = FakeIB([earliest_required, RecordedBar()])

    history = source(client)
    history.fetch(SESSION, ("BHP.AX",))

    assert [request["durationStr"] for request in client.requests] == ["4 Y", "4 Y"]
    assert all(request["whatToShow"] == "TRADES" for request in client.requests)
    assert all(request["useRTH"] is False for request in client.requests)
    assert [bar.session for bar in history.backfill] == [date(2023, 10, 12)]


def test_default_client_is_unconnected_ib_async():
    from ib_async import IB

    client = _default_client()
    assert isinstance(client, IB)
    assert not client.isConnected()


def test_raw_probe_records_bars_without_authority_files_and_never_converts():
    client = FakeIB(RecordedBar())
    observations = []

    async def no_wait(_seconds):
        return None

    probe = IBKRRawBarProbe(
        Settings(_env_file=None, broker="ibkr", ibkr_account_id="DU123456"),
        audit=observations.append,
        client_factory=lambda: client,
        now=lambda: OBSERVED,
        sleep=no_wait,
    )
    result = probe.fetch(SESSION, ("BHP.AX",))

    assert result == (
        {
            "symbol": "BHP.AX",
            "session": "2026-10-12",
            "close": "62.43",
            "volume": "4574071.0",
            "stable": True,
        },
    )
    assert len(observations) == 2
    assert all(row["kind"] == "ibkr_history_observation" for row in observations)
    assert client.account_reads == 4
    assert client.connected is False


def test_raw_probe_refuses_extra_account_before_history():
    client = FakeIB(RecordedBar())
    client.managedAccounts = lambda: ["DU123456", "DUOTHER"]
    probe = IBKRRawBarProbe(
        Settings(_env_file=None, broker="ibkr", ibkr_account_id="DU123456"),
        audit=lambda _: None,
        client_factory=lambda: client,
        now=lambda: OBSERVED,
    )
    with pytest.raises(ValueError, match="exactly the configured account"):
        probe.fetch(SESSION, ("BHP.AX",))
    assert client.requests == []


def test_changed_bar_remains_unfinalised_and_keeps_both_observations():
    client = FakeIB(RecordedBar(close=62.38), RecordedBar())
    observations = []
    bars = source(client, audit=observations.append).fetch(SESSION, ("BHP.AX",))
    assert bars[0].finalised is False
    assert bars[0].raw.close == Decimal("62.43")
    assert len(observations) == 2


def test_before_1700_cannot_finalise_even_if_observations_match():
    client = FakeIB(RecordedBar())
    bars = source(client, now=datetime.fromisoformat("2026-10-12T16:30:00+11:00")).fetch(
        SESSION, ("BHP.AX",)
    )
    assert bars[0].finalised is False


def test_fractional_volume_refused():
    client = FakeIB(RecordedBar(volume=4574071.5))
    with pytest.raises(ValueError, match="integer volume"):
        source(client).fetch(SESSION, ("BHP.AX",))


def test_undocumented_zero_volume_refused():
    client = FakeIB(RecordedBar(volume=0.0, barCount=0))
    with pytest.raises(ValueError, match="halt ledger"):
        source(client).fetch(SESSION, ("BHP.AX",))


def test_documented_halt_placeholder_is_excluded_and_audited():
    header = {"schema": "asx-halts-v1", "version": 1, "published_on": SESSION, "fixture": False}
    identity = {
        "sequence": 1,
        "symbol": "BHP.AX",
        "first_session": SESSION,
        "last_session": SESSION,
        "interruption_type": "halt",
        "evidence_kind": "broker_record",
        "evidence_reference": "IBKR:recorded-halt",
        "previous_hash": digest(header),
    }
    entry = HaltEntry(**identity, content_hash=digest(identity))
    halts = HaltLedger("asx-halts-v1", 1, SESSION, False, (entry,))
    observations = []
    client = FakeIB(RecordedBar(volume=0.0, barCount=0))
    assert source(client, halts=halts, audit=observations.append).fetch(SESSION, ("BHP.AX",)) == ()
    assert any(item["kind"] == "documented_halt_placeholder" for item in observations)


def test_half_step_grid_accepts_recorded_low_and_rejects_off_grid():
    client = FakeIB(RecordedBar(low=61.805))
    assert source(client).fetch(SESSION, ("BHP.AX",))[0].raw.low == Decimal("61.805")
    bad = FakeIB(RecordedBar(low=61.801))
    with pytest.raises(ValueError, match="half-step"):
        source(bad).fetch(SESSION, ("BHP.AX",))


def test_foreign_or_extra_managed_account_refuses_before_history():
    client = FakeIB(RecordedBar())
    client.managedAccounts = lambda: ["DU123456", "DUOTHER"]
    with pytest.raises(ValueError, match="exactly the configured account"):
        source(client).fetch(SESSION, ("BHP.AX",))
    assert client.requests == []


def test_same_source_backfill_preserves_exact_pre_split_raw_and_fractional_volume():
    historical = RecordedBar(
        date=date(2025, 12, 1), open=2.3765, high=2.5, low=2.25, close=2.4, volume=100000.0
    )
    client = FakeIB([historical, RecordedBar()])
    action = CorporateAction(
        "BHP.AX",
        date(2026, 1, 6),
        SplitFactor(1, 2),
        Decimal(0),
        "https://www.asx.com.au/markets",
    )
    actions = ActionLedger(
        "asx-corporate-actions-v1",
        1,
        SESSION,
        date(2023, 10, 1),
        SESSION,
        "https://www.asx.com.au/markets",
        False,
        (action,),
    )
    history = source(client, actions=actions)
    assert history.fetch(SESSION, ("BHP.AX",))[0].raw.close == Decimal("62.43")
    assert len(history.backfill) == 1
    older = history.backfill[0]
    assert older.raw_provenance == "DERIVED"
    assert older.raw.open == Decimal("4.753")
    assert older.raw.volume == 50000
    assert older.factor == SplitFactor(1, 2)


def test_fractional_adjusted_volume_uses_exact_split_inverse():
    historical = RecordedBar(
        date=date(2025, 2, 14),
        open=23.393,
        high=23.722,
        low=23.276,
        close=23.452,
        volume=2658069.5589,
    )
    client = FakeIB([historical, RecordedBar()])
    action = CorporateAction(
        "SUN.AX",
        date(2025, 2, 17),
        SplitFactor(10000, 8511),
        Decimal(0),
        "https://www.asx.com.au/markets",
    )
    actions = ActionLedger(
        "asx-corporate-actions-v1",
        1,
        SESSION,
        date(2023, 10, 1),
        SESSION,
        "https://www.asx.com.au/markets",
        False,
        (action,),
    )
    history = source(client, actions=actions)
    history.fetch(SESSION, ("SUN.AX",))
    assert history.backfill[0].raw_provenance == "DERIVED"
    assert history.backfill[0].raw.volume == 3123099
    assert history.backfill[0].analytical.volume == Decimal("2658069.5589")
