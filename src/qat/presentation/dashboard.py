"""Dashboard (spec §K): KPI tiles, equity curve, positions table, and an
AI regime-note panel the human acknowledges - the AI proposes, the human
disposes; nothing here auto-applies anything.

⚠️ The control used to be labelled "Review & Apply" and its handler was one
line: `setText("Reviewed ✓")`. Being inert toward TRADING is deliberate and
right - spec §K is "Review & Apply, never auto-apply" - but the word *Apply*
on a button that applies nothing is the same family as M73's framing that
lived only in a docstring and M105's connection test that returned a tick
whatever happened (item 18). It now says what it does, and the
acknowledgement is written to the log with the regime label it was made
against, so it can serve as evidence a human saw a regime change before a
trade. The button state still resets on the next `RegimeEvent`; the log line
does not.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from qat.domain.display_dates import format_session_time
from qat.domain.events import RegimeEvent
from qat.domain.oms.adopted import assess_adopted_positions
from qat.domain.oms.position_closer import CloseOutcome, PositionCloser
from qat.domain.oms.position_view import PositionView, build_position_views
from qat.presentation import theme
from qat.presentation.adopted_panel import AdoptedPositionsPanel
from qat.presentation.balances_panel import BalancesPanel
from qat.presentation.runtime import Runtime
from qat.presentation.session_panel import SessionPanel
from qat.presentation.ui_level import UiLevel
from qat.presentation.widgets import KpiTile

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_MS = 2000
_MAX_EQUITY_POINTS = 500
_MIN_POINTS_FOR_SHARPE = 10

# --- Positions table (positions panel brief) ----------------------------------
#
# Nine columns replacing the old Symbol/Quantity/Avg Price. `None` renders as
# an em dash everywhere on this table, never as a number or a blank cell that
# could be misread as zero (M81, M82: a display that states something false
# is the defect class this project has been bitten by most).
_EM_DASH = "—"
# Item 18. Not "Review & Apply": this applies nothing, and saying so is the
# whole fix. `&&` is Qt's escape for a literal ampersand, which is why the old
# label was doubled - a detail worth keeping in mind before adding one back.
_ACKNOWLEDGE_LABEL = "Acknowledge note"
# Same convention as blotter.py's and risk_console.py's own `_OPERATOR`: a
# per-screen identity string, since there is no single app-wide operator
# identity to import instead (config.py defines none). Manual position close
# (2026-09-01 spec, Task 7).
_OPERATOR = "operator (dashboard)"
_POSITIONS_COLUMNS = (
    "Symbol",
    "Qty",
    # The two money columns say so in the header. Every other numeric column
    # here is a percentage or a multiple, so an unlabelled price is the one
    # figure a reader has to infer the unit of.
    "Entry ($)",
    "Last ($)",
    "P&L",
    "To exit",
    "To stop",
    "Risk",
    "Status",
)
_POSITIONS_PNL_COLUMN = 4
_POSITIONS_STATUS_COLUMN = 8
# Every column except Symbol (text) and Status (a joined sentence) carries a
# number, and reads better right-aligned against its neighbours.
_POSITIONS_NUMERIC_COLUMNS = frozenset(range(1, _POSITIONS_STATUS_COLUMN))

# Cells already carry tooltips (M87); the headers did not, and "To exit" and
# "To stop" are the two most likely to be misread as each other or elided
# first (positions panel brief review, M7).
_POSITIONS_COLUMN_TOOLTIPS = {
    "Symbol": "The traded symbol",
    "Qty": "Quantity currently held",
    "Entry ($)": "This app's own entry price - not the broker's average cost",
    "Last ($)": "The broker's last reported mark; em dash when it reports none",
    "P&L": "Unrealised P&L, as a percentage and in R (risk multiples) when the lot has a stop",
    "To exit": "Distance from the strategy's signal-exit condition, as a fraction of its slow EMA",
    "To stop": "Distance from the last price down to the resting stop",
    "Risk": "This position's share of the aggregate risk-at-stop budget",
    "Status": "What is true about a sell right now - not all of this is a reason one won't fire",
}


def _format_price(value: float | None) -> str:
    return f"{value:,.2f}" if value is not None else _EM_DASH


def _format_pct(value: float | None, decimals: int = 2) -> str:
    return f"{value:.{decimals}%}" if value is not None else _EM_DASH


def _format_pnl(pnl_pct: float | None, pnl_r: float | None) -> str:
    """ "-6.2% (-0.35R)", or just the percentage when there is no R (no stop on
    the lot to measure one against).

    **The R carries its own sign**, which this did not always do. It was
    written unsigned on the reasoning that the percentage already states the
    direction - sound on paper, and wrong on screen: rendered, the cell put a
    negative number beside a positive one describing the same fact, a 0.35R
    LOSS was indistinguishable from a 0.35R gain, and a row near flat
    ("0.8% (0.04R)") carried no directional cue at all. Caught by looking at
    it, which is the only thing that catches this class.

    The two signs cannot disagree, because both are computed from the same
    `last - entry`: `pnl_pct` divides by the entry price and `pnl_r` by the
    per-share risk, and neither denominator can be negative - a stop above
    the entry price yields no R at all rather than a flipped one.
    """
    if pnl_pct is None:
        return _EM_DASH
    text = f"{pnl_pct:.1%}"
    if pnl_r is None:
        return text
    return f"{text} ({pnl_r:+.2f}R)"


def corporate_action_banner_text(monitor: object | None, acting: bool) -> str | None:
    """The Dashboard's corporate-action banner, or None to hide it.

    Pure and module-level so the WORDING is testable without a Qt widget.

    **Silence is a claim here.** The banner's original comment says it: "A
    silent Dashboard while the detector cannot see is indistinguishable from a
    quiet book." That invariant holds for an UNAVAILABLE broker as much as for
    a failed query, so this still shows something.

    What changes is the KIND of message (Task 5, option 1). A broker that
    cannot answer is a STANDING CONDITION, not an alarm: it is stated, and it
    does NOT say "check the log", because there is nothing in the log to find
    and sending someone there every time is how a banner stops being read.
    """
    if monitor is None:
        return None

    supported = getattr(monitor, "detection_supported", None)
    if callable(supported) and not supported():
        return (
            "CORPORATE-ACTION DETECTION UNAVAILABLE on this broker - it publishes no "
            "corporate-action feed, so a split cannot be seen before its ex-date. Entries "
            "are not gated on pending actions and resting stops are not adjusted through "
            "one. A standing condition of this broker, not a fault to chase."
        )

    blind = monitor.unreadable_symbols()  # type: ignore[attr-defined]
    if blind:
        return (
            f"CORPORATE ACTIONS COULD NOT BE READ for {', '.join(blind)}. The split "
            f"detector is blind on these - that is not the same as nothing being pending. "
            f"Check the log."
        )

    pending = monitor.pending_actions()  # type: ignore[attr-defined]
    if not pending:
        return None

    verb = (
        "the resting stop has been adjusted"
        if acting
        else "SHADOW MODE - nothing has been adjusted"
    )
    return (
        f"CORPORATE ACTION PENDING: {'; '.join(a.describe() for a in pending)} - {verb}. "
        f"New entries in these symbols are refused until it has passed."
    )


class DashboardScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._equity_history: list[float] = []
        # Parallel to it, and trimmed with it (M56). Kept as epoch seconds
        # because that is what DateAxisItem reads.
        self._equity_times: list[float] = []

        layout = QVBoxLayout(self)

        # Above the regime header on purpose: whether the market is even open
        # is the first thing that makes the rest of this screen meaningful.
        self.session_panel = SessionPanel(
            runtime.session_controller, market=runtime.settings.market
        )
        layout.addWidget(self.session_panel)

        # Directly under the session panel, because when this fires it is the
        # answer to "the market is open and nothing is happening".
        # The expertise level, finally consumed by a screen (M58c). Read once
        # at construction like every other setting - the level takes effect at
        # the next restart, which is what Settings promises.
        self.adopted_panel = AdoptedPositionsPanel(level=UiLevel.from_settings(runtime.settings))
        layout.addWidget(self.adopted_panel)

        # Directly under the adoption banner, because a pending corporate action
        # is the same class of fact: something is true about a held position that
        # the ordinary figures on this screen do not show (M39, R1). Hidden when
        # there is nothing pending - a permanent empty notice is what M74 was
        # partly for.
        self.corporate_action_banner = QLabel("")
        self.corporate_action_banner.setWordWrap(True)
        # theme.banner, not a hand-rolled band. This wrote `color: white` as a
        # NAMED COLOUR inside an f-string, which the colour guard could not see
        # (see that test's note on PEP 701) - so the one screen still deciding a
        # colour for itself was the one the guard was blind to.
        self.corporate_action_banner.setStyleSheet(theme.banner(theme.WARNING))
        self.corporate_action_banner.setVisible(False)
        layout.addWidget(self.corporate_action_banner)

        # What the operator's acknowledgement is recorded AGAINST. `None` until
        # the first RegimeEvent, and the log line says "unknown" rather than
        # inventing a label - an acknowledgement of nothing in particular is
        # still worth recording, and pretending it named a regime is not.
        self._regime_label: str | None = None
        self.regime_header = QLabel("Regime: (waiting for data...)")
        self.regime_header.setStyleSheet(theme.text(size=theme.SUBHEAD, bold=True))
        layout.addWidget(self.regime_header)

        # The balances panel replaces the old NAV tile (M21). Showing both
        # would put two numbers for the same money on one screen and invite the
        # question of why they differ - they do not.
        self.balances_panel = BalancesPanel(
            runtime.settings.min_cash_reserve,
            level=UiLevel.from_settings(runtime.settings),
        )
        layout.addWidget(self.balances_panel)

        # The three risk figures survive as a compact line rather than tiles:
        # they matter, but they are not what this screen is now led by.
        risk_row = QHBoxLayout()
        self.var_tile = KpiTile("Portfolio VaR (95%)")
        self.sharpe_tile = KpiTile("Realised Sharpe (naive)")
        self.drawdown_tile = KpiTile("Drawdown vs limit")
        for tile in (self.var_tile, self.sharpe_tile, self.drawdown_tile):
            risk_row.addWidget(tile)
        layout.addLayout(risk_row)

        # Real clock time, not a sample count (M56).
        #
        # This plotted `_equity_history` as a bare list, so the x-axis counted
        # account polls. Two problems, and the second is the serious one: an
        # overnight close and a busy minute occupied the same width, and a poll
        # that failed silently shortened the axis rather than leaving a gap.
        # Equity at 14:03 is a fact an operator can act on; equity at "sample
        # 412" is not.
        #
        # DateAxisItem also solves the spacing question on its own - it chooses
        # ticks appropriate to the visible span, so a session shows times of day
        # and a fortnight shows dates, without this screen deciding which.
        self.equity_plot = pg.PlotWidget(
            title="Equity Curve", axisItems={"bottom": pg.DateAxisItem()}
        )
        theme.label_axes(self.equity_plot, bottom="Time", left="NAV ($)")
        self.equity_curve = self.equity_plot.plot(pen=theme.SERIES_PRIMARY)
        layout.addWidget(self.equity_plot)

        # After the curve exists, and the position is load-bearing (M56a).
        # This ran at the top of __init__ beside the two lists it fills, which
        # read naturally and was wrong: the seed also DRAWS, and the thing it
        # draws onto is created here. Against an empty data directory the draw
        # sits behind a falsy `if` and never runs, so every test passed while
        # the app could not start on any machine with recorded history.
        self._seed_equity_history()

        layout.addWidget(QLabel("Positions"))
        self.positions_table = QTableWidget(0, len(_POSITIONS_COLUMNS))
        self.positions_table.setHorizontalHeaderLabels(list(_POSITIONS_COLUMNS))
        # ⚠️ WITHOUT THIS THE CLOSE POSITION BUTTON IS DEAD TO A MOUSE.
        #
        # `_sync_close_button` counts `selectionModel().selectedRows()`, and Qt
        # defaults to `SelectItems`: a click selects one CELL, `selectedRows()`
        # returns an empty list, and the button never enables - for every real
        # operator, on every click. `blotter.py` sets this on its own table for
        # the same reason. Eleven UI tests passed over it because they all
        # select with `selectRow(0)`, which selects a whole row
        # programmatically whatever the behaviour is; only a real cell click
        # exercises this line.
        self.positions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # v1 is full-close-only, so the button acts on exactly one symbol.
        # Enforced in the selection model as well as in `_sync_close_button` -
        # a table that cannot produce a two-row selection cannot present the
        # operator with a disabled button and no visible reason why.
        self.positions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Cells get a tooltip below; the headers need one too (M87 originally
        # fixed only the cells) - "To exit" and "To stop" are the two most in
        # need of disambiguating, and the first to elide.
        for col, label in enumerate(_POSITIONS_COLUMNS):
            header_item = self.positions_table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setToolTip(_POSITIONS_COLUMN_TOOLTIPS[label])
        # Status carries the most variable-length text on the row - the notes
        # joined into a sentence - so it gets the Stretch treatment the
        # Blotter's Reason column already has (M87): every other column keeps
        # a sensible fixed width and Status takes whatever the window has
        # left, rather than every column's minimum width summing past the
        # panel and clipping the last one off the edge.
        self.positions_table.horizontalHeader().setSectionResizeMode(
            _POSITIONS_STATUS_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.positions_table)

        # Manual position close (2026-09-01 spec, Task 7). Disabled until
        # exactly one row is selected - PositionCloser is a full-close-only
        # operation (v1), so a multi-row or zero-row selection has no single
        # symbol to act on.
        #
        # ⚠️ AND disabled for the whole DURATION of a close. `close_position`
        # is async and irreversible; while it awaited the broker the button
        # sat enabled, so a second click sent a SECOND full-size market sell.
        # `_close_in_flight` is the guard, and it is consulted by the
        # selection handler too - otherwise any selection change during the
        # close would hand the button straight back.
        self._close_in_flight = False
        self.close_position_button = QPushButton("Close Position")
        self.close_position_button.setEnabled(False)
        self.close_position_button.setToolTip(
            "Cancel this position's protective legs and sell the whole holding at "
            "market. The legs are cancelled FIRST and verified gone; if the sell "
            "fails the bracket is put back."
        )
        self.close_position_button.clicked.connect(self._on_close_clicked)
        self.positions_table.itemSelectionChanged.connect(self._sync_close_button)
        layout.addWidget(self.close_position_button)

        layout.addWidget(QLabel("AI Regime Note"))
        self.ai_note_label = QLabel("(no note yet)")
        self.ai_note_label.setWordWrap(True)
        layout.addWidget(self.ai_note_label)
        self.review_button = QPushButton(_ACKNOWLEDGE_LABEL)
        self.review_button.clicked.connect(self._on_review_clicked)
        layout.addWidget(self.review_button)

        self.runtime.bus.subscribe(RegimeEvent, self._on_regime)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._schedule_refresh)
        self._timer.start(_REFRESH_INTERVAL_MS)

    def _schedule_refresh(self) -> None:
        """Qt's timer can fire whenever the widget is alive, including before
        the qasync loop is running or after it has stopped. asyncio.ensure_future
        raises in that window, and because this is a Qt slot the exception
        escapes into Qt's handler rather than anywhere useful - so the loop is
        checked for rather than assumed.

        Skipping a tick is the right response: the timer will come round again
        once the loop exists, and the tiles are refreshed from scratch each
        time, so nothing is lost by missing one.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Dashboard refresh skipped - no running event loop")
            return
        loop.create_task(self._refresh_guarded())

    async def _refresh_guarded(self) -> None:
        """Timer-driven, so an exception here would otherwise vanish into an
        un-awaited Task and leave the tiles silently frozen at stale values."""
        try:
            await self._refresh()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("Dashboard refresh failed")
            self.regime_header.setText(f"Dashboard refresh failed: {exc}")

    def _refresh_corporate_actions(self) -> None:
        """The pending-action banner (M39, R1).

        Says the MODE as well as the action, because "detected" and "adjusted"
        are different facts and shadow mode does only the first. An operator
        reading "split pending" and assuming the stop has been moved is the
        failure this wording exists to prevent - the same shape as M60's
        "declared" being read as "fixed".
        """
        monitor = getattr(self.runtime, "corporate_action_monitor", None)
        acting = self.runtime.settings.corporate_action_mode == "act"
        text = corporate_action_banner_text(monitor, acting)
        if text is None:
            self.corporate_action_banner.setVisible(False)
            return
        self.corporate_action_banner.setText(text)
        self.corporate_action_banner.setVisible(True)

    def _seed_equity_history(self) -> None:
        """Start from what was already recorded, not from an empty axis (M56).

        `equity_curve.csv` has been written every poll since 26 July and read
        back since M31c, so the history exists - the chart simply never asked
        for it and began blank at every launch. On a time axis that matters
        more than it did on a sample count: an axis whose range is "the last
        four minutes" cannot show that the market was shut overnight.

        Failure here is not worth a broken screen. The live path appends to
        these lists regardless, so an unreadable curve costs the historical
        span and nothing else.
        """
        try:
            points = self.runtime.equity_curve.points()[-_MAX_EQUITY_POINTS:]
        except Exception:  # noqa: BLE001 - a dashboard must still open
            logger.warning("Could not seed the equity chart from the recorded curve", exc_info=True)
            return
        self._equity_times = [point.ts.timestamp() for point in points]
        self._equity_history = [point.equity for point in points]
        if self._equity_history:
            self.equity_curve.setData(self._equity_times, self._equity_history)

    async def _refresh(self) -> None:
        # One shared, throttled read rather than two broker calls per tick.
        # This screen's two-second timer was spending sixty requests a minute
        # of a two-hundred-per-minute budget on repainting.
        snapshot = await self.runtime.account_poller.snapshot()
        # Item 46: IBKR never reports a previous close, so the panel needs
        # the equity monitor's day-start basis or it renders nothing while
        # the autonomy gate is happily using a figure of its own.
        monitor = getattr(self.runtime, "equity_monitor", None)
        state = getattr(monitor, "state", None)
        self.balances_panel.set_day_start_equity(
            getattr(state, "day_start_equity", None) if state is not None else None
        )
        self.balances_panel.update_from(snapshot)
        self._refresh_corporate_actions()

        positions = list(snapshot.positions)
        equity = snapshot.balances.equity
        if equity is None:
            return
        self._equity_history.append(equity)
        self._equity_times.append(datetime.now(UTC).timestamp())
        if len(self._equity_history) > _MAX_EQUITY_POINTS:
            trim = len(self._equity_history) - _MAX_EQUITY_POINTS
            del self._equity_history[:trim]
            del self._equity_times[:trim]
        self.equity_curve.setData(self._equity_times, self._equity_history)

        if len(self._equity_history) >= 2:
            peak = max(self._equity_history)
            current = self._equity_history[-1]
            drawdown_pct = (peak - current) / peak if peak > 0 else 0.0
            limit_pct = self.runtime.settings.max_drawdown_limit_pct
            self.drawdown_tile.set_value(
                f"{drawdown_pct:.2%} / {limit_pct:.0%}",
                color=theme.DANGER if drawdown_pct >= limit_pct else theme.SUCCESS,
            )

        if len(self._equity_history) >= _MIN_POINTS_FOR_SHARPE:
            returns = pd.Series(self._equity_history).pct_change().dropna()
            if returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * (252**0.5)
                self.sharpe_tile.set_value(f"{sharpe:.2f}")

        latest_decisions = self.runtime.risk_engine.audit_log.entries()
        if latest_decisions:
            portfolio_check = latest_decisions[-1].inputs.get("portfolio_check")
            if portfolio_check and "var_95" in portfolio_check:
                self.var_tile.set_value(f"{portfolio_check['var_95']:.2%}")

        self.adopted_panel.update_from(
            assess_adopted_positions(
                adopted_baseline=self.runtime.oms.adopted_baseline,
                positions=positions,
                stops=self.runtime.oms.position_stops(),
                equity=equity,
                settings=self.runtime.settings,
                # The app's own record of what it opened, so a restart reads
                # as a restart rather than as an unexplained holding (M33e).
                opened_by_this_app=self.runtime.opened_position_symbols(),
            )
        )

        # A second `position_stops()` read, not a shared one - the adopted
        # panel above already read one a few lines up (positions panel brief
        # review, M1: an earlier version of this comment claimed otherwise).
        # Harmless duplication: `position_stops()` is a synchronous local
        # dict copy, never a broker call, so it is not the M21 pattern this
        # screen otherwise follows for the actual broker round trip - the
        # account snapshot at the top of `_refresh` is the one that matters.
        resting_stops = self.runtime.oms.position_stops()
        views = build_position_views(
            positions=positions,
            entries=(
                self.runtime.signal_bridge.position_entries()
                if self.runtime.signal_bridge is not None
                else {}
            ),
            resting_stops=resting_stops,
            # The SAME derivation the aggregate cap is gated on (piece 1 of
            # the brief) - never recomputed here, or this panel could show a
            # per-position risk figure that has quietly drifted from the one
            # that refuses entries.
            snapshot=self.runtime.risk_engine.governor.snapshot(positions, resting_stops, equity),
            settings=self.runtime.settings,
            bars_for=self._bars_for,
            # The AVAILABLE set, not `settings.deployed_strategies_tuple` (M4,
            # positions panel brief review) - a position's `entry.strategy`
            # can only be resolved against a strategy this dashboard can look
            # up by name, and the available set is the superset that
            # includes it. A judgement call the operator has not been asked
            # about; left as-is.
            strategies=self.runtime.available_strategies,
            # The true edge of the system: everything downstream of here
            # (position_view.py) takes an injected clock, and this is where
            # the wall clock actually gets read - the same boundary
            # SignalToOrderBridge._now draws for the churn rails.
            clock=lambda: datetime.now(UTC),
        )
        self._populate_positions_table(views)

    def _bars_for(self, symbol: str) -> pd.DataFrame | None:
        """The bars `PositionView.exit_distance` is computed from.

        Not literally the aggregator the exit condition is judged against
        (positions panel brief review, M2: an earlier version of this
        docstring claimed that). `exit_distance` is a STRATEGY accessor, and
        the signal that would actually fire comes from `on_features`
        evaluating `StrategyEngine.bars` - a separate `MultiSymbolAggregator`
        instance from this bridge's own `bars`. The two stay in step because
        `runtime.py`'s `WarmStart` seeds both of them (and `FeatureEngine.bars`)
        from one shared warm-start pass and then feeds all three the same
        live event stream - not because reading this one is reading "the
        same aggregator" the strategy engine does.

        Read-only (M6): `frame_if_present` never creates an aggregator entry
        for a symbol this bridge has not already seen the way `frame()`
        would, so opening the dashboard cannot mutate `SignalToOrderBridge`
        state - the same principle `position_entries()` already applies to
        the entry record.
        """
        bridge = self.runtime.signal_bridge
        if bridge is None:
            return None
        return bridge.bars.frame_if_present(symbol)

    def _populate_positions_table(self, views: tuple[PositionView, ...]) -> None:
        table = self.positions_table
        table.setRowCount(len(views))
        for row, view in enumerate(views):
            cells = (
                view.symbol,
                f"{view.quantity:g}",
                _format_price(view.entry_price),
                _format_price(view.last_price),
                _format_pnl(view.pnl_pct, view.pnl_r),
                _format_pct(view.exit_distance),
                _format_pct(view.stop_distance),
                _format_pct(view.risk_share, decimals=0),
                ", ".join(view.notes),
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                # Every cell, not only Status: the M87 fix is "elide with an
                # ellipsis and keep the full text one hover away", and a
                # narrow Entry or Risk column truncates exactly as easily as
                # a narrow Reason column does.
                item.setToolTip(text)
                if col in _POSITIONS_NUMERIC_COLUMNS:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if col == _POSITIONS_PNL_COLUMN and view.pnl_pct is not None:
                    colour = theme.SUCCESS if view.pnl_pct >= 0 else theme.DANGER
                    item.setForeground(QColor(colour))
                if col == _POSITIONS_STATUS_COLUMN and "no stop resting" in view.notes:
                    # The alarming blocker, coloured the same as the adopted
                    # panel's own DANGER state - both say the same thing:
                    # unknown protection is treated as none.
                    item.setForeground(QColor(theme.DANGER))
                table.setItem(row, col, item)

    async def _on_regime(self, event: RegimeEvent) -> None:
        self._regime_label = event.label
        self.regime_header.setText(f"Regime: {event.label} (scalar={event.exposure_scalar:.2f})")
        top_probs = sorted(event.probs.items(), key=lambda kv: kv[1], reverse=True)[:3]
        summary = ", ".join(f"{label}={prob:.0%}" for label, prob in top_probs)
        self.ai_note_label.setText(
            f"Current regime is '{event.label}' (top probabilities: {summary}). "
            "Review the Regime Monitor for full detail before adjusting exposure."
        )
        self.review_button.setText(_ACKNOWLEDGE_LABEL)

    def _on_review_clicked(self) -> None:
        """Explicit human action; never triggers a trade (spec §K).

        ⚠️ The LOG line is the point of this handler, not the tick. A button
        that changes its own caption and nothing else is not evidence of
        anything - it resets on the next `RegimeEvent`, and nobody can ask it
        afterwards whether the note was ever read. The label it was
        acknowledged AGAINST is carried explicitly, because "acknowledged at
        14:02" answers a different and much weaker question than "acknowledged
        the bull note at 14:02".
        """
        acknowledged_at = datetime.now(UTC)
        label = self._regime_label or "unknown"
        logger.info(
            "Regime note ACKNOWLEDGED by the operator: regime %s, at %s. "
            "Acknowledgement only - nothing was applied to the trading system.",
            label,
            acknowledged_at.isoformat(),
        )
        self.review_button.setText(
            f"Acknowledged ✓ {format_session_time(acknowledged_at, self.runtime.settings.market)}"
        )

    # --- manual position close (2026-09-01 spec, Task 7) -------------------
    #
    # THE UI STAYS THIN. This block's whole job is: gate the button on
    # selection, ask the operator, call close_position, render
    # CloseResult.detail - every sequencing decision (cancel-then-verify,
    # recovery on a failed sell) lives in PositionCloser, not here.
    #
    # _confirm_close is its own method for the same reason blotter.py's
    # _confirm()/_show_error() are (see that module's docstring): so a test
    # can answer the dialog, or capture what was shown, without driving a
    # real modal - tests/presentation/conftest.py's autouse
    # no_blocking_dialogs fixture makes any unpatched QMessageBox call fail
    # loudly rather than hang the suite.

    def _sync_close_button(self) -> None:
        """Enabled only for exactly one selected row, and never while a close
        is in flight. Both conditions in ONE place, because the selection
        signal fires on its own and would otherwise re-enable the button in
        the middle of an irreversible operation."""
        selected = len(self.positions_table.selectionModel().selectedRows())
        self.close_position_button.setEnabled(selected == 1 and not self._close_in_flight)

    def _on_close_clicked(self) -> None:
        if self._close_in_flight:
            # ⚠️ The re-entrancy rail. `clicked` is not the only way in (a
            # test, or a future keyboard shortcut, calls this directly), so
            # the guard lives here as well as on the button's enabled state.
            # A second pass sends a SECOND full-size market sell.
            return
        rows = self.positions_table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        row = rows[0].row()
        symbol_item = self.positions_table.item(row, 0)
        quantity_item = self.positions_table.item(row, 1)
        if symbol_item is None or quantity_item is None:
            return
        symbol = symbol_item.text()
        quantity = quantity_item.text()
        closer = self.runtime.closer
        if closer is None:
            self._show_error("Closing is unavailable: no PositionCloser is wired for this runtime.")
            return
        legs = closer.believed_legs_for(symbol)
        halt_reason = self.runtime.kill_switch.reason if self.runtime.kill_switch.tripped else None
        if not self._confirm_close(symbol, quantity, legs, halt_reason):
            return
        self._close_in_flight = True
        self._sync_close_button()
        asyncio.ensure_future(self._run_close(closer, symbol))

    async def _run_close(self, closer: PositionCloser, symbol: str) -> None:
        """Await the closer and put its own words on screen.

        Takes `closer` as a parameter (narrowed to non-None by the caller)
        rather than re-reading `self.runtime.closer` and asserting - the
        assert this replaced tripped bandit's B101 for no benefit `_on_close_
        clicked` had not already provided.

        `CloseResult.detail` is always populated and is written for the
        operator, so it is rendered verbatim rather than re-summarised here -
        two descriptions of one outcome drift, and the operator would be
        reading an explanation of a decision taken on different words.

        ⚠️ No `acknowledge_halt`: `close_position` no longer takes one and
        REFUSES while the switch is tripped, before touching the broker. The
        UI's job during a halt is to say so, not to offer a way past it.

        ⚠️ EVERYTHING IS IN A try/finally, AND THE EXCEPT ARM IS LOAD-BEARING.
        This runs under `asyncio.ensure_future` with nothing awaiting it, so
        an exception raised in here - after the protective legs have already
        been cancelled - had nowhere to go but a "Task exception was never
        retrieved" on stderr that nobody reads, with the position left BARE
        and NOTHING on screen. The operator must be told, and the button must
        come back either way.
        """
        try:
            result = await closer.close_position(symbol, operator=_OPERATOR)
            # ⚠️ A REFUSAL IS NOT ALWAYS HARMLESS, and assuming it was put a
            # bare downside behind a reassuring information dialog. Three of
            # `_cancel_legs`' failure branches fire AFTER `cancel_order` has
            # already gone out, so the position can be left with part or all
            # of its bracket deleted while the text truthfully says "NOTHING
            # was sold". `cancelled_legs` on a REFUSED result is exactly that
            # case, and it is as serious as UNPROTECTED.
            #
            # ⚠️ AND `issued_legs` IS THE OTHER HALF, which keying on
            # `cancelled_legs` alone missed. That tuple holds legs CONFIRMED
            # GONE, so a close whose cancels went out and confirmed NOTHING -
            # every leg still settling in `PendingCancel`, or the second
            # cancel raising after the first was accepted - carried an EMPTY
            # `cancelled_legs` and was rendered as an information dialog. The
            # accepted cancel then lands and the position is part or wholly
            # bare, announced by a box the operator has already dismissed.
            # "A cancel went out" is the discriminator; whether it was
            # confirmed is exactly what is unknown.
            #
            # A refusal that cancelled nothing stays an information dialog -
            # making every refusal a critical modal only teaches the operator
            # to dismiss red boxes.
            already_stripped = result.outcome is CloseOutcome.REFUSED and bool(
                result.cancelled_legs or result.issued_legs
            )
            if result.outcome is CloseOutcome.UNPROTECTED or already_stripped:
                # Blocking, not a status line: the position is held with part
                # or all of its protection gone, and that must be impossible
                # to miss.
                self._show_error(result.detail)
            else:
                self._show_result(result.detail)
        except Exception as exc:  # noqa: BLE001 - a swallowed one leaves a bare position
            logger.critical(
                "MANUAL CLOSE of %s RAISED: %s. The protective legs may ALREADY have "
                "been cancelled, so the position may be held with no stop. Check the "
                "broker by hand.",
                symbol,
                exc,
                exc_info=True,
            )
            self._show_error(
                f"The close of {symbol} FAILED with an error: {exc}\n\n"
                f"⚠️ The protective legs may ALREADY have been cancelled, in which "
                f"case {symbol} is held with NO STOP. Check the broker by hand "
                f"before doing anything else."
            )
        finally:
            self._close_in_flight = False
            self._sync_close_button()

    def _confirm_close(
        self,
        symbol: str,
        quantity: str,
        legs: tuple[Order, ...],
        halt_reason: str | None,
    ) -> bool:
        """Ask before selling the whole position. Separated so a test can
        answer it (see blotter.py's _confirm docstring for why).

        The halt reason, when present, is quoted VERBATIM in the message
        rather than the dialog merely saying the switch is tripped - the same
        "state the reason, not just the fact" rule PositionCloser itself
        applies to its own refusal text.

        ⚠️ It no longer offers an override. It said "closing now overrides the
        halt for this position only", which was false and dangerous: the
        cancel bypasses sign-off and would have gone through, while the sell
        and the re-protect are both rejected by the tripped switch - the
        stop deleted, nothing sold, the bracket unrestorable. The dialog now
        says what will actually happen, which is a refusal.
        """
        lines = [
            f"Close the entire {symbol} position ({quantity} share(s))?",
            "",
            f"This app BELIEVES {len(legs)} protective leg(s) are resting. The "
            "cancel re-reads the broker and acts on whatever is actually "
            "there, not this count, then the position is sold at market. If "
            "the sell fails, the original bracket is re-placed.",
        ]
        if halt_reason is not None:
            lines.append("")
            lines.append(f"⚠️ THE KILL SWITCH IS TRIPPED: {halt_reason}")
            lines.append(
                "A manual close is REFUSED while it is tripped - nothing will be "
                "cancelled and nothing will be sold. Reset the kill switch first, "
                "then close."
            )
        answer = QMessageBox.question(
            self,
            "Close position?",
            "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Position close failed", message)

    def _show_result(self, message: str) -> None:
        QMessageBox.information(self, "Position close", message)
