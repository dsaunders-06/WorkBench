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
from datetime import UTC, datetime, timedelta

import pandas as pd
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qat.data.market_data import SyntheticMarketDataSource
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.backtester.costs import CostModel
from qat.domain.backtester.monte_carlo import run_monte_carlo
from qat.domain.backtester.results import BacktestResult
from qat.domain.backtester.signal_adapter import generate_signal_series
from qat.domain.backtester.sizing import FixedFractionalSizer
from qat.domain.backtester.vectorized_engine import VectorizedBacktester
from qat.presentation.runtime import Runtime
from qat.presentation.widgets import KpiTile

_N_BACKTEST_BARS = 300
_PERCENT_METRICS = {"cagr", "volatility", "max_drawdown", "win_rate", "var_95"}
_METRICS_PER_ROW = 5


def _seed_for_symbol(symbol: str) -> int:
    return sum(ord(char) for char in symbol) + 1


async def _generate_daily_bars(symbol: str, n_bars: int = _N_BACKTEST_BARS) -> pd.DataFrame:
    source = SyntheticMarketDataSource(seed=_seed_for_symbol(symbol), interval_seconds=0.0)
    start = datetime.now(UTC) - timedelta(days=n_bars)
    rows: list[dict[str, object]] = []
    async for tick in source.stream_ticks([symbol]):
        ts = start + timedelta(days=len(rows))
        rows.append(
            {
                "ts": ts,
                "open": tick.price,
                "high": tick.price,
                "low": tick.price,
                "close": tick.price,
                "volume": tick.volume,
            }
        )
        if len(rows) >= n_bars:
            break
    return pd.DataFrame(rows)


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

        layout.addWidget(QLabel("AI Robustness Note"))
        self.ai_note_label = QLabel("(run a backtest to get an AI note)")
        self.ai_note_label.setWordWrap(True)
        layout.addWidget(self.ai_note_label)

    def _on_run_clicked(self) -> None:
        asyncio.ensure_future(self._run_backtest())

    def _on_deploy_clicked(self) -> None:
        strategy_name = self.strategy_picker.currentText()
        strategy = next(
            (s for s in self.runtime.available_strategies if s.name == strategy_name), None
        )
        if strategy is None:
            return
        if strategy not in self.runtime.strategy_engine.strategies:
            self.runtime.strategy_engine.strategies.append(strategy)
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

            bars = await _generate_daily_bars(symbol)
            benchmark_symbol = self.runtime.watchlist[0]
            benchmark_bars = (
                bars if symbol == benchmark_symbol else await _generate_daily_bars(benchmark_symbol)
            )
            benchmark_prices = benchmark_bars.set_index("ts")["close"]

            fundamentals = await self.runtime.strategy_engine.fundamentals_source.get_fundamentals(
                symbol
            )
            signal_series = generate_signal_series(strategy, symbol, bars, fundamentals)

            backtester = VectorizedBacktester(
                CostModel(), FixedFractionalSizer(settings=self.runtime.settings)
            )
            result = backtester.run(symbol, bars, signal_series, benchmark_prices=benchmark_prices)
            self._last_result = result

            self._render_result(result, benchmark_prices, backtester.starting_equity)

            mc_result = run_monte_carlo(result.trades, starting_equity=backtester.starting_equity)
            self._render_monte_carlo(mc_result.paths)

            await self._render_ai_note(symbol, strategy.name, result, signal_series)

            self.deploy_button.setText("Deploy to Paper")
            self.deploy_button.setEnabled(strategy not in self.runtime.strategy_engine.strategies)
            if strategy in self.runtime.strategy_engine.strategies:
                self.deploy_button.setText(f"Deployed: {strategy_name} ✓")
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
