"""Failure injection for the protective-stop handoff, using the real OMS."""

import hashlib
import json
from dataclasses import replace
from datetime import date

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order, Position, RestingOrder
from qat.data.broker.mock_broker import MockBroker
from qat.data.broker.pending_legs import leg_order_ref
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal, JournalEntry
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class ExitBroker(MockBroker):
    def __init__(self):
        super().__init__(seed=1)
        self._positions["AAA"] = Position("AAA", 100.0, 100.0)
        self.legs = [
            RestingOrder(
                "AAA", "stop", "sell", "STP", 100.0, "Submitted", stop_price=90.0, tif="GTC"
            ),
            RestingOrder(
                "AAA", "target", "sell", "LMT", 100.0, "Submitted", limit_price=120.0, tif="GTC"
            ),
        ]
        self.cancelled = []
        self.sent = []
        self.market_result = "rejected"
        self.pending_target = False
        self.halt_on_cancel = None
        self.on_cancel = None
        self.completed = []

    async def open_orders(self):
        return list(self.legs)

    async def completed_orders(self):
        return list(self.completed)

    async def cancel_order(self, order_id):
        if self.on_cancel:
            self.on_cancel()
        self.cancelled.append(order_id)
        if self.pending_target and order_id == "target":
            self.legs = [
                replace(leg, status="PendingCancel") if leg.order_id == order_id else leg
                for leg in self.legs
            ]
        else:
            self.completed.extend(
                replace(leg, status="Cancelled") for leg in self.legs if leg.order_id == order_id
            )
            self.legs = [leg for leg in self.legs if leg.order_id != order_id]
        if self.halt_on_cancel:
            self.halt_on_cancel.trip("halt during cancellation")
        return Order("AAA", "sell", 100.0, order_id, status="cancelled")

    async def place_order(self, order):
        self.sent.append(order)
        if order.is_protective_stop:
            order.status = "transmitted"
            self.legs.append(
                RestingOrder(
                    order.symbol,
                    order.order_id,
                    "sell",
                    "STP",
                    order.quantity,
                    "Submitted",
                    stop_price=order.stop_price,
                    tif="GTC",
                )
            )
            return order
        if self.market_result == "uncertain":
            raise TimeoutError("acknowledgement lost")
        order.status = self.market_result
        if self.market_result == "transmitted":
            self.legs.append(
                RestingOrder("AAA", order.order_id, "sell", "MKT", order.quantity, "Submitted")
            )
        return order


def make_oms(broker, tmp_path, switch=None):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = switch or KillSwitch()
    return OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )


def make_watchdog_oms(broker, tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), operator_name="DS")
    bus = EventBus()
    switch = KillSwitch()
    journal = DecisionJournal(tmp_path)
    journal.record(JournalEntry("entry-1", "AAA", "buy", "signed_off", "entry", entity_name="DS"))
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "AAA": {
                    "order_id": "entry-1",
                    "quantity": 100,
                    "stop_price": 90.0,
                    "opened_at": "2026-10-20T10:30:00+11:00",
                }
            }
        ),
        encoding="utf-8",
    )
    broker.owns_resting_order = lambda order: bool(order.order_ref and order.perm_id)

    async def no_pending(symbol):
        return None

    broker.pending_identity_reason = no_pending
    broker.last_owned_protection = lambda symbol: {
        "order_id": "999",
        "order_ref": "qat-stop-ref",
        "stop_price": 90.0,
        "seen_at": "2026-10-20T10:31:00+11:00",
    }
    broker.completed = [RestingOrder("AAA", "0", "sell", "STP", 100, "Cancelled", perm_id=999)]
    return OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
        journal=journal,
    )


def write_approved_card_legs(tmp_path, legs):
    (tmp_path / "approved_protection_legs.json").write_text(
        json.dumps({"AAA": {"entry_order_id": "entry-1", "legs": legs}}), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_watchdog_restores_once_after_two_empty_broker_reads(tmp_path):
    broker = ExitBroker()
    broker.legs = []
    oms = make_watchdog_oms(broker, tmp_path)

    await oms.watch_protection()

    assert len(broker.sent) == 1
    assert broker.sent[0].is_protective_stop
    assert broker.sent[0].quantity == 100
    assert broker.sent[0].stop_price == 90.0
    assert oms._exit_recovery is not None
    plan = oms._exit_recovery.plans["AAA"]
    assert (plan.approval_order_id, plan.approval_operator) == ("entry-1", "DS")
    assert any(
        "DS restoration under entry approval entry-1" in row["entity_name"]
        for row in oms.journal.entries()
        if row["outcome"] == "signed_off"
    )
    await oms.watch_protection()
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_watchdog_pending_cancel_alerts_and_never_rearms(tmp_path):
    broker = ExitBroker()
    broker.legs = [replace(broker.legs[0], status="PendingCancel")]
    oms = make_watchdog_oms(broker, tmp_path)

    await oms.watch_protection()

    assert broker.sent == []
    assert oms.kill_switch.tripped
    assert "AAA" in oms.protection_warnings()[0]


@pytest.mark.asyncio
async def test_watchdog_never_restores_a_looser_entry_stop_after_tightening(tmp_path):
    broker = ExitBroker()
    broker.legs = []
    oms = make_watchdog_oms(broker, tmp_path)
    broker.last_owned_protection = lambda symbol: {
        "order_id": "999",
        "order_ref": "qat-stop-ref",
        "stop_price": 95.0,
        "seen_at": "2026-10-20T10:31:00+11:00",
    }

    await oms.watch_protection()

    assert broker.sent == []
    assert oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_watchdog_waits_when_missing_stop_has_no_terminal_broker_evidence(tmp_path):
    broker = ExitBroker()
    broker.legs = []
    oms = make_watchdog_oms(broker, tmp_path)
    broker.completed = []

    await oms.watch_protection()

    assert broker.sent == []
    assert oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_watchdog_second_read_catches_new_pending_cancel_before_transmission(tmp_path):
    class ChangingBook(ExitBroker):
        def __init__(self):
            super().__init__()
            self.legs = []
            self.reads = 0

        async def open_orders(self):
            self.reads += 1
            if self.reads >= 2:
                return [
                    RestingOrder(
                        "AAA",
                        "999",
                        "sell",
                        "STP",
                        100,
                        "PendingCancel",
                        stop_price=90.0,
                        perm_id=999,
                    )
                ]
            return []

    broker = ChangingBook()
    oms = make_watchdog_oms(broker, tmp_path)
    await oms.watch_protection()

    assert broker.reads >= 2
    assert broker.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_role", ["runner", "banked"])
async def test_watchdog_restores_only_the_missing_card_leg(tmp_path, missing_role):
    class TwoLegBroker(ExitBroker):
        async def place_order(self, order):
            self.sent.append(order)
            order.status = "transmitted"
            self.legs.append(
                RestingOrder(
                    "AAA",
                    "new-stop",
                    "sell",
                    "STP",
                    order.quantity,
                    "Submitted",
                    stop_price=order.stop_price,
                    perm_id=2002,
                    order_ref=leg_order_ref(order.order_id, "primary"),
                    oca_group=order.oca_group,
                    tif="GTC",
                    oca_type=1 if order.oca_group else 0,
                )
            )
            return order

    broker = TwoLegBroker()
    original_banked = RestingOrder(
        "AAA",
        "banked",
        "sell",
        "STP",
        50,
        "Submitted",
        stop_price=90,
        perm_id=1000,
        order_ref="banked-ref",
        oca_group="BANKED",
        tif="GTC",
        oca_type=1,
    )
    original_runner = RestingOrder(
        "AAA",
        "runner",
        "sell",
        "STP",
        50,
        "Submitted",
        stop_price=90,
        perm_id=1001,
        order_ref="runner-ref",
        tif="GTC",
    )
    target = RestingOrder(
        "AAA",
        "target",
        "sell",
        "LMT",
        50,
        "Submitted",
        limit_price=120,
        perm_id=1003,
        order_ref="target-ref",
        oca_group="BANKED",
        tif="GTC",
        oca_type=1,
    )
    broker.legs = [original_banked if missing_role == "runner" else original_runner, target]
    oms = make_watchdog_oms(broker, tmp_path)
    prior_perm = 1001 if missing_role == "runner" else 1000
    broker.completed = [
        RestingOrder("AAA", "0", "sell", "STP", 50, "Cancelled", perm_id=prior_perm)
    ]
    broker.last_owned_protection = lambda symbol, ref: {
        "order_id": str(prior_perm),
        "order_ref": ref,
        "stop_price": 90,
        "seen_at": "2026-10-20T10:31:00+11:00",
    }
    write_approved_card_legs(
        tmp_path,
        [
            {
                "role": "banked",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "banked-ref",
                "perm_id": 1000,
                "oca_group": "BANKED",
                "target_order_ref": "target-ref",
                "target_perm_id": 1003,
                "target_price": 120,
            },
            {
                "role": "runner",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "runner-ref",
                "perm_id": 1001,
            },
        ],
    )

    await oms.watch_protection()

    assert len(broker.sent) == 1
    assert broker.sent[0].quantity == 50
    assert broker.sent[0].stop_price == 90
    assert broker.sent[0].oca_group == ("BANKED" if missing_role == "banked" else None)
    expected_sibling = "banked-ref" if missing_role == "runner" else "runner-ref"
    assert [order.order_ref for order in broker.legs[:2]] == [expected_sibling, "target-ref"]
    assert oms._exit_recovery is not None and "AAA" not in oms._exit_recovery.plans
    lineage = json.loads((tmp_path / "protection_leg_lineage.json").read_text())
    assert lineage[f"AAA:{missing_role}"]["current_perm_id"] == 2002
    await oms.watch_protection()
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_watchdog_restores_two_confirmed_missing_card_legs_one_at_a_time(tmp_path):
    class TwoLegBroker(ExitBroker):
        async def place_order(self, order):
            self.sent.append(order)
            order.status = "transmitted"
            self.legs.append(
                RestingOrder(
                    "AAA",
                    order.order_id,
                    "sell",
                    "STP",
                    order.quantity,
                    "Submitted",
                    stop_price=order.stop_price,
                    perm_id=2000 + len(self.sent),
                    order_ref=leg_order_ref(order.order_id, "primary"),
                    oca_group=order.oca_group,
                    tif="GTC",
                    oca_type=1 if order.oca_group else 0,
                )
            )
            return order

    broker = TwoLegBroker()
    broker.legs = []
    oms = make_watchdog_oms(broker, tmp_path)
    broker.completed = [
        RestingOrder("AAA", "0", "sell", "STP", 50, "Cancelled", perm_id=1000),
        RestingOrder("AAA", "0", "sell", "STP", 50, "Cancelled", perm_id=1001),
    ]
    broker.last_owned_protection = lambda symbol, ref: {
        "order_id": "1000" if ref == "banked-ref" else "1001",
        "order_ref": ref,
        "stop_price": 90,
        "seen_at": "2026-10-20T10:31:00+11:00",
    }
    write_approved_card_legs(
        tmp_path,
        [
            {
                "role": "banked",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "banked-ref",
                "perm_id": 1000,
            },
            {
                "role": "runner",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "runner-ref",
                "perm_id": 1001,
            },
        ],
    )

    await oms.watch_protection()
    assert len(broker.sent) == 1
    assert len(broker.legs) == 1
    assert broker.sent[0].quantity == 50
    assert oms._exit_recovery is not None and "AAA" not in oms._exit_recovery.plans
    await oms.watch_protection()
    assert len(broker.sent) == 2
    assert len(broker.legs) == 2
    assert sum(order.quantity for order in broker.legs) == 100
    assert "AAA" not in oms._exit_recovery.plans
    lineage = json.loads((tmp_path / "protection_leg_lineage.json").read_text())
    assert set(lineage) == {"AAA:banked", "AAA:runner"}


@pytest.mark.asyncio
async def test_watchdog_waits_if_missing_banked_leg_has_pending_cancel_target(tmp_path):
    broker = ExitBroker()
    broker.legs = [
        RestingOrder(
            "AAA",
            "runner",
            "sell",
            "STP",
            50,
            "Submitted",
            stop_price=90,
            perm_id=1001,
            order_ref="runner-ref",
            tif="GTC",
        ),
        RestingOrder(
            "AAA",
            "target",
            "sell",
            "LMT",
            50,
            "PendingCancel",
            limit_price=120,
            perm_id=1003,
            order_ref="target-ref",
            oca_group="BANKED",
            tif="GTC",
            oca_type=1,
        ),
    ]
    oms = make_watchdog_oms(broker, tmp_path)
    write_approved_card_legs(
        tmp_path,
        [
            {
                "role": "banked",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "banked-ref",
                "perm_id": 1000,
                "oca_group": "BANKED",
                "target_order_ref": "target-ref",
                "target_perm_id": 1003,
                "target_price": 120,
            },
            {
                "role": "runner",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "runner-ref",
                "perm_id": 1001,
            },
        ],
    )
    await oms.watch_protection()
    assert broker.sent == []
    assert oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_unacknowledged_card_leg_stays_durable_and_is_never_sent_twice(tmp_path):
    class NoAcknowledgement(ExitBroker):
        async def place_order(self, order):
            self.sent.append(order)
            order.status = "transmitted"
            return order

    broker = NoAcknowledgement()
    broker.legs = [
        RestingOrder(
            "AAA",
            "banked",
            "sell",
            "STP",
            50,
            "Submitted",
            stop_price=90,
            perm_id=1000,
            order_ref="banked-ref",
            tif="GTC",
        )
    ]
    oms = make_watchdog_oms(broker, tmp_path)
    broker.completed = [RestingOrder("AAA", "0", "sell", "STP", 50, "Cancelled", perm_id=1001)]
    broker.last_owned_protection = lambda symbol, ref: {
        "order_id": "1001",
        "order_ref": ref,
        "stop_price": 90,
        "seen_at": "2026-10-20T10:31:00+11:00",
    }
    write_approved_card_legs(
        tmp_path,
        [
            {
                "role": "banked",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "banked-ref",
                "perm_id": 1000,
            },
            {
                "role": "runner",
                "quantity": 50,
                "stop_price": 90,
                "order_ref": "runner-ref",
                "perm_id": 1001,
            },
        ],
    )

    await oms.watch_protection()
    assert len(broker.sent) == 1
    assert oms._exit_recovery is not None
    assert oms._exit_recovery.plans["AAA"].stage == "working"
    assert oms._exit_recovery.plans["AAA"].replacement_order_ref
    await oms.recover_exit_protection()
    await oms.watch_protection()
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_corporate_warning_uses_only_ds_pinned_nonfixture_authority(tmp_path):
    broker = ExitBroker()
    broker._positions = {"BHP.AX": Position("BHP.AX", 10, 60, qat_holding=False)}
    authority = {
        "schema": "asx-corporate-actions-v1",
        "version": 1,
        "published_on": "2026-10-22",
        "coverage_start": "2026-10-22",
        "coverage_end": "2026-10-23",
        "source": "https://www.asx.com.au/connectivity-and-data/information-services/reference-data",
        "fixture": False,
        "events": [
            {
                "symbol": "BHP.AX",
                "ex_session": "2026-10-23",
                "split_ratio": [1, 1],
                "dividend": "0.50",
                "evidence_reference": "https://www.asx.com.au/markets/BHP",
            }
        ],
    }
    path = tmp_path / "actions.json"
    path.write_text(json.dumps(authority), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        protection_actions_authority_path=str(path),
        protection_actions_authority_sha256=digest,
    )
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )

    await oms.watch_corporate_stop_risk(today=date(2026, 10, 22))
    assert "BHP.AX" in oms.corporate_stop_warnings()[0]
    assert broker.sent == []

    authority["fixture"] = True
    path.write_text(json.dumps(authority), encoding="utf-8")
    await oms.watch_corporate_stop_risk(today=date(2026, 10, 22))
    assert "unreadable" in oms.corporate_stop_warnings()[0]
    path.unlink()
    await oms.watch_corporate_stop_risk(today=date(2026, 10, 22))
    assert oms.corporate_stop_warnings() == ()


@pytest.mark.asyncio
async def test_a_rejected_exit_restores_the_original_stop(tmp_path):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    stops = [leg for leg in broker.legs if leg.order_type == "STP"]
    assert len(stops) == 1
    assert stops[0].quantity == 100.0
    assert stops[0].stop_price == 90.0


@pytest.mark.asyncio
async def test_recovery_intent_is_durable_before_any_cancel(tmp_path):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)

    def check_intent():
        assert (tmp_path / "exit_recovery.json").is_file()
        assert "AAA" in (tmp_path / "exit_recovery.json").read_text()

    broker.on_cancel = check_intent
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    assert broker.cancelled


@pytest.mark.asyncio
async def test_pending_target_cancel_leaves_the_stop_in_place(tmp_path):
    broker = ExitBroker()
    broker.pending_target = True
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    signed = await oms.sign_off(order.order_id, "operator")
    assert signed.status == "rejected"
    assert broker.cancelled == ["target"]
    assert any(leg.order_id == "stop" for leg in broker.legs)
    assert broker.sent == []


@pytest.mark.asyncio
async def test_oca_partner_disappears_with_target_and_is_not_cancelled_again(tmp_path):
    class OcaBroker(ExitBroker):
        async def cancel_order(self, order_id):
            result = await super().cancel_order(order_id)
            if order_id == "target":
                self.completed.extend(replace(leg, status="Cancelled") for leg in self.legs)
                self.legs = []
            return result

    broker = OcaBroker()
    broker.legs = [replace(leg, oca_group="BOQ-OCA") for leg in broker.legs]
    oms = make_oms(broker, tmp_path)
    released = await oms._release_protective_legs("AAA", 100.0, "manual_close")
    assert released is True
    assert broker.cancelled == ["target"]


@pytest.mark.asyncio
async def test_oca_partner_without_completed_order_source_halts_close(tmp_path):
    class OcaBroker(ExitBroker):
        async def cancel_order(self, order_id):
            target = next(leg for leg in self.legs if leg.order_id == order_id)
            result = await super().cancel_order(order_id)
            if order_id == "target":
                # The requested leg is explicitly terminal; only the OCA
                # partner's disappearance lacks a completed-order source.
                self.legs = [replace(target, status="Cancelled")]
            return result

    broker = OcaBroker()
    broker.legs = [replace(leg, oca_group="BOQ-OCA") for leg in broker.legs]
    broker.completed_orders = None
    oms = make_oms(broker, tmp_path)

    assert await oms._release_protective_legs("AAA", 100.0, "manual_close") is False
    assert broker.cancelled == ["target"]
    assert oms._exit_recovery is not None
    assert "AAA" in oms._exit_recovery.plans


@pytest.mark.asyncio
async def test_pending_target_settles_with_oca_partner_before_sell(tmp_path):
    class DelayedOcaBroker(ExitBroker):
        def __init__(self):
            super().__init__()
            self.after_cancel_reads = 0

        async def cancel_order(self, order_id):
            result = await super().cancel_order(order_id)
            if order_id == "target":
                self.legs = [
                    replace(leg, status="PendingCancel") if leg.order_id == "target" else leg
                    for leg in self.legs
                ]
            return result

        async def open_orders(self):
            if "target" in self.cancelled:
                self.after_cancel_reads += 1
                if self.after_cancel_reads >= 2:
                    self.completed.extend(replace(leg, status="Cancelled") for leg in self.legs)
                    self.legs = []
            return await super().open_orders()

    broker = DelayedOcaBroker()
    broker.pending_target = True
    broker.legs = [replace(leg, oca_group="BOQ-OCA") for leg in broker.legs]
    oms = make_oms(broker, tmp_path)
    released = await oms._release_protective_legs("AAA", 100.0, "manual_close")
    assert released is True
    assert broker.cancelled == ["target"]


@pytest.mark.asyncio
async def test_oca_partner_pending_cancel_is_not_cancelled_twice(tmp_path):
    class PendingPartnerBroker(ExitBroker):
        def __init__(self):
            super().__init__()
            self.legs = [replace(leg, oca_group="OCA-1") for leg in self.legs]
            self.after_cancel_reads = 0

        async def cancel_order(self, order_id):
            assert order_id == "target"
            self.cancelled.append(order_id)
            self.legs = [
                replace(leg, status="PendingCancel") for leg in self.legs if leg.order_id == "stop"
            ]
            return Order("AAA", "sell", 100, order_id, status="cancelled")

        async def open_orders(self):
            if self.cancelled:
                self.after_cancel_reads += 1
                if self.after_cancel_reads >= 2:
                    return []
            return list(self.legs)

        async def completed_orders(self):
            completed = [
                RestingOrder("AAA", "target", "sell", "LMT", 100, "Cancelled", oca_group="OCA-1")
            ]
            if self.after_cancel_reads >= 2:
                completed.append(
                    RestingOrder("AAA", "stop", "sell", "STP", 100, "Cancelled", oca_group="OCA-1")
                )
            return completed

    broker = PendingPartnerBroker()
    oms = make_oms(broker, tmp_path)
    assert await oms._release_protective_legs("AAA", 100, "manual_close")
    assert broker.cancelled == ["target"]
    assert broker.after_cancel_reads >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop_terminal", "expected_release"),
    [("Cancelled", True), ("Filled", False)],
)
async def test_boq_replay_matches_order_id_zero_rows_by_perm_id(
    tmp_path, stop_terminal, expected_release
):
    class BoqReplayBroker(ExitBroker):
        def __init__(self):
            super().__init__()
            self.legs = [
                replace(
                    self.legs[0],
                    order_id="1216552513",
                    broker_order_id=153,
                    perm_id=1216552513,
                    oca_group="1216552511",
                ),
                replace(
                    self.legs[1],
                    order_id="1216552512",
                    broker_order_id=152,
                    perm_id=1216552512,
                    oca_group="1216552511",
                ),
            ]
            self.read_after_cancel = 0
            self.completed_reads = 0

        async def cancel_order(self, order_id):
            assert order_id == "1216552512"
            self.cancelled.append(order_id)
            return Order("AAA", "sell", 100, order_id, status="cancelled")

        async def open_orders(self):
            if not self.cancelled:
                return list(self.legs)
            self.read_after_cancel += 1
            if self.read_after_cancel == 1:
                return [
                    (
                        replace(leg, order_id="0", status="PendingCancel")
                        if leg.perm_id == 1216552512
                        else leg
                    )
                    for leg in self.legs
                ]
            return []

        async def completed_orders(self):
            self.completed_reads += 1
            return [
                replace(
                    leg,
                    order_id="0",
                    status=stop_terminal if leg.perm_id == 1216552513 else "Cancelled",
                )
                for leg in self.legs
            ]

    broker = BoqReplayBroker()
    oms = make_oms(broker, tmp_path)
    assert await oms._release_protective_legs("AAA", 100, "manual_close") is expected_release
    assert broker.cancelled == ["1216552512"]
    assert broker.read_after_cancel == 2
    assert broker.completed_reads >= 1


@pytest.mark.asyncio
async def test_halt_after_cancellation_allows_only_captured_stop_restoration(tmp_path):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)
    # Trip only after the final stop cancellation, not after the target.
    original = broker.cancel_order

    async def cancel_and_halt(order_id):
        result = await original(order_id)
        if order_id == "stop":
            oms.kill_switch.trip("halt after final cancel")
        return result

    broker.cancel_order = cancel_and_halt
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    signed = await oms.sign_off(order.order_id, "operator")
    assert signed.status == "rejected"
    assert oms.kill_switch.tripped
    assert len(broker.sent) == 1
    assert broker.sent[0].is_protective_stop
    assert broker.sent[0].stop_price == 90.0
    assert broker.sent[0].quantity == 100.0


@pytest.mark.asyncio
async def test_uncertain_market_transmission_does_not_add_another_sell(tmp_path):
    broker = ExitBroker()
    broker.market_result = "uncertain"
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    await oms.recover_exit_protection()
    assert len(broker.sent) == 1
    assert not broker.sent[0].is_protective_stop
    assert oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_restart_does_not_restore_over_a_working_exit(tmp_path):
    broker = ExitBroker()
    broker.market_result = "transmitted"
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 40.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    restarted = make_oms(broker, tmp_path)
    restarted.kill_switch.trip("restart under halt")
    await restarted.recover_exit_protection()
    assert len(broker.sent) == 1
    # Broker confirms the exit has finished, leaving a 60-share holding.
    broker.legs = []
    broker._positions["AAA"] = Position("AAA", 60.0, 100.0)
    await restarted.recover_exit_protection()
    assert len(broker.sent) == 2
    assert broker.sent[-1].is_protective_stop
    assert broker.sent[-1].quantity == 60.0
    # Another sweep must not duplicate the stop.
    await restarted.recover_exit_protection()
    assert len(broker.sent) == 2


@pytest.mark.asyncio
async def test_failed_journal_update_cannot_retransmit_an_accepted_exit(tmp_path, monkeypatch):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)

    async def accept_as_new_object(order):
        broker.sent.append(order)
        return replace(order, status="transmitted")

    monkeypatch.setattr(broker, "place_order", accept_as_new_object)
    original_stage = oms._exit_recovery.stage

    def fail_after_acceptance(symbol, stage):
        if stage == "working":
            raise OSError("disk full after broker acknowledgement")
        original_stage(symbol, stage)

    monkeypatch.setattr(oms._exit_recovery, "stage", fail_after_acceptance)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    try:
        await oms.sign_off(order.order_id, "operator")
    except OSError:
        pass
    assert order.order_id in oms._transmitted
    with pytest.raises(ValueError):
        await oms.sign_off(order.order_id, "operator")
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_unprotected_exit_with_unknown_outcome_is_durable(tmp_path):
    broker = ExitBroker()
    broker.legs = []
    broker.market_result = "uncertain"
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    assert oms.kill_switch.tripped
    restarted = make_oms(broker, tmp_path)
    assert restarted.kill_switch.tripped
    await restarted.recover_exit_protection()
    second = await restarted.submit_exit_order("AAA", 100.0, 100.0)
    assert second.status == "rejected"
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_failed_recovery_journal_write_leaves_original_bracket(tmp_path, monkeypatch):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)

    def unavailable(plan):
        raise OSError("journal cannot be written")

    monkeypatch.setattr(oms._exit_recovery, "put", unavailable)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    assert (await oms.sign_off(order.order_id, "operator")).status == "rejected"
    assert broker.cancelled == []
    assert broker.sent == []
    assert {leg.order_id for leg in broker.legs} == {"stop", "target"}


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining", [-5.0, 101.0])
async def test_recovery_never_sells_against_short_or_enlarged_holding(tmp_path, remaining):
    broker = ExitBroker()
    broker.market_result = "transmitted"
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 40.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    broker.legs = []
    broker._positions["AAA"] = Position("AAA", remaining, 100.0)
    await oms.recover_exit_protection()
    assert len(broker.sent) == 1
    assert oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_preexisting_pending_stop_cannot_race_a_working_exit(tmp_path):
    broker = ExitBroker()
    broker.market_result = "transmitted"
    oms = make_oms(broker, tmp_path)
    old_stop = await oms.submit_protective_stop("AAA", 100.0, 90.0)
    order = await oms.submit_exit_order("AAA", 40.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    assert (await oms.sign_off(old_stop.order_id, "operator")).status == "rejected"
    assert (await oms.submit_protective_stop("AAA", 100.0, 90.0)).status == "rejected"
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_a_working_sell_arriving_during_recovery_preflight_blocks_restoration(tmp_path):
    broker = ExitBroker()
    broker.market_result = "transmitted"
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 40.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    broker.legs = []
    original_positions = broker.positions

    async def positions_with_competing_sell():
        broker.legs = [RestingOrder("AAA", "other", "sell", "MKT", 100.0, "Submitted")]
        return await original_positions()

    broker.positions = positions_with_competing_sell
    await oms.recover_exit_protection()
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_halt_does_not_authorise_an_unrelated_protective_order(tmp_path):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_protective_stop("AAA", 100.0, 90.0)
    oms.kill_switch.trip("ordinary halt")
    assert (await oms.sign_off(order.order_id, "operator")).status == "rejected"
    assert broker.sent == []


@pytest.mark.asyncio
async def test_holding_shrinking_during_final_recovery_check_blocks_stop(tmp_path):
    broker = ExitBroker()
    broker.market_result = "transmitted"
    oms = make_oms(broker, tmp_path)
    order = await oms.submit_exit_order("AAA", 40.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    broker.legs = []
    reads = 0

    async def shrinking_book():
        nonlocal reads
        reads += 1
        if reads == 2:
            broker._positions["AAA"] = Position("AAA", 60.0, 100.0)
        return []

    broker.open_orders = shrinking_book
    await oms.recover_exit_protection()
    assert len(broker.sent) == 1
    assert oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_replacement_stop_during_cancel_blocks_market_exit(tmp_path):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)
    original = broker.cancel_order

    async def replace_stop(order_id):
        result = await original(order_id)
        if order_id == "stop":
            broker.legs.append(
                RestingOrder(
                    "AAA", "replacement", "sell", "STP", 100.0, "Submitted", stop_price=90.0
                )
            )
        return result

    broker.cancel_order = replace_stop
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    assert (await oms.sign_off(order.order_id, "operator")).status == "rejected"
    assert broker.sent == []


@pytest.mark.asyncio
async def test_old_pending_stop_stays_invalid_after_recovery_finishes(tmp_path):
    broker = ExitBroker()
    oms = make_oms(broker, tmp_path)
    old_stop = await oms.submit_protective_stop("AAA", 100.0, 90.0)
    order = await oms.submit_exit_order("AAA", 100.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    await oms.recover_exit_protection()
    assert not oms.exit_protection_pending("AAA")
    if old_stop.status == "pending_signoff":
        await oms.sign_off(old_stop.order_id, "operator")
    assert old_stop.status == "rejected"
    assert len([o for o in broker.sent if o.is_protective_stop]) == 1
