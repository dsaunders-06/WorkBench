"""Risk Console (spec §K): live VaR/ES/exposure/limit-utilisation tiles, a
simple correlation table, and the kill-switch - always visible, one click
to trip or reset (spec §H/§18.2). It overrides every strategy and the AI
layer and cannot be hidden.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.domain import market_calendar as mc
from qat.domain.display_dates import format_display_date, format_session_time
from qat.domain.evaluation.refusals import load_risk_decisions, summarise_refusals
from qat.domain.events import MarketDataEvent
from qat.presentation import theme
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel
from qat.presentation.widgets import KpiTile

_REFRESH_INTERVAL_MS = 2000
_CORRELATION_WINDOW = 60
_MIN_POINTS_FOR_CORRELATION = 5

# The kill-switch state, through the design system (M75). Colours unchanged to
# the byte; the padding moves 10px to the rhythm's 8px.
_TRIPPED_STYLE = theme.banner(theme.DANGER)
_ACTIVE_STYLE = theme.banner(theme.SUCCESS)

_OPERATOR = "operator (risk console)"

# Suffixes distinguishing the two quarantine stores in the "Clear a
# quarantine..." picker (I4, final review). A symbol can be quarantined in
# BOTH at once, and each clears independently through a different method -
# see `_on_clear_clicked` - so a bare symbol list could not say which store
# an operator meant to clear.
_POSITION_SUFFIX = "  (position anomaly)"
_RESTING_SUFFIX = "  (resting-order quarantine)"

logger = logging.getLogger(__name__)


def corporate_action_summary(monitor: object | None, mode: str) -> str:
    """What the Risk Console says about corporate actions.

    Pure and module-level so the WORDING can be tested without a Qt widget -
    the defects this project keeps finding are in sentences that explain, and
    a sentence nothing can assert against is where they hide.

    THE ORDER OF THESE BRANCHES IS THE POINT. "Could not find out" must come
    before "nothing pending", because saying the second while the first is true
    is a checkably false statement - and it was one: a 135-day query range broke
    every announcement query while this label went on reporting none pending.

    Three states, not two (Task 5, option 1):

    * **UNAVAILABLE** - the broker cannot answer at all. Permanent, so it is
      stated calmly and does not send anyone to a log that will say the same
      thing for ever. IBKR publishes no structured corporate-action feed.
    * **COULD NOT BE READ** - the broker CAN answer and this pass failed.
      Transient, so it names the symbols and points at the log.
    * **none pending** - allowed only when the detector can actually see.

    The mode is not decoration. In shadow nothing has been placed, and an
    operator reading "adjusted to 36.34" while believing the broker holds that
    order would be misled in the direction that costs money - the same failure
    as reading M60's "declared" as "fixed".
    """
    if monitor is None:
        return "Corporate actions: no monitor is running, so nothing is being watched."

    supported = getattr(monitor, "detection_supported", None)
    if callable(supported) and not supported():
        return (
            "Corporate actions: detection UNAVAILABLE on this broker - it publishes no "
            "corporate-action feed, so a split cannot be seen before its ex-date. Entries "
            "are not gated on pending actions and stops are not adjusted through one. This "
            "is a property of the broker, not a fault."
        )

    blind = monitor.unreadable_symbols()  # type: ignore[attr-defined]
    if blind:
        return (
            f"Corporate actions: COULD NOT BE READ for {', '.join(blind)} - the detector "
            f"is blind on these, which is not the same as nothing being pending. See the "
            f"log for why the query failed."
        )

    pending = monitor.pending_actions()  # type: ignore[attr-defined]
    if not pending:
        return "Corporate actions: none pending on held positions."

    rows = []
    for action in pending:
        adjusted = (
            f"{action.adjusted_stop:.2f}" if action.adjusted_stop is not None else "not computed"
        )
        state = action.refusal or ("placed" if action.state == "applied" else "NOT placed (shadow)")
        rows.append(f"{action.describe()}: stop {action.current_stop:.2f} -> {adjusted}, {state}")
    return f"CORPORATE ACTIONS PENDING (mode: {mode}) - " + "; ".join(rows)


class RiskConsoleScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._price_history: dict[str, list[float]] = {symbol: [] for symbol in runtime.watchlist}
        self.level = UiLevel.from_settings(runtime.settings)

        layout = QVBoxLayout(self)

        self.kill_switch_button = QPushButton()
        self.kill_switch_button.clicked.connect(self._on_kill_switch_clicked)
        layout.addWidget(self.kill_switch_button)
        self._refresh_kill_switch_button()

        kpi_row = QHBoxLayout()
        self.var95_tile = KpiTile("Portfolio VaR (95%)")
        self.var99_tile = KpiTile("Portfolio VaR (99%)")
        self.es_tile = KpiTile("Expected Shortfall (97.5%)")
        self.concentration_tile = KpiTile("Largest single name")
        for tile in (self.var95_tile, self.var99_tile, self.es_tile, self.concentration_tile):
            kpi_row.addWidget(tile)
        layout.addLayout(kpi_row)

        # --- Why nothing traded, which this screen is named for ----------
        #
        # It showed VaR tiles, a matrix and the kill-switch, and nothing about
        # refusals. M64 then made the Regime Monitor point HERE when the regime
        # permits a strategy and nothing still trades, so a forward reference
        # existed to a screen that could not answer it.
        #
        # The numbers come from summarise_refusals - the same function the
        # daily report uses - so the screen and the report cannot describe the
        # same night differently.
        # The heading states the period. M56b's defect was not the arithmetic,
        # it was a total under a heading that implied a narrower window.
        layout.addWidget(QLabel("Why orders did not happen - today"))
        self.refusal_headline = QLabel("No sizing decisions recorded.")
        self.refusal_headline.setWordWrap(True)
        self.refusal_headline.setStyleSheet(theme.text(size=theme.BODY, bold=True))
        layout.addWidget(self.refusal_headline)

        self.refusal_detail = QPlainTextEdit()
        self.refusal_detail.setReadOnly(True)
        self.refusal_detail.setMaximumHeight(110)
        self.refusal_detail.setVisible(self.level.shows_advanced())
        layout.addWidget(self.refusal_detail)

        # Item 38. This panel renders the RISK ENGINE's verdicts, and
        # `RiskDecision` carries no order id, so it cannot know whether an
        # order later reached the broker. On 25 August three orders parked in
        # `pending_signoff` on session phase rendered here as "approved" under
        # a headline reading "none refused", on the screen an operator checks
        # to answer "did my orders go out". It answered yes for three that had
        # not.
        #
        # `approvals.py` already documents this exact collision elsewhere -
        # "the trade ledger cannot tell them apart. Both read `approved`" - so
        # the caption says what the verdict is NOT, rather than trusting a
        # hyphenated label to carry it alone.
        self.audit_caption = QLabel(
            "Risk engine sizing verdicts - NOT whether the order reached the "
            "broker. An order can be risk-approved and then held by the "
            "autonomy gate; check the Order Blotter for what actually happened."
        )
        self.audit_caption.setWordWrap(True)
        self.audit_caption.setVisible(self.level.prefers_density())
        layout.addWidget(self.audit_caption)

        self.audit_log = QPlainTextEdit()
        self.audit_log.setReadOnly(True)
        self.audit_log.setMaximumHeight(130)
        self.audit_log.setVisible(self.level.prefers_density())
        layout.addWidget(self.audit_log)

        # Pending corporate actions, directly under the refusals block because a
        # pending split is one of the answers to the question that block asks
        # (M39, R1). It was below the quarantine controls, which put the most
        # time-critical fact on this screen underneath two buttons and a text
        # area - found by rendering the deployed build.
        self.corporate_action_label = QLabel("")
        self.corporate_action_label.setWordWrap(True)
        self.corporate_action_label.setStyleSheet(theme.text(size=theme.BODY, bold=True))
        layout.addWidget(self.corporate_action_label)
        self._refresh_corporate_actions()

        layout.addWidget(QLabel("Quarantined positions & resting-order flags"))
        self.anomaly_caption = QLabel(
            "A declared anomaly explains a difference so the session is not halted. It does "
            "NOT correct the quantity, the entry record, the resting protection or the "
            "ledger - that is still manual. A RESTING ORDER quarantine below is a different "
            "thing: it flags orders the book cannot justify and does NOT suppress a "
            "reconciliation halt (M141, item 23)."
        )
        self.anomaly_caption.setWordWrap(True)
        layout.addWidget(self.anomaly_caption)
        self.anomaly_list = QPlainTextEdit()
        self.anomaly_list.setReadOnly(True)
        # Bounded like every other text area on this screen. It was the only one
        # without a cap, so with nothing quarantined - the normal case - it was
        # the widget the layout stretched, and "No quarantined positions." sat in
        # the middle of an empty box spanning most of the screen. That reads as a
        # rendering fault rather than as good news, which is the M74 complaint.
        self.anomaly_list.setMaximumHeight(110)
        layout.addWidget(self.anomaly_list)

        anomaly_row = QHBoxLayout()
        self.declare_anomaly_button = QPushButton("Declare a difference explained...")
        self.declare_anomaly_button.clicked.connect(self._on_declare_clicked)
        # Item 36. ReconciliationMonitor.poll's docstring promised this
        # control - "Public so a test or the Risk Console can force a
        # check" - and it did not exist. On 25 August that sentence was
        # read as fact, the operator was sent here to force a check while
        # diagnosing a wedged poll, and the kill switch was tripped instead.
        self.force_check_button = QPushButton("Force a reconciliation check")
        self.force_check_button.clicked.connect(self._on_force_check_clicked)
        anomaly_row.addWidget(self.force_check_button)

        self.clear_anomaly_button = QPushButton("Clear a quarantine...")
        self.clear_anomaly_button.clicked.connect(self._on_clear_clicked)
        anomaly_row.addWidget(self.declare_anomaly_button)
        anomaly_row.addWidget(self.clear_anomaly_button)
        layout.addLayout(anomaly_row)
        self._refresh_anomalies()

        # Which pairs actually BIND, from the rail rather than from this
        # screen's own arithmetic. The matrix below correlates ~60 intraday
        # tick samples - about the last hour - while the cluster cap correlates
        # 60 daily bars, about three months. They are different quantities, and
        # only one of them refuses trades.
        self.binding_pairs_label = QLabel("")
        self.binding_pairs_label.setWordWrap(True)
        self.binding_pairs_label.setStyleSheet(theme.text(size=theme.BODY, bold=True))
        layout.addWidget(self.binding_pairs_label)

        self.correlation_caption = QLabel(
            "The table below is a short intraday window, shown for shape. The line above "
            "is the measure the cluster cap actually enforces."
        )
        self.correlation_caption.setWordWrap(True)
        self.correlation_caption.setStyleSheet(theme.text(theme.MUTED, size=theme.CAPTION))
        self.correlation_caption.setVisible(self.level.shows_advanced())
        layout.addWidget(self.correlation_caption)

        self.correlation_header = QLabel("Correlation (trailing window)")
        self.correlation_header.setVisible(self.level.shows_advanced())
        layout.addWidget(self.correlation_header)
        self.correlation_table = QTableWidget(len(runtime.watchlist), len(runtime.watchlist))
        self.correlation_table.setHorizontalHeaderLabels(list(runtime.watchlist))
        self.correlation_table.setVerticalHeaderLabels(list(runtime.watchlist))
        self.correlation_table.setVisible(self.level.shows_advanced())
        layout.addWidget(self.correlation_table)
        self.refresh_binding_pairs()

        self.runtime.bus.subscribe(MarketDataEvent, self._on_market_data)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start(_REFRESH_INTERVAL_MS)

    def _on_timer_tick(self) -> None:
        # Item 57. The label is DERIVED here rather than remembered: it was
        # previously only ever repainted at construction and at the tail of
        # this screen's own click handler, so a trip via any other route -
        # reconciliation, the equity rails, the startup restore - left it
        # reading "inactive - click to halt trading" while the switch was
        # actually tripped. The click handler resets on that state with no
        # confirmation (de-risking stays one click, deliberately), so a stale
        # label invited the opposite of an operator's intent during an
        # incident. A listener on the switch would have the same gap this
        # screen already has on the outbound side (see _on_kill_switch_clicked's
        # docstring); the timer already runs every 2s regardless, so deriving
        # from it here cannot go stale the same way.
        self._refresh_kill_switch_button()
        self._refresh_risk_tiles()
        self._refresh_correlation_table()
        self._refresh_anomalies()
        self.refresh_refusals()
        self.refresh_binding_pairs()

    def _refresh_corporate_actions(self) -> None:
        monitor = getattr(self.runtime, "corporate_action_monitor", None)
        self.corporate_action_label.setText(
            corporate_action_summary(monitor, self.runtime.settings.corporate_action_mode)
        )

    def refresh_binding_pairs(self) -> None:
        """Pairs at or above the cluster threshold, asked of the governor.

        Never recomputed here. The screen and the rail must not derive "are
        these correlated" separately - they would drift, and an operator
        reading one while the other refused the trade could not tell which was
        binding.

        Shown at EVERY level: it is a constraint on what may be traded, and the
        matrix below is the detail rather than the fact.
        """
        bridge = self.runtime.signal_bridge
        if bridge is None:
            self.binding_pairs_label.setText("Correlation clusters: no strategy bridge running.")
            return
        symbols = sorted(self.runtime.opened_position_symbols())
        if not symbols:
            self.binding_pairs_label.setText("Correlation clusters: nothing held.")
            return

        returns = bridge.return_series(symbols)
        threshold = self.runtime.settings.correlation_cluster_threshold
        pairs = self.runtime.risk_engine.governor.binding_pairs(returns)
        if not pairs:
            self.binding_pairs_label.setText(
                f"Correlation clusters: none of the {len(symbols)} held position(s) "
                f"pair at or above {threshold:.2f}."
            )
            return
        self.binding_pairs_label.setText(
            "Correlation clusters AT OR ABOVE "
            f"{threshold:.2f}: "
            + ", ".join(f"{left}/{right} {corr:.2f}" for left, right, corr in pairs)
        )

    def refresh_refusals(self) -> None:
        """Why orders did not happen, in the report's own words.

        `summarise_refusals` is ASKED, never reproduced. A screen that counted
        the rows itself would be a second derivation of the same night, and the
        two would eventually disagree with no way for the operator to tell which
        was lying - the rule the adopted-positions panel and the Regime Monitor
        already follow.

        Public because it must be callable without waiting on the 2s timer.
        """
        # BOUNDED TO TODAY, which is the whole of M56b's lesson: that defect
        # was lifetime totals sitting under a daily heading, and the 6 August
        # report claimed a kill-switch that had fired on the 4th. Unbounded,
        # this panel reads "2,629 candidates considered" while meaning "since
        # the file was created", and an operator would take it for tonight.
        # M120. The exchange's trading date. A UTC date would relabel the panel
        # an hour into an AEDT session and show the operator an empty "today"
        # while the session it belongs to was still running.
        today = mc.trading_date(self.runtime.settings.market).isoformat()
        rows = load_risk_decisions(
            self.runtime.settings.data_dir, since=today, market=self.runtime.settings.market
        )
        summary = summarise_refusals(rows)
        self.refusal_headline.setText(summary.headline())

        # Families rather than raw reason strings: capacity against candidate is
        # the split that decides what to do. Capacity says change the limits;
        # candidate says look at the strategy.
        lines = [
            f"{family.value}: {count}  -  {family.means}"
            for family, count in sorted(
                summary.by_family.items(), key=lambda kv: (-kv[1], kv[0].value)
            )
        ]
        self.refusal_detail.setPlainText(
            "\n".join(lines) if lines else "No refusals in the record."
        )

        entries = self.runtime.risk_engine.audit_log.entries()
        self.audit_log.setPlainText(
            "\n".join(
                f"{entry.symbol}  "
                f"{'risk-approved' if entry.approved else 'risk-refused'}  "
                f"{entry.reason}"
                for entry in entries[-40:]
            )
            or "No audit entries yet."
        )

    def _refresh_anomalies(self) -> None:
        """Renders both quarantine stores, clearly labelled apart (I4, final
        review).

        `PositionAnomalyStore.explains()` can suppress a reconciliation halt;
        `RestingOrderAnomalyStore` deliberately has no such method and cannot
        (see its own docstring). Blurring the two into one undifferentiated
        list would make that distinction invisible on the one screen an
        operator actually reads it from, so every row names its own kind.

        Before this fix the panel read only `oms.anomalies` - a resting-order
        quarantine had no screen, no button and no way to tell an operator it
        existed, so a symbol that got cancelled clean stayed quarantined
        forever with nothing visible anywhere.
        """
        positions = self.runtime.oms.anomalies.active()
        resting = self.runtime.oms.resting_order_anomalies.active()
        if not positions and not resting:
            self.anomaly_list.setPlainText("No quarantined positions.")
            return
        lines = [
            f"POSITION  {a.symbol}  tracked={a.tracked_quantity:g} broker={a.broker_quantity:g}  "
            f"{a.reason}  (declared by {a.declared_by}, "
            f"{format_display_date(a.declared_at)} "
            f"{format_session_time(a.declared_at, self.runtime.settings.market)})"
            for a in positions
        ] + [
            f"RESTING ORDER  {a.symbol}  {a.excess:g} share(s) unjustified  "
            f"{a.reason}  (declared by {a.declared_by}, "
            f"{format_display_date(a.declared_at)} "
            f"{format_session_time(a.declared_at, self.runtime.settings.market)})"
            for a in resting
        ]
        self.anomaly_list.setPlainText("\n".join(lines))

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

    def _clear_resting_anomaly(self, symbol: str) -> None:
        """Clears a resting-order quarantine (I4, final review).

        `RestingOrderAnomalyStore.clear()` had no production caller at all
        before this: cancelling could resolve every leg cleanly and the
        symbol would stay quarantined forever, across every restart, with no
        screen and no button pointing at the file that held it. Kept as its
        own method rather than folded into `_clear_anomaly` above, because a
        symbol can be quarantined in BOTH stores at once and each has to be
        clearable independently - clearing one must never look like it
        cleared the other.
        """
        self.runtime.oms.resting_order_anomalies.clear(symbol, operator=_OPERATOR)
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
        """Offers both stores (I4, final review).

        Suffixed rather than a bare symbol list, because a symbol can carry
        BOTH kinds of quarantine at once and they clear independently through
        different methods below - a plain symbol picker could not say which
        one the operator meant, and picking wrong would leave the other kind
        silently still in force.
        """
        options = [f"{a.symbol}{_POSITION_SUFFIX}" for a in self.runtime.oms.anomalies.active()]
        options += [
            f"{a.symbol}{_RESTING_SUFFIX}"
            for a in self.runtime.oms.resting_order_anomalies.active()
        ]
        if not options:
            return
        choice, ok = QInputDialog.getItem(self, "Clear quarantine", "Symbol:", options, 0, False)
        if not ok or not choice:
            return
        if choice.endswith(_RESTING_SUFFIX):
            self._clear_resting_anomaly(choice[: -len(_RESTING_SUFFIX)])
        else:
            self._clear_anomaly(choice[: -len(_POSITION_SUFFIX)])

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

    def _refresh_risk_tiles(self) -> None:
        """Live book risk as the headline; the last decision's figure as a
        caption, and ONLY when there is one.

        ⚠️ This used to read `entries[-1].inputs["portfolio_check"]` and return
        early when it was absent - which is every startup, because the audit log
        is in-memory, and every 10-of-10 day, because the governor refuses one
        rail before that dict is written. The tiles sat at "-" from 31 August.
        """
        # ⚠️ NOT `getattr(self.runtime, "book_risk_monitor", None)`. That returns
        # `Any`, which poisons every attribute read below it: with the getattr
        # form, `live.var_99` type-checked clean even when the field name was
        # misspelled, so three of these four tiles could have rendered "-"
        # forever with mypy reporting success across 173 files. `Runtime` has
        # declared this field since it was wired, so read it directly and let
        # mypy check the names against `BookRisk`.
        monitor = self.runtime.book_risk_monitor
        live = monitor.fresh() if monitor is not None else None

        entries = self.runtime.risk_engine.audit_log.entries()
        decision = entries[-1].inputs.get("portfolio_check") if entries else None

        es_limit = self.runtime.settings.portfolio_es_limit_pct

        def _pct(value: float | None) -> str:
            return "-" if value is None else f"{value:.2%}"

        def _caption(name: str, *, prefix: str = "") -> str | None:
            if not decision:
                return None
            value = decision.get(name)
            return None if value is None else f"{prefix}at last decision: {value:.2%}"

        self.var95_tile.set_value(_pct(live.var_95 if live is not None else None))
        self.var95_tile.set_caption(_caption("var_95"))

        self.var99_tile.set_value(_pct(live.var_99 if live is not None else None))
        self.var99_tile.set_caption(_caption("var_99"))

        es_value = live.es_975 if live is not None else None
        self.es_tile.set_value(
            "-" if es_value is None else f"{es_value:.2%} / {es_limit:.0%}",
            color=(
                None
                if es_value is None
                else (theme.DANGER if es_value >= es_limit else theme.SUCCESS)
            ),
        )
        self.es_tile.set_caption(_caption("es_975"))

        # `single_name_pct` here is the CANDIDATE's, from the last decision -
        # the live figure above is the largest already in the book. The two
        # are different measurements (book_risk.py's own docstring warns
        # against letting a coincidence between them read as agreement), so
        # the qualifier is built explicitly rather than by editing the base
        # string after the fact: a later change to the base wording would
        # carry through here too, instead of a `.replace()` silently failing
        # to match and dropping the qualifier back to the unqualified text.
        self.concentration_tile.set_value(_pct(live.single_name_pct if live is not None else None))
        self.concentration_tile.set_caption(_caption("single_name_pct", prefix="candidate "))

    def _refresh_kill_switch_button(self) -> None:
        if self.runtime.kill_switch.tripped:
            self.kill_switch_button.setText(
                f"KILL-SWITCH TRIPPED ({self.runtime.kill_switch.reason}) - click to reset"
            )
            self.kill_switch_button.setStyleSheet(_TRIPPED_STYLE)
        else:
            self.kill_switch_button.setText("KILL-SWITCH: inactive - click to halt trading")
            self.kill_switch_button.setStyleSheet(_ACTIVE_STYLE)

    def _schedule(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Run an awaitable from a Qt slot, which cannot await. Separated
        so a test can drive the handler without a running qasync loop."""
        asyncio.ensure_future(coro)

    def _on_force_check_clicked(self) -> None:
        self._schedule(self.runtime.reconciliation_monitor.poll())

    def _confirm_trip(self) -> bool:
        """Ask before HALTING. Separated so a test can answer it.

        On trip only. Clearing a halt stays one click: a confirmation in
        front of de-risking is a worse failure than the accident this
        prevents."""
        answer = QMessageBox.question(
            self,
            "Halt trading?",
            "Halt ALL new order flow, including exits and protective-stop "
            "re-arming, until reset by hand? Resting orders already at the "
            "broker are NOT cancelled and can still fill.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_kill_switch_clicked(self) -> None:
        """Toggle the switch AND announce it.

        This screen used to mutate the shared KillSwitch and repaint only its
        own button, so halting from here left the main window's banner reading
        AUTO-TRADE ACTIVE and resetting left it reading HALTED. The state was
        right and every other view of it was wrong.
        """
        operator = "operator (risk console)"
        if self.runtime.kill_switch.tripped:
            # No confirmation: de-risking stays one click, deliberately.
            self.runtime.kill_switch.reset(operator)
        else:
            # Item 36. A TOGGLE bound to Qt's clicked, which fires on Space
            # or Enter when focused - and it is the first widget on this
            # screen. Halting a live account was one stray keystroke away
            # from an unrelated instruction.
            if not self._confirm_trip():
                return
            self.runtime.kill_switch.trigger_manual(operator)
        # Every other view of the switch now updates through its listeners, so
        # this screen no longer has to remember to announce what it did.
        self._refresh_kill_switch_button()
