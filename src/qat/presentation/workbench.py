"""Strategy Workbench (spec §G/§K): pick a strategy + symbol, run a
vectorised backtest against synthetic history, review the 10-metric panel,
equity-vs-benchmark chart, and Monte-Carlo outcome cone, read an AI
robustness note, and - the one real action here - "Deploy to Paper" adds
the vetted strategy to the *live* StrategyEngine's active list. Nothing
below ever places an order itself: OMS.sign_off (Blotter) is still the only
path to a transmitted trade.

Backtests run against synthetic daily bars (reusing SyntheticMarketDataSource's
per-symbol random walk with re-labelled daily timestamps) rather than real
history - no historical data vendor is wired into this app (spec names none),
matching the mock-everywhere stance used throughout. A per-symbol seed is
derived from the symbol string itself (not Python's hash()) so results are
reproducible run to run.
"""

from __future__ import annotations

import asyncio
import logging

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.data.fundamentals import FundamentalSnapshot
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.backtester.costs import CostModel
from qat.domain.backtester.monte_carlo import run_monte_carlo
from qat.domain.backtester.results import BacktestResult, WalkForwardResult
from qat.domain.backtester.signal_adapter import generate_signal_series
from qat.domain.backtester.sizing import FixedFractionalSizer
from qat.domain.backtester.vectorized_engine import VectorizedBacktester
from qat.domain.backtester.walk_forward import run_walk_forward
from qat.presentation import theme
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel
from qat.presentation.widgets import KpiTile

logger = logging.getLogger(__name__)

_PERCENT_METRICS = {"cagr", "volatility", "max_drawdown", "win_rate", "var_95"}
_WF_COLUMNS = ("From", "To", "CAGR", "Sharpe", "Max DD", "Trades")
# Below this many windows the spread of a metric across them is arithmetic
# rather than evidence, and saying so beats printing a confident number.
_MIN_INFORMATIVE_WINDOWS = 3
# At or below this many trades per window, the windows are slices of a hold
# rather than independent tests. Two rather than one, because a window with two
# trades is still an entry manufactured at the boundary plus one real exit -
# swing's measured shape is exactly one per window.
_MAX_TRADES_FOR_SLICING_CAVEAT = 2
# Below this, resampling a trade sequence produces one observation repeated
# rather than a distribution. Ten is not a statistical threshold - it is the
# point below which the cone is obviously misleading rather than merely thin.
_MIN_TRADES_FOR_A_CONE = 10
_METRICS_PER_ROW = 5


class WorkbenchScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.level = UiLevel.from_settings(runtime.settings)
        self._last_result: BacktestResult | None = None

        layout = QVBoxLayout(self)

        # What Guided sees instead of the tools. §4.5 says "not shown", and an
        # emptied screen is not that - M45's rule is that an absent control is
        # one level away AND THE LEVEL SELECTOR SAYS SO, which a blank tab
        # fails. The Risk Console faced the identical instruction at M67 and
        # kept its tab, so the tab stays here too.
        self.guided_notice = QLabel(
            "<b>Strategy Workbench — research, not operation.</b><br>"
            "This screen backtests a strategy against history and decides whether to deploy "
            "it. Reading a backtest correctly is most of the work: the figures it produces "
            "look equally confident whether they rest on two hundred trades or on one.<br><br>"
            "It becomes available at the <b>Standard</b> level, and the walk-forward tests "
            "and the deploy control at <b>Professional</b>. Change the level in Settings."
        )
        self.guided_notice.setWordWrap(True)
        self.guided_notice.setStyleSheet(theme.text(theme.ACCENT, size=theme.BODY))
        # Pinned to the top. With every other widget hidden the label is the
        # only thing left for the layout to stretch, and a QLabel centres its
        # text vertically - so rendering it showed the notice floating in the
        # middle of an otherwise empty screen, which reads as a rendering fault
        # rather than as a deliberate message.
        self.guided_notice.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.guided_notice)

        controls = QHBoxLayout()
        self.strategy_picker = QComboBox()
        for strategy in runtime.available_strategies:
            self.strategy_picker.addItem(strategy.name)
        self.symbol_picker = QComboBox()
        for symbol in runtime.watchlist:
            self.symbol_picker.addItem(symbol)
        self.run_button = QPushButton("Run Backtest")
        self.run_button.clicked.connect(self._on_run_clicked)
        self.deploy_button = QPushButton("Deploy to Paper")
        self.deploy_button.clicked.connect(self._on_deploy_clicked)
        self.deploy_button.setEnabled(False)
        controls.addWidget(QLabel("Strategy:"))
        controls.addWidget(self.strategy_picker)
        controls.addWidget(QLabel("Symbol:"))
        controls.addWidget(self.symbol_picker)
        controls.addWidget(self.run_button)
        controls.addWidget(self.deploy_button)
        controls.addStretch(1)
        self.controls_widget = QWidget()
        self.controls_widget.setLayout(controls)
        layout.addWidget(self.controls_widget)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        # theme.DANGER, not #d9534f. The design system's own migration note
        # says '#d9534f (3 uses) -> DANGER'; this was one of the sites it did
        # not reach, and 24 more like it survive elsewhere (M74).
        self.status_label.setStyleSheet(theme.text(theme.DANGER))
        layout.addWidget(self.status_label)

        # The plain-language summary §4.5 lists for Standard and that never
        # existed. Placed above the charts because it is what the charts are
        # for, and a reader who stops after one line should stop after this one.
        self.headline_label = QLabel("")
        self.headline_label.setWordWrap(True)
        self.headline_label.setStyleSheet(theme.text(theme.ACCENT, size=theme.BODY, bold=True))
        layout.addWidget(self.headline_label)

        self.equity_plot = pg.PlotWidget(title="Equity vs Benchmark")
        # Bar index, not dates (M55). `result.equity_curve` IS indexed by
        # timestamp, but `.to_numpy()` at the render site discards that index,
        # so what reaches the chart is a bare sequence. Labelled for what is
        # actually drawn rather than for what the data could have supported -
        # plotting against the real dates is a separate change, and mislabelling
        # this one in anticipation would be worse than the honest label.
        theme.label_axes(self.equity_plot, bottom="Daily bars (backtest)", left="Equity ($)")
        self.equity_curve_item = self.equity_plot.plot(pen="y", name="strategy")
        self.benchmark_curve_item = self.equity_plot.plot(pen="c", name="benchmark")
        layout.addWidget(self.equity_plot)

        self.metrics_grid = QGridLayout()
        layout.addLayout(self.metrics_grid)
        self._metric_tiles: dict[str, KpiTile] = {}

        self.mc_plot = pg.PlotWidget(title="Monte Carlo Outcome Cone")
        # One step per TRADE, not per day (M55). The paths are built by
        # resampling the backtest's trade sequence, so the x-axis counts trades
        # taken - which is why the cone widens with trade count rather than with
        # elapsed time, and why two strategies' cones are not comparable
        # side-by-side unless they took the same number of trades.
        theme.label_axes(self.mc_plot, bottom="Trades simulated", left="Equity ($)")
        self.mc_p5_item = self.mc_plot.plot(pen="r", name="p5")
        self.mc_p50_item = self.mc_plot.plot(pen="y", name="p50")
        self.mc_p95_item = self.mc_plot.plot(pen="g", name="p95")
        layout.addWidget(self.mc_plot)

        # What the cone was resampled FROM. Without it, a cone built from one
        # trade looks exactly like a cone built from two hundred.
        self.mc_caption = QLabel("")
        self.mc_caption.setWordWrap(True)
        self.mc_caption.setStyleSheet(f"color: {theme.MUTED}; font-size: {theme.CAPTION}px;")
        layout.addWidget(self.mc_caption)

        self.walk_forward_group = self._build_walk_forward_group()
        layout.addWidget(self.walk_forward_group)

        self.ai_note_header = QLabel("AI Robustness Note")
        layout.addWidget(self.ai_note_header)
        self.ai_note_label = QLabel("(run a backtest to get an AI note)")
        self.ai_note_label.setWordWrap(True)
        layout.addWidget(self.ai_note_label)

        self._apply_level()

    def _apply_level(self) -> None:
        """Three levels, three outcomes.

        Guided gets the notice and none of the tools: §4.5 is explicit that
        backtesting is not a beginner task, and a half-understood backtest is
        worse here than no backtest, because the deploy control is on the same
        screen.

        Standard gets the backtest, the charts, the summary and the AI note.
        **Professional additionally gets walk-forward and the deploy control** -
        walk-forward because per-window statistics are the evidence base for
        deploying, and deploy because it is the one control on this screen that
        changes what the account does.

        Hidden, never disabled (M45). The deploy button's own `setEnabled` is a
        different thing entirely and is left alone - it says "this strategy is
        already live", which is state rather than level, and the brief's "do not
        touch the deploy gate" is exactly that logic.
        """
        shows_tools = self.level.shows_advanced()
        self.guided_notice.setVisible(not shows_tools)
        for widget in (
            self.controls_widget,
            self.status_label,
            self.headline_label,
            self.equity_plot,
            self.mc_plot,
            self.mc_caption,
            self.ai_note_header,
            self.ai_note_label,
        ):
            widget.setVisible(shows_tools)
        for tile in self._metric_tiles.values():
            tile.setVisible(shows_tools)

        self.walk_forward_group.setVisible(self.level.prefers_density())
        # The one control here that changes what the account does.
        self.deploy_button.setVisible(self.level.prefers_density())

    def _build_walk_forward_group(self) -> QGroupBox:
        """Out-of-sample evaluation across rolling windows (spec M19).

        Written and tested since M4 but reachable from nowhere until now, which
        left the single in-sample backtest above plus a bootstrap as the whole
        evidence base for deploying a strategy. Those two share a weakness:
        both are computed from one pass over one period, so a strategy that
        worked in one regime and nowhere else looks the same as one that
        worked throughout.
        """
        group = QGroupBox("Walk-Forward (out-of-sample)")
        outer = QVBoxLayout(group)

        controls = QHBoxLayout()
        self.wf_in_sample_input = QSpinBox()
        self.wf_in_sample_input.setRange(10, 2000)
        self.wf_in_sample_input.setSingleStep(10)
        self.wf_in_sample_input.setValue(self.runtime.settings.walk_forward_in_sample_bars)
        self.wf_out_sample_input = QSpinBox()
        self.wf_out_sample_input.setRange(5, 2000)
        self.wf_out_sample_input.setSingleStep(5)
        self.wf_out_sample_input.setValue(self.runtime.settings.walk_forward_out_sample_bars)
        self.wf_run_button = QPushButton("Run Walk-Forward")
        self.wf_run_button.clicked.connect(self._on_walk_forward_clicked)
        controls.addWidget(QLabel("In-sample bars:"))
        controls.addWidget(self.wf_in_sample_input)
        controls.addWidget(QLabel("Out-of-sample bars:"))
        controls.addWidget(self.wf_out_sample_input)
        controls.addWidget(self.wf_run_button)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.wf_headline = QLabel(
            "Run a walk-forward to see whether the result above survives out of sample."
        )
        self.wf_headline.setWordWrap(True)
        self.wf_headline.setStyleSheet("font-weight: bold;")
        outer.addWidget(self.wf_headline)

        self.wf_table = QTableWidget(0, len(_WF_COLUMNS))
        self.wf_table.setHorizontalHeaderLabels(list(_WF_COLUMNS))
        self.wf_table.setMaximumHeight(200)
        outer.addWidget(self.wf_table)

        return group

    def _on_walk_forward_clicked(self) -> None:
        asyncio.ensure_future(self._run_walk_forward())

    async def _run_walk_forward(self) -> None:
        self.wf_run_button.setEnabled(False)
        self.wf_headline.setText("Running...")
        try:
            strategy_name = self.strategy_picker.currentText()
            strategy = next(
                (s for s in self.runtime.available_strategies if s.name == strategy_name), None
            )
            symbol = self.symbol_picker.currentText()
            if strategy is None or not symbol:
                return

            in_bars = self.wf_in_sample_input.value()
            out_bars = self.wf_out_sample_input.value()

            bars = await self.runtime.history_source.get_daily_bars(symbol)
            if len(bars) < in_bars + out_bars:
                self.wf_headline.setText(
                    f"Not enough history: {len(bars)} bars available, "
                    f"{in_bars + out_bars} needed for even one window. "
                    "Shorten the windows or use a longer history."
                )
                self.wf_table.setRowCount(0)
                return

            fundamentals = await self.runtime.strategy_engine.fundamentals_source.get_fundamentals(
                symbol
            )
            signal_series = generate_signal_series(strategy, symbol, bars, fundamentals)
            backtester = VectorizedBacktester(
                # from_settings, not CostModel() (M33). The bare constructor
                # defaults min_commission to 0.0 - it exists so pre-M27
                # backtests keep their old numbers - so every backtest, cone
                # and walk-forward window this app has ever shown was costed
                # with NO per-transaction floor, against a configured 6.60.
                # A round trip is 13.20 before the market moves, and the
                # promotion gate was reading results that never paid it.
                CostModel.from_settings(self.runtime.settings),
                FixedFractionalSizer(settings=self.runtime.settings),
            )
            result = run_walk_forward(
                backtester,
                symbol,
                bars,
                signal_series,
                in_sample_bars=in_bars,
                out_sample_bars=out_bars,
            )
            self._render_walk_forward(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("Walk-forward failed")
            self.wf_headline.setText(f"Walk-forward failed: {exc}")
        finally:
            self.wf_run_button.setEnabled(True)

    def _render_walk_forward(self, result: WalkForwardResult) -> None:
        windows = result.windows
        self.wf_table.setRowCount(len(windows))
        for row, window in enumerate(windows):
            metrics = window.out_sample_result.metrics
            values = (
                f"{window.out_sample_start:%Y-%m-%d}",
                f"{window.out_sample_end:%Y-%m-%d}",
                f"{metrics.get('cagr', 0.0):.2%}",
                f"{metrics.get('sharpe', 0.0):.2f}",
                f"{metrics.get('max_drawdown', 0.0):.2%}",
                str(len(window.out_sample_result.trades)),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:  # Sharpe: the column the headline is about
                    item.setForeground(
                        QColor(theme.SUCCESS)
                        if metrics.get("sharpe", 0.0) > 0
                        else QColor(theme.DANGER)
                    )
                self.wf_table.setItem(row, column, item)
        self.wf_table.resizeColumnsToContents()
        self.wf_headline.setText(_walk_forward_headline(result))

    def _on_run_clicked(self) -> None:
        asyncio.ensure_future(self._run_backtest())

    def _on_deploy_clicked(self) -> None:
        strategy_name = self.strategy_picker.currentText()
        strategy = next(
            (s for s in self.runtime.available_strategies if s.name == strategy_name), None
        )
        if strategy is None:
            return
        self.runtime.strategy_engine.deploy(strategy)
        self.deploy_button.setText(f"Deployed: {strategy_name} ✓")
        self.deploy_button.setEnabled(False)

    async def _run_backtest(self) -> None:
        self.run_button.setEnabled(False)
        self.status_label.setText("")
        try:
            strategy_name = self.strategy_picker.currentText()
            strategy = next(
                (s for s in self.runtime.available_strategies if s.name == strategy_name), None
            )
            symbol = self.symbol_picker.currentText()
            if strategy is None or not symbol:
                return

            bars = await self.runtime.history_source.get_daily_bars(symbol)
            benchmark_symbol = self.runtime.benchmark_symbol
            benchmark_bars = (
                bars
                if symbol == benchmark_symbol
                else await self.runtime.history_source.get_daily_bars(benchmark_symbol)
            )
            benchmark_prices = benchmark_bars.set_index("ts")["close"]

            fundamentals = await self.runtime.strategy_engine.fundamentals_source.get_fundamentals(
                symbol
            )
            signal_series = generate_signal_series(strategy, symbol, bars, fundamentals)

            backtester = VectorizedBacktester(
                # from_settings, not CostModel() (M33). The bare constructor
                # defaults min_commission to 0.0 - it exists so pre-M27
                # backtests keep their old numbers - so every backtest, cone
                # and walk-forward window this app has ever shown was costed
                # with NO per-transaction floor, against a configured 6.60.
                # A round trip is 13.20 before the market moves, and the
                # promotion gate was reading results that never paid it.
                CostModel.from_settings(self.runtime.settings),
                FixedFractionalSizer(settings=self.runtime.settings),
            )
            result = backtester.run(symbol, bars, signal_series, benchmark_prices=benchmark_prices)
            self._last_result = result

            self._render_result(result, benchmark_prices, backtester.starting_equity)

            mc_result = run_monte_carlo(result.trades, starting_equity=backtester.starting_equity)
            self._render_monte_carlo(mc_result.paths, len(result.trades))

            # The AI note is commentary on a backtest that already succeeded -
            # a failing/misconfigured LLM must not discard the results above,
            # but it must be visible rather than silently doing nothing.
            try:
                await self._render_ai_note(
                    symbol, strategy.name, result, signal_series, fundamentals
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the user below
                logger.exception("AI robustness note failed")
                self.ai_note_label.setText(f"AI note unavailable - {exc}")

            self.deploy_button.setText("Deploy to Paper")
            self.deploy_button.setEnabled(strategy not in self.runtime.strategy_engine.strategies)
            if strategy in self.runtime.strategy_engine.strategies:
                self.deploy_button.setText(f"Deployed: {strategy_name} ✓")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("Backtest failed")
            self.status_label.setText(f"Backtest failed: {exc}")
        finally:
            self.run_button.setEnabled(True)

    def _render_result(
        self, result: BacktestResult, benchmark_prices: pd.Series, starting_equity: float
    ) -> None:
        self.equity_curve_item.setData(result.equity_curve.to_numpy())
        benchmark_equity = starting_equity * (benchmark_prices / benchmark_prices.iloc[0])
        self.benchmark_curve_item.setData(benchmark_equity.to_numpy())

        for tile in self._metric_tiles.values():
            tile.setParent(None)
        self._metric_tiles.clear()
        for index, (name, value) in enumerate(sorted(result.metrics.items())):
            text = f"{value:.2%}" if name in _PERCENT_METRICS else f"{value:.3f}"
            tile = KpiTile(name, text)
            tile.setVisible(self.level.shows_advanced())
            self._metric_tiles[name] = tile
            self.metrics_grid.addWidget(tile, index // _METRICS_PER_ROW, index % _METRICS_PER_ROW)

        self.status_label.setText("  ".join(result.warnings))
        self.headline_label.setText(_backtest_headline(result))

    def _render_monte_carlo(self, paths: pd.DataFrame, trade_count: int) -> None:
        quantiles = paths.quantile([0.05, 0.50, 0.95], axis=1)
        self.mc_p5_item.setData(quantiles.loc[0.05].to_numpy())
        self.mc_p50_item.setData(quantiles.loc[0.50].to_numpy())
        self.mc_p95_item.setData(quantiles.loc[0.95].to_numpy())
        self.mc_caption.setText(_monte_carlo_caption(trade_count))

    async def _render_ai_note(
        self,
        symbol: str,
        strategy_name: str,
        result: BacktestResult,
        signal_series: pd.Series,
        fundamentals: FundamentalSnapshot | None = None,
    ) -> None:
        context = AdvisoryContext(
            symbol=symbol,
            regime_label="unknown",
            regime_probs={},
            positions={},
            risk_metrics={},
            candidate_signal={
                "strategy": strategy_name,
                "last_target_exposure": float(signal_series.iloc[-1]),
            },
            backtest_stats=result.metrics,
            # Already fetched for the signal series itself (M40) - the note was
            # commenting on a fundamentals-driven strategy while knowing none of
            # the fundamentals that drove it.
            fundamentals=fundamentals.available_figures() if fundamentals is not None else {},
        )
        recommendation = await self.runtime.ai_service.get_regime_narrative(context)
        flags = ", ".join(recommendation.risk_flags) if recommendation.risk_flags else "none"
        confidence_pct = f"{recommendation.confidence:.0%}"
        self.ai_note_label.setText(
            f"[{recommendation.recommendation.upper()}, confidence={confidence_pct}] "
            f"{recommendation.rationale} (risk flags: {flags})"
        )


def _monte_carlo_caption(trade_count: int) -> str:
    """What the cone was built from, and whether that is enough to be a cone.

    The other half of the sentence M69 addressed. ROADMAP covers both tools at
    once - *"the Monte Carlo cone resamples near-buy-and-holds, and walk-forward
    manufactures exactly one entry per window at the slice boundary"* - and only
    the walk-forward panel was given its caveat.

    The cone is built by RESAMPLING the backtest's trade sequence. Resampling a
    sequence of one trade produces something that looks like a distribution and
    is one observation repeated: the spread between p5 and p95 is then an
    artefact of the resampling, not a range of plausible outcomes.

    Names the count rather than warning in the abstract, and self-suppresses
    above the threshold, for the same reason as the walk-forward caveat - a
    disclaimer printed on every result stops being read.
    """
    if trade_count <= 0:
        return "No trades to resample: the cone above is empty, not a forecast of zero."
    caption = f"Resampled from {trade_count} trade(s) in the backtest above."
    if trade_count <= _MIN_TRADES_FOR_A_CONE:
        caption += (
            " That is too few to resample into a distribution - the spread between"
            " p5 and p95 is one observation repeated, not a range of plausible"
            " outcomes."
        )
    return caption


def _backtest_headline(result: BacktestResult) -> str:
    """What the backtest above actually says, in a sentence (M74).

    §4.5 lists a "plain-language summary" in Standard's column and there was
    never one. What Standard got was `result.metrics` rendered as KPI tiles in
    ALPHABETICAL order - alpha, beta, calmar, cagr, information_ratio - with
    nothing to say which of them decides anything, and a reader who cannot rank
    nine metrics is left to assume the first one matters.

    Built on the same three judgements as `_walk_forward_headline`, for the same
    reasons:

    * **Trade count leads the caveats, not the returns.** ROADMAP measured that
      swing changes exposure 7 times in 300 bars. A Sharpe computed over one
      trade is a property of that trade. M69 gave the cone and the windows this
      caveat; the backtest they are both derived from never had it.
    * **Against the benchmark, not in isolation.** A 12% CAGR is a triumph or a
      failure depending entirely on what buying the index did over the same
      bars, and the chart plots both while the tiles report only one.
    * **The drawdown is stated as what it would have felt like**, because
      max_drawdown as a percentage is the number people agree to in advance and
      do not sit through.

    It self-suppresses nothing: unlike a caveat, a summary that vanishes when
    the result is healthy leaves the reader to work out whether silence means
    good or means broken.
    """
    metrics = result.metrics
    trades = len(result.trades)
    if trades == 0:
        return (
            "No trades were taken. Every figure below is computed from an equity curve that "
            "never moved, so none of them describes the strategy - only that it found no "
            "setup in this history."
        )

    sharpe = metrics.get("sharpe", 0.0)
    cagr = metrics.get("cagr", 0.0)
    drawdown = abs(metrics.get("max_drawdown", 0.0))
    # A figure that ROUNDS to zero is described as flat rather than printed.
    # Rendering it found "Grew -0.0% a year", which reads as a broken template
    # rather than as a small number, and "gave up 0.0%" for an alpha that was
    # not distinguishable from none.
    negligible = 0.0005
    if abs(cagr) < negligible:
        moved = "was flat"
    else:
        moved = f"{'grew' if cagr > 0 else 'lost'} {abs(cagr):.1%} a year"
    fell = (
        f"worst peak-to-trough fall {drawdown:.1%}"
        if drawdown >= negligible
        else "with no material drawdown"
    )
    parts = [f"{trades} trade(s). It {moved}, {fell}, at a Sharpe of {sharpe:.2f}."]

    alpha = metrics.get("alpha")
    if alpha is not None and abs(alpha) >= negligible:
        parts.append(
            f"Against the benchmark it {'added' if alpha > 0 else 'gave up'} "
            f"{abs(alpha):.1%} a year."
        )

    if sharpe <= 0:
        parts.append("It lost money per unit of risk taken - the strategy did not work here.")
    elif drawdown >= 0.20:
        parts.append(
            f"A {drawdown:.0%} drawdown is the part to weigh: that is what holding it would "
            "have felt like, not the annual figure."
        )

    # The caveat M69 gave the cone and the windows, on the result they are both
    # computed from. Stated as the count this run produced rather than as a
    # standing warning, and it therefore disappears when the strategy trades
    # enough - which is what stops it becoming boilerplate.
    if trades <= _MIN_TRADES_FOR_A_CONE:
        parts.append(
            f"But {trades} trade(s) is too few to conclude anything: these figures describe "
            "that handful of trades, not the strategy."
        )
    return " ".join(parts)


def _walk_forward_headline(result: WalkForwardResult) -> str:
    """The sentence that decides whether the backtest above meant anything.

    Deliberately leads with how many windows were profitable rather than the
    mean Sharpe. A strategy can post a strong average from one exceptional
    window and lose money in every other, and the average is the number that
    hides it.
    """
    windows = result.windows
    if not windows:
        return (
            "No complete windows: the history is shorter than one in-sample plus one "
            "out-of-sample period. Shorten the windows or use a longer history."
        )
    count = len(windows)
    sharpes = [w.out_sample_result.metrics.get("sharpe", 0.0) for w in windows]
    profitable = sum(1 for s in sharpes if s > 0)
    mean = result.metric_stability.get("sharpe_mean", 0.0)
    spread = result.metric_stability.get("sharpe_std", 0.0)

    parts = [
        f"{profitable} of {count} out-of-sample windows profitable.",
        f"Sharpe mean {mean:.2f}, spread {spread:.2f} (min {min(sharpes):.2f}, "
        f"max {max(sharpes):.2f}).",
    ]

    if count < _MIN_INFORMATIVE_WINDOWS:
        parts.append(
            f"Only {count} window(s) - too few to say anything about stability. "
            "Shorten the windows or use a longer history."
        )
    elif profitable <= count / 2:
        parts.append(
            "It failed out of sample as often as it worked: treat the backtest above "
            "as unproven."
        )
    elif spread > abs(mean):
        parts.append(
            "The spread between windows exceeds the average, so the result depends "
            "heavily on which period you look at."
        )
    else:
        parts.append("Reasonably consistent across periods.")

    # The caveat the panel omitted, and the deploy gate is on this screen.
    #
    # Walk-forward slicing MANUFACTURES an entry at each window boundary. For a
    # continuously-held strategy that means the windows are 60-day chunks of one
    # hold rather than N independent tests - and every figure above is computed
    # from them. ROADMAP measured it: swing changes exposure 7 times in 300
    # bars, giving 3 walk-forward trades across 3 windows, and "neither tool
    # says much about swing until it exits".
    #
    # APPENDED rather than substituted, because both facts can be true at once:
    # the windows may be perfectly consistent AND built on too few trades to
    # mean anything.
    #
    # Stated as the COUNT THIS RUN PRODUCED rather than as a standing warning. A
    # disclaimer on every result is scrolled past; a number computed from the
    # run in front of you is not. It therefore self-suppresses when the strategy
    # trades enough, which is what stops it becoming the boilerplate it replaced.
    trades = [len(window.out_sample_result.trades) for window in windows]
    total_trades = sum(trades)
    if total_trades <= count * _MAX_TRADES_FOR_SLICING_CAVEAT:
        per_window = total_trades / count
        parts.append(
            f"But {total_trades} trade(s) across {count} window(s) - "
            f"{per_window:.1f} per window. Slicing manufactures the entry at each "
            "boundary, so for a strategy that holds continuously these are chunks "
            "of one hold rather than independent tests, and the figures above "
            "describe the slicing as much as the strategy."
        )

    return " ".join(parts)
