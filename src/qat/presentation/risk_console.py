"""Risk Console (spec §K): live VaR/ES/exposure/limit-utilisation tiles, a
simple correlation table, and the kill-switch - always visible, one click
to trip or reset (spec §H/§18.2). It overrides every strategy and the AI
layer and cannot be hidden.
"""

from __future__ import annotations

import logging

import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.domain.events import MarketDataEvent
from qat.presentation import theme
from qat.presentation.runtime import Runtime
from qat.presentation.widgets import KpiTile

_REFRESH_INTERVAL_MS = 2000
_CORRELATION_WINDOW = 60
_MIN_POINTS_FOR_CORRELATION = 5

_TRIPPED_STYLE = "background-color: #b71c1c; color: white; font-weight: bold; padding: 10px;"
_ACTIVE_STYLE = "background-color: #1b5e20; color: white; font-weight: bold; padding: 10px;"

_OPERATOR = "operator (risk console)"

logger = logging.getLogger(__name__)


class RiskConsoleScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._price_history: dict[str, list[float]] = {symbol: [] for symbol in runtime.watchlist}

        layout = QVBoxLayout(self)

        self.kill_switch_button = QPushButton()
        self.kill_switch_button.clicked.connect(self._on_kill_switch_clicked)
        layout.addWidget(self.kill_switch_button)
        self._refresh_kill_switch_button()

        kpi_row = QHBoxLayout()
        self.var95_tile = KpiTile("Portfolio VaR (95%)")
        self.var99_tile = KpiTile("Portfolio VaR (99%)")
        self.es_tile = KpiTile("Expected Shortfall (97.5%)")
        self.concentration_tile = KpiTile("Single-name concentration")
        for tile in (self.var95_tile, self.var99_tile, self.es_tile, self.concentration_tile):
            kpi_row.addWidget(tile)
        layout.addLayout(kpi_row)

        layout.addWidget(QLabel("Quarantined positions"))
        self.anomaly_caption = QLabel(
            "A declared anomaly explains a difference so the session is not halted. It does "
            "NOT correct the quantity, the entry record, the resting protection or the "
            "ledger - that is still manual."
        )
        self.anomaly_caption.setWordWrap(True)
        layout.addWidget(self.anomaly_caption)
        self.anomaly_list = QPlainTextEdit()
        self.anomaly_list.setReadOnly(True)
        layout.addWidget(self.anomaly_list)

        anomaly_row = QHBoxLayout()
        self.declare_anomaly_button = QPushButton("Declare a difference explained...")
        self.declare_anomaly_button.clicked.connect(self._on_declare_clicked)
        self.clear_anomaly_button = QPushButton("Clear a quarantine...")
        self.clear_anomaly_button.clicked.connect(self._on_clear_clicked)
        anomaly_row.addWidget(self.declare_anomaly_button)
        anomaly_row.addWidget(self.clear_anomaly_button)
        layout.addLayout(anomaly_row)
        self._refresh_anomalies()

        layout.addWidget(QLabel("Correlation (trailing window)"))
        self.correlation_table = QTableWidget(len(runtime.watchlist), len(runtime.watchlist))
        self.correlation_table.setHorizontalHeaderLabels(list(runtime.watchlist))
        self.correlation_table.setVerticalHeaderLabels(list(runtime.watchlist))
        layout.addWidget(self.correlation_table)

        self.runtime.bus.subscribe(MarketDataEvent, self._on_market_data)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start(_REFRESH_INTERVAL_MS)

    def _on_timer_tick(self) -> None:
        self._refresh_from_audit_log()
        self._refresh_correlation_table()
        self._refresh_anomalies()

    def _refresh_anomalies(self) -> None:
        active = self.runtime.oms.anomalies.active()
        if not active:
            self.anomaly_list.setPlainText("No quarantined positions.")
            return
        self.anomaly_list.setPlainText(
            "\n".join(
                f"{a.symbol}  tracked={a.tracked_quantity:g} broker={a.broker_quantity:g}  "
                f"{a.reason}  (declared by {a.declared_by}, "
                f"{a.declared_at:%Y-%m-%d %H:%M} UTC)"
                for a in active
            )
        )

    def _declare_anomaly(self, symbol: str, reason: str) -> None:
        """Binds the declaration to what the broker reports right now.

        Captured here rather than typed by the operator, because the binding is
        what stops one declaration granting a symbol permanent immunity - and a
        hand-typed quantity is exactly the thing that would be typed to match
        whatever silences the alert.

        Read from the poller's CACHED snapshot: a Qt slot cannot await, and
        blocking the UI thread on a broker round-trip would be worse. With no
        snapshot the action declines rather than binding to a zero, because a
        wrong binding either silences a real divergence or fails to explain the
        actual one.
        """
        snapshot = self.runtime.account_poller.last_snapshot
        if snapshot is None:
            logger.error(
                "Cannot declare an anomaly on %s: the broker's positions have not been read "
                "yet, and binding a declaration to a guessed quantity is worse than not "
                "declaring it. Try again once the account has been polled.",
                symbol,
            )
            return
        broker_quantity = next(
            (abs(pos.quantity) for pos in snapshot.positions if pos.symbol == symbol), 0.0
        )
        self.runtime.oms.anomalies.declare(
            symbol=symbol,
            reason=reason,
            declared_by=_OPERATOR,
            tracked_quantity=self.runtime.oms.filled_quantities().get(symbol, 0.0),
            broker_quantity=broker_quantity,
        )
        self._refresh_anomalies()

    def _clear_anomaly(self, symbol: str) -> None:
        self.runtime.oms.anomalies.clear(symbol, operator=_OPERATOR)
        self._refresh_anomalies()

    def _on_declare_clicked(self) -> None:
        symbol, ok = QInputDialog.getText(self, "Declare explained", "Symbol:")
        if not ok or not symbol.strip():
            return
        reason, ok = QInputDialog.getText(
            self, "Declare explained", "Why is this difference explained?"
        )
        if not ok or not reason.strip():
            # A declaration with no reason is the one that cannot be reviewed
            # later, so an empty one is refused rather than stored blank.
            return
        self._declare_anomaly(symbol.strip().upper(), reason.strip())

    def _on_clear_clicked(self) -> None:
        active = [a.symbol for a in self.runtime.oms.anomalies.active()]
        if not active:
            return
        symbol, ok = QInputDialog.getItem(self, "Clear quarantine", "Symbol:", active, 0, False)
        if not ok or not symbol:
            return
        self._clear_anomaly(symbol)

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        """Only buffers the price - recomputing correlations here would run
        an O(n^2) pandas pass on every tick of every symbol (i.e. O(n^3) work
        per second), which saturated the event loop at larger watchlist sizes.
        The 2s timer does the actual refresh instead."""
        history = self._price_history.get(event.symbol)
        if history is None:
            return
        history.append(event.price)
        if len(history) > _CORRELATION_WINDOW:
            del history[: len(history) - _CORRELATION_WINDOW]

    def _refresh_correlation_table(self) -> None:
        symbols = [
            symbol
            for symbol in self.runtime.watchlist
            if len(self._price_history[symbol]) > _MIN_POINTS_FOR_CORRELATION
        ]
        if len(symbols) < 2:
            return

        # Truncate to the shortest history so rows line up positionally, then
        # let pandas compute the whole matrix in one vectorised pass rather
        # than doing an individual concat+corr per symbol pair.
        length = min(len(self._price_history[symbol]) for symbol in symbols)
        frame = pd.DataFrame({symbol: self._price_history[symbol][-length:] for symbol in symbols})
        # .to_numpy() once, then index positionally: pandas' .at[] scalar
        # lookup costs ~40us, which dominated everything else at n^2 cells.
        matrix = frame.pct_change().corr().to_numpy()

        index_by_symbol = {symbol: i for i, symbol in enumerate(self.runtime.watchlist)}
        for matrix_row, row_symbol in enumerate(symbols):
            row = index_by_symbol[row_symbol]
            for matrix_col, col_symbol in enumerate(symbols):
                corr = matrix[matrix_row, matrix_col]
                if pd.isna(corr):
                    continue
                # Reuse the existing cell widget: allocating a fresh
                # QTableWidgetItem per cell on every refresh dominated the
                # cost on large watchlists (n^2 allocations each tick).
                col = index_by_symbol[col_symbol]
                item = self.correlation_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.correlation_table.setItem(row, col, item)
                item.setText(f"{corr:.2f}")
                intensity = int(abs(corr) * 200)
                item.setBackground(
                    QColor(255, 255 - intensity, 255 - intensity)
                    if corr >= 0
                    else QColor(255 - intensity, 255 - intensity, 255)
                )

    def _refresh_from_audit_log(self) -> None:
        entries = self.runtime.risk_engine.audit_log.entries()
        if not entries:
            return
        portfolio_check = entries[-1].inputs.get("portfolio_check")
        if not portfolio_check:
            return
        self.var95_tile.set_value(f"{portfolio_check['var_95']:.2%}")
        self.var99_tile.set_value(f"{portfolio_check['var_99']:.2%}")
        es_limit = self.runtime.settings.portfolio_es_limit_pct
        es_value = portfolio_check["es_975"]
        self.es_tile.set_value(
            f"{es_value:.2%} / {es_limit:.0%}",
            color=theme.DANGER if es_value >= es_limit else theme.SUCCESS,
        )
        self.concentration_tile.set_value(f"{portfolio_check['single_name_pct']:.2%}")

    def _refresh_kill_switch_button(self) -> None:
        if self.runtime.kill_switch.tripped:
            self.kill_switch_button.setText(
                f"KILL-SWITCH TRIPPED ({self.runtime.kill_switch.reason}) - click to reset"
            )
            self.kill_switch_button.setStyleSheet(_TRIPPED_STYLE)
        else:
            self.kill_switch_button.setText("KILL-SWITCH: inactive - click to halt trading")
            self.kill_switch_button.setStyleSheet(_ACTIVE_STYLE)

    def _on_kill_switch_clicked(self) -> None:
        """Toggle the switch AND announce it.

        This screen used to mutate the shared KillSwitch and repaint only its
        own button, so halting from here left the main window's banner reading
        AUTO-TRADE ACTIVE and resetting left it reading HALTED. The state was
        right and every other view of it was wrong.
        """
        operator = "operator (risk console)"
        if self.runtime.kill_switch.tripped:
            self.runtime.kill_switch.reset(operator)
        else:
            self.runtime.kill_switch.trigger_manual(operator)
        # Every other view of the switch now updates through its listeners, so
        # this screen no longer has to remember to announce what it did.
        self._refresh_kill_switch_button()
