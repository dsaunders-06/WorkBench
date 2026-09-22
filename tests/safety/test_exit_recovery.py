"""Failure injection for the protective-stop handoff, using the real OMS."""

from dataclasses import replace

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order, Position, RestingOrder
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class ExitBroker(MockBroker):
    def __init__(self):
        super().__init__(seed=1)
        self._positions["AAA"] = Position("AAA", 100.0, 100.0)
        self.legs = [
            RestingOrder("AAA", "stop", "sell", "STP", 100.0, "Submitted", stop_price=90.0),
            RestingOrder("AAA", "target", "sell", "LMT", 100.0, "Submitted", limit_price=120.0),
        ]
        self.cancelled = []
        self.sent = []
        self.market_result = "rejected"
        self.pending_target = False
        self.halt_on_cancel = None
        self.on_cancel = None

    async def open_orders(self):
        return list(self.legs)

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
