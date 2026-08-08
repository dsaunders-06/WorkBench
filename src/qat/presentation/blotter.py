"""Order Blotter (spec §I/§K): every order OMS knows about, with the
mandatory human sign-off gate at the UI layer too - selecting pending
orders and clicking Sign Off always opens a confirmation dialog first;
oms.sign_off() is only ever reached from inside the confirmed branch.
Paper/live colour coding matches the main window banner so the mode is
unmistakable on this screen as well (spec §13.3).

Bulk sign-off (M11) selects many orders at once, but the confirmation
dialog still itemises every order it is about to transmit - approving a
batch stays an informed decision rather than a single blind click. The
underlying per-order sign_off() call, and therefore the safety invariant,
is unchanged: each order is still individually transmitted only after that
explicit confirmation.

_confirm()/_show_error() are kept as their own methods specifically so
tests can monkeypatch them (return True/False, capture messages) and assert
sign_off is/isn't reached, without driving real Qt dialog widgets.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from time import monotonic

from PySide6.QtCore import QItemSelectionModel, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.data.broker.adapter import Order
from qat.domain.evaluation import refusals
from qat.presentation import theme
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_MS = 2000
_OPERATOR = "operator (blotter)"
# How often the decision journal may be re-read for reasons we do not have
# (M77). `entries()` re-parses the whole CSV - 464KB on the live account - and
# this screen refreshes every two seconds, so an uncached lookup would parse it
# thirty times a minute. A reason never changes once written, so the cache only
# ever grows and this bounds the cost of learning about new orders.
_REASON_REREAD_SECONDS = 10.0
# Price, stop, target and strategy are shown because this is the screen a
# human signs an order off from, and until M31b it showed none of them. Judging
# whether a pending order was still safe to approve on 30 July meant
# reconstructing all four from the decision journal plus a live quote.
_COLUMNS = (
    "Order ID",
    "Symbol",
    "Side",
    "Quantity",
    "Price",
    "Stop",
    "Target",
    "Risk/share",
    "Strategy",
    "Status",
    "Reason",
    "Created At",
)

# Pending first: it is the only actionable set, and defaulting to it keeps the
# view short even when the account has a long completed-order history.
_STATUS_FILTERS: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ("Pending sign-off", ("pending_signoff",)),
    ("All", None),
    ("Filled", ("filled",)),
    ("Rejected", ("rejected",)),
    ("Cancelled", ("cancelled",)),
)
_MAX_ORDERS_LISTED_IN_DIALOG = 20
_REASON_COLUMN = _COLUMNS.index("Reason")


class BlotterScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.level = UiLevel.from_settings(runtime.settings)
        self._restoring_selection = False
        self._rendered_signature: tuple[object, ...] | None = None
        # order_id -> the reason recorded in the decision journal. See
        # _REASON_REREAD_SECONDS for why this is cached rather than looked up.
        self._reasons: dict[str, str] = {}
        self._reasons_read_at = 0.0

        layout = QVBoxLayout(self)

        # theme.banner, whose docstring names this exact use - "the mode and
        # execution banners, which state the two facts that change what every
        # other number on screen means". It held two raw hex literals that were
        # already SUCCESS and DANGER (M75, and two of its 25 sites).
        #
        # NOT level-aware, and it must never become so: M45 puts the mode
        # banner in the same class as the sign-off gate.
        banner = QLabel(f"MODE: {runtime.settings.trading_mode.upper()}")
        banner.setStyleSheet(
            theme.banner(theme.DANGER if runtime.settings.is_live else theme.SUCCESS)
        )
        layout.addWidget(banner)

        filter_row = QHBoxLayout()
        self.status_filter = QComboBox()
        for label, _statuses in _STATUS_FILTERS:
            self.status_filter.addItem(label)
        self.status_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.count_label = QLabel("")
        filter_row.addWidget(QLabel("Show:"))
        filter_row.addWidget(self.status_filter)
        filter_row.addWidget(self.count_label)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.orders_table = QTableWidget(0, len(_COLUMNS))
        self.orders_table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.orders_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # "One order at a time" at Guided (§4.2), enforced in the selection
        # model rather than by hiding the bulk button - a single-selection table
        # cannot produce a batch for the confirm dialog to itemise in the first
        # place. This makes Guided STRICTER, never looser, which is the only
        # direction the level is allowed to move on this screen.
        self.orders_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if self.level.shows_advanced()
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        # The Reason column takes the width nothing else needs. Rendering it
        # showed "Sized below on..." in a 120px stub - a column whose entire
        # purpose is to be read, truncated hardest at Guided, where the text is
        # longest and the reader least able to reconstruct it. The rest of the
        # table was leaving a third of the window empty to its right.
        self.orders_table.horizontalHeader().setSectionResizeMode(
            _REASON_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        self.orders_table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.orders_table)

        button_row = QHBoxLayout()
        self.sign_off_button = QPushButton("Sign Off Selected")
        self.sign_off_button.setEnabled(False)
        self.sign_off_button.clicked.connect(self._on_sign_off_clicked)
        self.reject_button = QPushButton("Reject Selected")
        self.reject_button.setEnabled(False)
        self.reject_button.clicked.connect(self._on_reject_clicked)
        self.select_all_button = QPushButton("Select All Pending")
        self.select_all_button.clicked.connect(self._on_select_all_pending)
        # Bulk sign-off is Standard and above. Guided approves one at a time.
        self.select_all_button.setVisible(self.level.shows_advanced())
        button_row.addWidget(self.sign_off_button)
        button_row.addWidget(self.reject_button)
        button_row.addWidget(self.select_all_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._timer_refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._timer_refresh)
        self._timer.start(_REFRESH_INTERVAL_MS)

    # --- data -------------------------------------------------------------

    def _active_statuses(self) -> tuple[str, ...] | None:
        return _STATUS_FILTERS[self.status_filter.currentIndex()][1]

    def _visible_orders(self) -> list[Order]:
        statuses = self._active_statuses()
        orders = self.runtime.oms.orders()
        if statuses is not None:
            orders = [order for order in orders if order.status in statuses]
        return orders

    def _refresh_reasons(self, orders: list[Order]) -> None:
        """Learns the journalled reason for any visible order we cannot explain.

        The reason lives in the decision journal, not on the Order - `_record`
        writes it and `Order` carries no field for it - which is why this screen
        listed rejected orders for its whole life without being able to say why
        any of them was rejected (M77).

        Read at most every `_REASON_REREAD_SECONDS`, and only when something
        visible is actually unexplained. A reason is written once and never
        changes, so a hit is permanent; the throttle bounds the cost of the
        misses, which is what stops a screen refreshing every two seconds from
        re-parsing a 464KB CSV to learn nothing.
        """
        if all(order.order_id in self._reasons for order in orders):
            return
        now = monotonic()
        if now - self._reasons_read_at < _REASON_REREAD_SECONDS and self._reasons_read_at:
            return
        self._reasons_read_at = now
        for row in self.runtime.decision_journal.entries():
            order_id = row.get("order_id")
            reason = row.get("reason")
            if order_id and reason:
                # Latest wins: an order is journalled at proposal and again at
                # its outcome, and the outcome is the one that explains it.
                self._reasons[order_id] = reason

    def _reason_cell(self, order: Order) -> tuple[str, str]:
        """The reason as (what to show, what to show on hover).

        §4.2's actual complaint, and its actual instruction: "same fact,
        layered: plain sentence first, exact figures beneath". Its own example -
        "sized at 0.4 shares, below one whole share" - is precise and opaque,
        and `refusals.rail_of` already turns exactly that string into "Sized
        below one whole share". That mapping existed from M51 and was read by
        the reporter and the Risk Console, never by the screen where an operator
        meets a refused order.

        Guided also gets what the FAMILY means, because "Position limit" still
        assumes you know the book has one. `classify().means` is a sentence
        written for precisely that.
        """
        raw = self._reasons.get(order.order_id, "")
        if not raw:
            return "-", ""
        # The refusal vocabulary applies to REFUSALS. A proposal or a sign-off
        # is journalled in words a human already wrote - "proposed by swing" -
        # and running it through `rail_of` classifies it UNCLASSIFIED, whose
        # sentence is "not recognised - see the note below". That sentence
        # belongs to the refusal REPORT, where a note does follow; here it
        # called a healthy proposal unrecognised. Found by rendering it.
        if order.status != "rejected":
            return raw, raw
        if self.level.prefers_density():
            # Professional reads the rail's own words. The label is a summary,
            # and a summary is what this level is choosing to do without.
            return raw, raw
        label = refusals.rail_of(raw)
        # `not shows_advanced()` is GUIDED exactly, and `explains()` is NOT the
        # predicate here: it is true for Standard too, so keying on it rendered
        # Guided and Standard identically - M58a, caught by this screen's own
        # collapse test, in the change that added the test.
        family = refusals.classify(raw)
        if not self.level.shows_advanced() and family is not refusals.RefusalFamily.UNCLASSIFIED:
            label = f"{label} - {family.means}"
        return label, raw

    def _on_filter_changed(self) -> None:
        self._rendered_signature = None  # force a rebuild for the new filter
        self._timer_refresh()

    def _timer_refresh(self) -> None:
        visible = self._visible_orders()
        total = len(self.runtime.oms.orders())
        capped = visible[: self.runtime.settings.blotter_max_rows]

        # Rebuilding every row on a 2s timer is what made a large blotter
        # unusable, so only redraw when the visible set actually changed.
        self._refresh_reasons(capped)

        # The reason is part of the signature: it arrives from the journal a
        # beat after the order does, and without this the row would keep the
        # dash it was first drawn with until something else changed.
        signature = tuple(
            (order.order_id, order.status, self._reasons.get(order.order_id, ""))
            for order in capped
        )
        if signature != self._rendered_signature:
            self._render(capped)
            self._rendered_signature = signature

        shown = len(capped)
        suffix = f" (showing first {shown})" if shown < len(visible) else ""
        self.count_label.setText(f"{len(visible)} of {total} orders{suffix}")
        self._on_selection_changed()

    def _render(self, orders: list[Order]) -> None:
        selected_ids = self._selected_order_ids()
        self._restoring_selection = True
        try:
            self.orders_table.setRowCount(len(orders))
            rows_to_reselect = []
            for row, order in enumerate(orders):
                price = order.reference_price
                stop = order.stop_price
                risk = (price - stop) if (price and stop and stop < price) else None
                reason_text, reason_detail = self._reason_cell(order)
                values = (
                    order.order_id,
                    order.symbol,
                    order.side,
                    f"{order.quantity:g}",
                    f"{price:,.2f}" if price else "-",
                    f"{stop:,.2f}" if stop else "-",
                    f"{order.take_profit_price:,.2f}" if order.take_profit_price else "-",
                    f"{risk:,.2f}" if risk else "-",
                    order.strategy or "-",
                    order.status,
                    reason_text,
                    f"{order.created_at:%Y-%m-%d %H:%M:%S}",
                )
                for col, value in enumerate(values):
                    item = self.orders_table.item(row, col)
                    if item is None:
                        item = QTableWidgetItem()
                        self.orders_table.setItem(row, col, item)
                    item.setText(value)
                    if col == _REASON_COLUMN:
                        # "Exact figures beneath" (§4.2). The rail's own words,
                        # with every number it mentioned, one hover away from
                        # the plain label - so the layering hides nothing.
                        item.setToolTip(reason_detail)
                if order.order_id in selected_ids:
                    rows_to_reselect.append(row)
            self._select_rows(rows_to_reselect)
        finally:
            self._restoring_selection = False

    # --- selection --------------------------------------------------------

    def _select_rows(self, rows: Iterable[int]) -> None:
        """Adds whole rows to the current selection.

        QTableWidget.selectRow() *replaces* the selection under
        ExtendedSelection, so looping over it would leave only the last row
        selected - both for "Select All Pending" and when restoring a
        multi-row selection across a timer refresh.
        """
        selection_model = self.orders_table.selectionModel()
        model = self.orders_table.model()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in rows:
            selection_model.select(model.index(row, 0), flags)

    def _selected_order_ids(self) -> set[str]:
        rows = {index.row() for index in self.orders_table.selectedIndexes()}
        ids = set()
        for row in rows:
            item = self.orders_table.item(row, 0)
            if item is not None:
                ids.add(item.text())
        return ids

    def _selected_orders(self) -> list[Order]:
        orders = []
        for order_id in self._selected_order_ids():
            try:
                orders.append(self.runtime.oms.get_order(order_id))
            except KeyError:
                continue
        return orders

    def _selected_pending_orders(self) -> list[Order]:
        return [order for order in self._selected_orders() if order.status == "pending_signoff"]

    def _on_selection_changed(self) -> None:
        if self._restoring_selection:
            return
        pending = self._selected_pending_orders()
        count = len(pending)
        suffix = f" ({count})" if count else ""
        self.sign_off_button.setText(f"Sign Off Selected{suffix}")
        self.reject_button.setText(f"Reject Selected{suffix}")
        self.sign_off_button.setEnabled(count > 0)
        self.reject_button.setEnabled(count > 0)

    def _on_select_all_pending(self) -> None:
        self._restoring_selection = True
        try:
            self.orders_table.clearSelection()
            status_col = _COLUMNS.index("Status")
            self._select_rows(
                row
                for row in range(self.orders_table.rowCount())
                if (item := self.orders_table.item(row, status_col)) is not None
                and item.text() == "pending_signoff"
            )
        finally:
            self._restoring_selection = False
        self._on_selection_changed()

    # --- dialogs (monkeypatched in tests) ---------------------------------

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Order action failed", message)

    def _confirm(self, message: str) -> bool:
        result = QMessageBox.question(
            self,
            "Confirm order action",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    @staticmethod
    def _describe(orders: list[Order]) -> str:
        listed = orders[:_MAX_ORDERS_LISTED_IN_DIALOG]
        lines = [
            f"  - {o.side.upper()} {o.quantity:g} {o.symbol} ({o.order_id[:8]})" for o in listed
        ]
        remaining = len(orders) - len(listed)
        if remaining > 0:
            lines.append(f"  ...and {remaining} more")
        return "\n".join(lines)

    # --- actions ----------------------------------------------------------

    def _on_sign_off_clicked(self) -> None:
        orders = self._selected_pending_orders()
        if not orders:
            return
        confirmed = self._confirm(
            f"Sign off {len(orders)} order(s)?\n\n{self._describe(orders)}\n\n"
            "This transmits them to the broker."
        )
        if not confirmed:
            return
        asyncio.ensure_future(self._do_sign_off([o.order_id for o in orders]))

    async def _do_sign_off(self, order_ids: list[str]) -> None:
        failures: list[str] = []
        for order_id in order_ids:
            try:
                await self.runtime.oms.sign_off(order_id, _OPERATOR)
            except Exception as exc:  # noqa: BLE001 - collected and surfaced below
                # A silently failed sign-off is dangerous: the operator would be
                # left unsure whether the order reached the broker or not.
                logger.exception("Sign-off failed for order %s", order_id)
                failures.append(f"{order_id}: {exc}")
        if failures:
            self._show_error(
                "Sign-off failed for {} of {} order(s):\n\n{}".format(
                    len(failures), len(order_ids), "\n".join(failures)
                )
            )
        self._timer_refresh()

    def _on_reject_clicked(self) -> None:
        orders = self._selected_pending_orders()
        if not orders:
            return
        confirmed = self._confirm(f"Reject {len(orders)} order(s)?\n\n{self._describe(orders)}")
        if not confirmed:
            return
        asyncio.ensure_future(self._do_reject([o.order_id for o in orders]))

    async def _do_reject(self, order_ids: list[str]) -> None:
        failures: list[str] = []
        for order_id in order_ids:
            try:
                await self.runtime.oms.reject_order(order_id, _OPERATOR, "rejected via blotter")
            except Exception as exc:  # noqa: BLE001 - collected and surfaced below
                logger.exception("Reject failed for order %s", order_id)
                failures.append(f"{order_id}: {exc}")
        if failures:
            self._show_error(
                "Reject failed for {} of {} order(s):\n\n{}".format(
                    len(failures), len(order_ids), "\n".join(failures)
                )
            )
        self._timer_refresh()
