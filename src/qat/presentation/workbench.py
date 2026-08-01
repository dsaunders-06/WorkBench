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

from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.backtester.costs import CostModel
from qat.domain.backtester.monte_carlo import run_monte_carlo
from qat.domain.backtester.results import BacktestResult, WalkForwardResult
from qat.domain.backtester.signal_adapter import generate_signal_series
from qat.domain.backtester.sizing import FixedFractionalSizer
from qat.domain.backtester.vectorized_engine import VectorizedBacktester
from qat.domain.backtester.walk_forward import run_walk_forward
from qat.presentation.runtime import Runtime
from qat.presentation.widgets import KpiTile

logger = logging.getLogger(__name__)

_PERCENT_METRICS = {"cagr", "volatility", "max_drawdown", "win_rate", "var_95"}
_WF_COLUMNS = ("From", "To", "CAGR", "Sharpe", "Max DD", "Trades")
# Below this many windows the spread of a metric across them is arithmetic
# rather than evidence, and saying so beats printing a confident number.
_MIN_INFORMATIVE_WINDOWS = 3
_METRICS_PER_ROW = 5


class WorkbenchScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._last_result: BacktestResult | None = None

        layout = QVBoxLayout(self)

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
        layout.addLayout(controls)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #d9534f;")
        layout.addWidget(self.status_label)

        self.equity_plot = pg.PlotWidget(title="Equity vs Benchmark")
        self.equity_curve_item = self.equity_plot.plot(pen="y", name="strategy")
        self.benchmark_curve_item = self.equity_plot.plot(pen="c", name="benchmark")
        layout.addWidget(self.equity_plot)

        self.metrics_grid = QGridLayout()
        layout.addLayout(self.metrics_grid)
        self._metric_tiles: dict[str, KpiTile] = {}

        self.mc_plot = pg.PlotWidget(title="Monte Carlo Outcome Cone")
        self.mc_p5_item = self.mc_plot.plot(pen="r", name="p5")
        self.mc_p50_item = self.mc_plot.plot(pen="y", name="p50")
        self.mc_p95_item = self.mc_plot.plot(pen="g", name="p95")
        layout.addWidget(self.mc_plot)

        layout.addWidget(self._build_walk_forward_group())

        layout.addWidget(QLabel("AI Robustness Note"))
        self.ai_note_label = QLabel("(run a backtest to get an AI note)")
        self.ai_note_label.setWordWrap(True)
        layout.addWidget(self.ai_note_label)

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
                        QColor("#1b5e20") if metrics.get("sharpe", 0.0) > 0 else QColor("#b71c1c")
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
            self._render_monte_carlo(mc_result.paths)

            # The AI note is commentary on a backtest that already succeeded -
            # a failing/misconfigured LLM must not discard the results above,
            # but it must be visible rather than silently doing nothing.
            try:
                await self._render_ai_note(symbol, strategy.name, result, signal_series)
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
            self._metric_tiles[name] = tile
            self.metrics_grid.addWidget(tile, index // _METRICS_PER_ROW, index % _METRICS_PER_ROW)

        self.status_label.setText("  ".join(result.warnings))

    def _render_monte_carlo(self, paths: pd.DataFrame) -> None:
        quantiles = paths.quantile([0.05, 0.50, 0.95], axis=1)
        self.mc_p5_item.setData(quantiles.loc[0.05].to_numpy())
        self.mc_p50_item.setData(quantiles.loc[0.50].to_numpy())
        self.mc_p95_item.setData(quantiles.loc[0.95].to_numpy())

    async def _render_ai_note(
        self, symbol: str, strategy_name: str, result: BacktestResult, signal_series: pd.Series
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
        )
        recommendation = await self.runtime.ai_service.get_regime_narrative(context)
        flags = ", ".join(recommendation.risk_flags) if recommendation.risk_flags else "none"
        confidence_pct = f"{recommendation.confidence:.0%}"
        self.ai_note_label.setText(
            f"[{recommendation.recommendation.upper()}, confidence={confidence_pct}] "
            f"{recommendation.rationale} (risk flags: {flags})"
        )


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

    return " ".join(parts)
