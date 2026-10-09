"""Phase 3 auction intent must fail closed until paper capability is verified."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.alpaca_adapter import AlpacaAdapter
from qat.data.broker.ib_adapter import IBAdapter
from qat.data.broker.ib_translate import UnrepresentableOrderError, to_ib_order, to_ib_parent
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.card_orders import CardOrderStore, card_order_id
from qat.domain.oms.oms import OMS
from qat.domain.oms.order_identity import OrderIdentityStore
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

SYDNEY = ZoneInfo("Australia/Sydney")


def _auction_order(card_id: str = "card-1") -> Order:
    return Order(
        symbol="BHP.AX",
        side="buy",
        quantity=10,
        order_id=card_order_id(card_id),
        order_type="opening_auction_limit",
        limit_price=42.5,
        auction_open=datetime(2026, 10, 12, 10, 0, tzinfo=SYDNEY),
        stop_price=40.0,
    )


def test_auction_intent_cannot_be_approximated_as_gtc_or_day() -> None:
    order = _auction_order()
    for translate in (to_ib_order, to_ib_parent):
        with pytest.raises(UnrepresentableOrderError, match="opening auction"):
            translate(order)


def test_card_order_id_is_fixed_namespace_uuid5() -> None:
    assert card_order_id("card-1") == card_order_id("card-1")
    assert card_order_id("card-1") != card_order_id("card-2")
    assert card_order_id("card-1") == "f97c3625-6a48-5bd5-807e-b4080429a6cb"


def test_card_key_reservation_survives_restart_and_returns_existing_order(tmp_path) -> None:
    first = CardOrderStore(tmp_path / "card_orders.json")
    order = _auction_order()
    assert first.reserve("card-1", order) == order

    restarted = CardOrderStore(tmp_path / "card_orders.json")
    assert restarted.reserve("card-1", _auction_order()) == order
    assert len(restarted.orders) == 1


def test_card_key_cannot_be_reused_for_changed_order(tmp_path) -> None:
    store = CardOrderStore(tmp_path / "card_orders.json")
    store.reserve("card-1", _auction_order())
    changed = _auction_order()
    changed.quantity = 11
    with pytest.raises(ValueError, match="already reserved"):
        store.reserve("card-1", changed)


def test_caller_mutation_cannot_change_reserved_intent(tmp_path) -> None:
    store = CardOrderStore(tmp_path / "card_orders.json")
    order = _auction_order()
    store.reserve("card-1", order)
    order.quantity = 99
    assert store.reserve("card-1", _auction_order()).quantity == 10
    exposed = store.orders["card-1"]
    exposed.quantity = 88
    assert store.reserve("card-1", _auction_order()).quantity == 10


def test_order_id_must_match_card_key(tmp_path) -> None:
    store = CardOrderStore(tmp_path / "card_orders.json")
    order = _auction_order()
    order.order_id = "arbitrary"
    with pytest.raises(ValueError, match="UUIDv5"):
        store.reserve("card-1", order)


def test_existing_transmission_identity_can_retain_auction_open(tmp_path) -> None:
    path = tmp_path / "inflight_orders.json"
    order = _auction_order()
    store = OrderIdentityStore(path)
    store.put(order.order_id, order, stage="transmitting")
    restored = OrderIdentityStore(path)
    assert restored.records[order.order_id].order.auction_open == order.auction_open


@pytest.mark.asyncio
async def test_all_broker_entrypoints_refuse_unverified_auction_intent() -> None:
    order = _auction_order()
    for adapter_type in (AlpacaAdapter, IBAdapter):
        adapter = adapter_type.__new__(adapter_type)
        with pytest.raises(ValueError, match="opening auction"):
            await adapter.place_order(order)


@pytest.mark.asyncio
async def test_oms_refuses_unverified_auction_intent_before_fake_broker_call(tmp_path) -> None:
    class CountingBroker(MockBroker):
        calls = 0

        async def place_order(self, order: Order) -> Order:
            self.calls += 1
            return await super().place_order(order)

    bus = EventBus()
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    switch = KillSwitch(data_dir=tmp_path)
    broker = CountingBroker(seed=1)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    pending = oms._new_pending_order(
        "BHP.AX",
        "buy",
        10,
        42.5,
        "authoritative_swing",
        stop_price=40,
        order_id=card_order_id("card-1"),
        order_type="opening_auction_limit",
        limit_price=42.5,
        auction_open=datetime(2026, 10, 12, 10, 0, tzinfo=SYDNEY),
    )
    refused = await oms.sign_off(pending.order_id, "operator")
    assert refused.status == "rejected"
    assert broker.calls == 0
