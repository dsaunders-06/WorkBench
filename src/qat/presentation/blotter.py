"""Order Blotter (spec §I/§K): every order OMS knows about, with the
mandatory human sign-off gate at the UI layer too - selecting a
pending_signoff order and clicking Sign Off always opens a confirmation
dialog first; oms.sign_off() is only ever reached from inside the
confirmed branch. Paper/live colour coding matches the main window banner
so the mode is unmistakable on this screen as well (spec §13.3).

_confirm() is a thin wrapper around QMessageBox.question kept as its own
method specifically so tests can monkeypatch it (return True/False) and
assert sign_off is/isn't reached, without driving real Qt dialog widgets.
"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.data.broker.adapter import Order
from qat.presentation.runtime import Runtime

_REFRESH_INTERVAL_MS = 2000
_PAPER_STYLE = "background-color: #1b5e20; color: white; padding: 6px; font-weight: bold;"
_LIVE_STYLE = "background-color: #b71c1c; color: white; padding: 6px; font-weight: bold;"
_OPERATOR = "operator (blotter)"
_COLUMNS = ("Order ID", "Symbol", "Side", "Quantity", "Status", "Created At")


class BlotterScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime

        layout = QVBoxLayout(self)

        banner = QLabel(f"MODE: {runtime.settings.trading_mode.upper()}")
        banner.setStyleSheet(_LIVE_STYLE if runtime.settings.is_live else _PAPER_STYLE)
        layout.addWidget(banner)

        self.orders_table = QTableWidget(0, len(_COLUMNS))
        self.orders_table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.orders_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.orders_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.orders_table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.orders_table)

        button_row = QHBoxLayout()
        self.sign_off_button = QPushButton("Sign Off Selected")
        self.sign_off_button.setEnabled(False)
        self.sign_off_button.clicked.connect(self._on_sign_off_clicked)
        self.reject_button = QPushButton("Reject Selected")
        self.reject_button.setEnabled(False)
        self.reject_button.clicked.connect(self._on_reject_clicked)
        button_row.addWidget(self.sign_off_button)
        button_row.addWidget(self.reject_button)
        layout.addLayout(button_row)

        self._timer_refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._timer_refresh)
        self._timer.start(_REFRESH_INTERVAL_MS)

    def _timer_refresh(self) -> None:
        selected_id = self._selected_order_id()
        orders = self.runtime.oms.orders()
        self.orders_table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            self.orders_table.setItem(row, 0, QTableWidgetItem(order.order_id))
            self.orders_table.setItem(row, 1, QTableWidgetItem(order.symbol))
            self.orders_table.setItem(row, 2, QTableWidgetItem(order.side))
            self.orders_table.setItem(row, 3, QTableWidgetItem(f"{order.quantity:g}"))
            self.orders_table.setItem(row, 4, QTableWidgetItem(order.status))
            self.orders_table.setItem(
                row, 5, QTableWidgetItem(f"{order.created_at:%Y-%m-%d %H:%M:%S}")
            )
            if order.order_id == selected_id:
                self.orders_table.selectRow(row)
        self._on_selection_changed()

    def _selected_order_id(self) -> str | None:
        selected = self.orders_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.orders_table.item(row, 0)
        return item.text() if item else None

    def _selected_order(self) -> Order | None:
        order_id = self._selected_order_id()
        if order_id is None:
            return None
        try:
            return self.runtime.oms.get_order(order_id)
        except KeyError:
            return None

    def _on_selection_changed(self) -> None:
        order = self._selected_order()
        pending = order is not None and order.status == "pending_signoff"
        self.sign_off_button.setEnabled(pending)
        self.reject_button.setEnabled(pending)

    def _confirm(self, message: str) -> bool:
        result = QMessageBox.question(
            self,
            "Confirm order action",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _on_sign_off_clicked(self) -> None:
        order = self._selected_order()
        if order is None or order.status != "pending_signoff":
            return
        confirmed = self._confirm(
            f"Sign off order {order.order_id}: {order.side.upper()} {order.quantity:g} "
            f"{order.symbol}?\n\nThis transmits the order to the broker."
        )
        if not confirmed:
            return
        asyncio.ensure_future(self._do_sign_off(order.order_id))

    async def _do_sign_off(self, order_id: str) -> None:
        await self.runtime.oms.sign_off(order_id, _OPERATOR)
        self._timer_refresh()

    def _on_reject_clicked(self) -> None:
        order = self._selected_order()
        if order is None or order.status != "pending_signoff":
            return
        confirmed = self._confirm(
            f"Reject order {order.order_id}: {order.side.upper()} {order.quantity:g} "
            f"{order.symbol}?"
        )
        if not confirmed:
            return
        asyncio.ensure_future(self._do_reject(order.order_id))

    async def _do_reject(self, order_id: str) -> None:
        await self.runtime.oms.reject_order(order_id, _OPERATOR, "rejected via blotter")
        self._timer_refresh()
