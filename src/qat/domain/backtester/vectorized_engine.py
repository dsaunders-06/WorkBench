"""Vectorised backtest engine (spec §G): bars + a target-exposure signal
series -> equity curve, trade list, and the ten-metric panel, with realistic
costs and ATR-based position sizing (paper Appendix A - see sizing.py) and an
optional regime exposure scalar (constant 1.0, i.e. no overlay, until M5's
regime engine supplies a real series).

Position sizing is set once per direction change (the opening trade) and
held until the signal flips direction or drops to zero; a magnitude-only
change within the same direction does not rescale the position - a
documented simplification that keeps trade accounting unambiguous.

Guardrails (spec §G): warns loudly if the resulting Sharpe > ~2 on daily
data, or if both cost components are zero - both are red flags for
overfitting or unrealistic assumptions, not something to silently accept.
"""

from __future__ import annotations

import pandas as pd

from qat.data.features import compute_atr
from qat.domain.backtester.costs import CostModel
from qat.domain.backtester.metrics import compute_metrics_panel
from qat.domain.backtester.results import BacktestResult, Trade
from qat.domain.backtester.sizing import PositionSizer

_SHARPE_WARNING_THRESHOLD = 2.0
_STARTING_EQUITY = 100_000.0
_ATR_WINDOW = 14


class VectorizedBacktester:
    def __init__(
        self,
        cost_model: CostModel,
        sizer: PositionSizer,
        starting_equity: float = _STARTING_EQUITY,
        risk_free_rate: float = 0.0,
    ) -> None:
        self.cost_model = cost_model
        self.sizer = sizer
        self.starting_equity = starting_equity
        self.risk_free_rate = risk_free_rate

    def run(
        self,
        symbol: str,
        bars: pd.DataFrame,
        signal_series: pd.Series,
        benchmark_prices: pd.Series | None = None,
        regime_scalar_series: pd.Series | None = None,
    ) -> BacktestResult:
        bars = bars.reset_index(drop=True)
        atr = compute_atr(bars["high"], bars["low"], bars["close"], window=_ATR_WINDOW)
        regime_scalar = (
            regime_scalar_series.reindex(bars["ts"]).fillna(1.0)
            if regime_scalar_series is not None
            else pd.Series(1.0, index=bars["ts"])
        )

        equity = self.starting_equity
        equity_values: list[float] = []
        trades: list[Trade] = []

        current_position = 0.0  # signed shares
        entry_price = 0.0
        entry_ts = bars["ts"].iloc[0]
        entry_side: str = "buy"

        for i in range(len(bars)):
            ts = bars["ts"].iloc[i]
            price = float(bars["close"].iloc[i])
            raw_exposure = float(signal_series.iloc[i]) * float(regime_scalar.iloc[i])
            target_exposure = max(-1.0, min(1.0, raw_exposure))

            bar_atr = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else 0.0
            desired_direction = 1 if target_exposure > 0 else (-1 if target_exposure < 0 else 0)
            current_direction = 1 if current_position > 0 else (-1 if current_position < 0 else 0)

            if desired_direction != current_direction:
                if current_position != 0:
                    pnl = (price - entry_price) * current_position
                    equity += pnl
                    equity -= self.cost_model.apply(abs(current_position) * price)
                    trades.append(
                        Trade(
                            symbol=symbol,
                            side=entry_side,  # type: ignore[arg-type]
                            entry_ts=entry_ts,
                            exit_ts=ts,
                            entry_price=entry_price,
                            exit_price=price,
                            quantity=abs(current_position),
                            pnl=pnl,
                        )
                    )
                    current_position = 0.0

                if desired_direction != 0:
                    shares = self.sizer.size(equity, price, bar_atr) * abs(target_exposure)
                    if shares > 0:
                        equity -= self.cost_model.apply(shares * price)
                        current_position = shares * desired_direction
                        entry_price = price
                        entry_ts = ts
                        entry_side = "buy" if desired_direction > 0 else "sell"

            unrealised = (price - entry_price) * current_position if current_position != 0 else 0.0
            equity_values.append(equity + unrealised)

        if current_position != 0:
            final_price = float(bars["close"].iloc[-1])
            pnl = (final_price - entry_price) * current_position
            equity += pnl
            equity -= self.cost_model.apply(abs(current_position) * final_price)
            trades.append(
                Trade(
                    symbol=symbol,
                    side=entry_side,  # type: ignore[arg-type]
                    entry_ts=entry_ts,
                    exit_ts=bars["ts"].iloc[-1],
                    entry_price=entry_price,
                    exit_price=final_price,
                    quantity=abs(current_position),
                    pnl=pnl,
                )
            )
            equity_values[-1] = equity

        equity_curve = pd.Series(equity_values, index=pd.DatetimeIndex(bars["ts"]), name="equity")
        metrics = compute_metrics_panel(equity_curve, trades, benchmark_prices, self.risk_free_rate)

        warnings: list[str] = []
        if self.cost_model.total_bps == 0:
            warnings.append(
                "Zero-cost backtest: commission and slippage are both 0 bps - unrealistic; "
                "results likely overstate performance."
            )
        sharpe = metrics.get("sharpe", 0.0)
        if sharpe > _SHARPE_WARNING_THRESHOLD:
            warnings.append(
                f"Sharpe ratio {sharpe:.2f} exceeds {_SHARPE_WARNING_THRESHOLD} on daily data - "
                "a common sign of overfitting or unrealistic assumptions."
            )

        return BacktestResult(
            equity_curve=equity_curve, trades=trades, metrics=metrics, warnings=warnings
        )
