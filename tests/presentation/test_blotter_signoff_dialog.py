"""UI-layer safety test (spec §I): selecting a pending_signoff order and
clicking Sign Off must never reach OMS.sign_off without the confirmation
dialog's explicit Yes - the same "no order without sign-off" invariant as
tests/safety/test_no_order_without_signoff.py, checked one layer up at the
Qt widget boundary instead of directly against OMS.

_confirm() is monkeypatched rather than driving a real QMessageBox so the
test is deterministic and doesn't block on a modal dialog.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain.risk_engine.engine import OrderCandidate
from qat.presentation.blotter import BlotterScreen
from qat.presentation.runtime import Runtime


async def _build_pending_order(runtime: Runtime) -> Order:
    candidate = OrderCandidate(
        symbol=runtime.watchlist[0],
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.55,
        win_loss_ratio=1.5,
        candidate_returns=pd.Series([0.01, -0.02, 0.015, -0.01, 0.02] * 5),
    )
    order = await runtime.oms.submit_order(candidate, 100_000.0, {}, {})
    assert order.status == "pending_signoff"
    return order


def _spy_on_sign_off(runtime: Runtime, calls: list[str]) -> None:
    original_sign_off = runtime.oms.sign_off

    async def spy(order_id: str, operator: str) -> Order:
        calls.append(order_id)
        return await original_sign_off(order_id, operator)

    runtime.oms.sign_off = spy  # type: ignore[method-assign]


async def test_sign_off_never_called_without_dialog_confirmation(qtbot):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    order = await _build_pending_order(runtime)

    screen = BlotterScreen(runtime)
    qtbot.addWidget(screen)
    screen._timer_refresh()

    sign_off_calls: list[str] = []
    _spy_on_sign_off(runtime, sign_off_calls)
    screen._confirm = lambda message: False

    screen.orders_table.selectRow(0)
    screen._on_sign_off_clicked()
    await asyncio.sleep(0.05)

    assert sign_off_calls == []
    assert runtime.oms.get_order(order.order_id).status == "pending_signoff"


async def test_sign_off_called_after_dialog_confirms(qtbot):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    order = await _build_pending_order(runtime)

    screen = BlotterScreen(runtime)
    qtbot.addWidget(screen)
    screen._timer_refresh()

    sign_off_calls: list[str] = []
    _spy_on_sign_off(runtime, sign_off_calls)
    screen._confirm = lambda message: True

    screen.orders_table.selectRow(0)
    screen._on_sign_off_clicked()
    await asyncio.sleep(0.05)

    assert sign_off_calls == [order.order_id]
    assert runtime.oms.get_order(order.order_id).status == "filled"
