"""Blotter filtering and bulk sign-off (spec M11).

Bulk approval is a convenience, not a loosening of the sign-off gate: these
tests pin down that the confirmation dialog still itemises what is about to be
transmitted, and that declining it transmits nothing at all.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain.risk_engine.engine import OrderCandidate
from qat.presentation.blotter import BlotterScreen
from qat.presentation.runtime import Runtime


async def _pending_orders(runtime: Runtime, symbols: list[str]) -> list[Order]:
    orders = []
    for symbol in symbols:
        candidate = OrderCandidate(
            symbol=symbol,
            side="buy",
            price=100.0,
            atr=2.0,
            win_rate=0.55,
            win_loss_ratio=1.5,
            candidate_returns=pd.Series([0.01, -0.02, 0.015, -0.01, 0.02] * 5),
        )
        orders.append(await runtime.oms.submit_order(candidate, 100_000.0, {}, {}))
    return orders


def _build(qtbot) -> tuple[BlotterScreen, Runtime]:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    screen = BlotterScreen(runtime)
    qtbot.addWidget(screen)
    return screen, runtime


async def test_select_all_pending_enables_bulk_actions(qtbot):
    screen, runtime = _build(qtbot)
    await _pending_orders(runtime, ["AAA", "BBB", "CCC"])
    screen._timer_refresh()

    screen._on_select_all_pending()

    assert len(screen._selected_pending_orders()) == 3
    assert screen.sign_off_button.isEnabled()
    assert "(3)" in screen.sign_off_button.text()


async def test_bulk_sign_off_transmits_every_selected_order(qtbot):
    screen, runtime = _build(qtbot)
    orders = await _pending_orders(runtime, ["AAA", "BBB", "CCC"])
    screen._timer_refresh()
    screen._confirm = lambda message: True
    screen._on_select_all_pending()

    screen._on_sign_off_clicked()
    await asyncio.sleep(0.05)

    assert all(runtime.oms.get_order(o.order_id).status == "filled" for o in orders)


async def test_declining_the_dialog_transmits_nothing(qtbot):
    screen, runtime = _build(qtbot)
    orders = await _pending_orders(runtime, ["AAA", "BBB"])
    screen._timer_refresh()
    screen._confirm = lambda message: False
    screen._on_select_all_pending()

    screen._on_sign_off_clicked()
    await asyncio.sleep(0.05)

    assert all(runtime.oms.get_order(o.order_id).status == "pending_signoff" for o in orders)


async def test_confirmation_dialog_itemises_the_orders(qtbot):
    screen, runtime = _build(qtbot)
    await _pending_orders(runtime, ["AAA", "BBB"])
    screen._timer_refresh()
    seen: list[str] = []
    screen._confirm = lambda message: (seen.append(message), False)[1]
    screen._on_select_all_pending()

    screen._on_sign_off_clicked()

    assert len(seen) == 1
    assert "AAA" in seen[0] and "BBB" in seen[0]
    assert "2 order(s)" in seen[0]


async def test_bulk_failures_are_reported_together(qtbot):
    screen, runtime = _build(qtbot)
    await _pending_orders(runtime, ["AAA", "BBB"])
    screen._timer_refresh()

    async def failing(order_id: str, operator: str) -> Order:
        raise RuntimeError("broker down")

    runtime.oms.sign_off = failing  # type: ignore[method-assign]
    errors: list[str] = []
    screen._show_error = errors.append  # type: ignore[method-assign]
    screen._confirm = lambda message: True
    screen._on_select_all_pending()

    screen._on_sign_off_clicked()
    await asyncio.sleep(0.05)

    assert len(errors) == 1
    assert "2 of 2" in errors[0]
    assert "broker down" in errors[0]


async def test_status_filter_defaults_to_pending_and_can_show_all(qtbot):
    screen, runtime = _build(qtbot)
    orders = await _pending_orders(runtime, ["AAA", "BBB"])
    await runtime.oms.reject_order(orders[0].order_id, "alice", "test")
    screen._timer_refresh()

    assert screen.status_filter.currentText() == "Pending sign-off"
    assert len(screen._visible_orders()) == 1  # the rejected one is hidden

    screen.status_filter.setCurrentText("All")
    assert len(screen._visible_orders()) == 2


async def test_unchanged_order_set_is_not_re_rendered(qtbot):
    """Rebuilding every row on the 2s timer is what made a large blotter
    unusable; an unchanged set must be a no-op."""
    screen, runtime = _build(qtbot)
    await _pending_orders(runtime, ["AAA"])
    screen._timer_refresh()

    renders = 0
    original = screen._render

    def counting(orders):
        nonlocal renders
        renders += 1
        original(orders)

    screen._render = counting  # type: ignore[method-assign]
    screen._timer_refresh()
    screen._timer_refresh()

    assert renders == 0

    await _pending_orders(runtime, ["BBB"])
    screen._timer_refresh()
    assert renders == 1
