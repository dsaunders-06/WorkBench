"""Per-strategy edge estimates from realised trades (M35).

`SignalToOrderBridge` passed `win_rate=0.55` and `win_loss_ratio=1.5` into
Kelly sizing as fixed constants, and the module docstring called them "clearly
documented placeholders, not real edge estimates". Every position size this
system has ever taken traces back to those two invented numbers.

This closes the loop: what a strategy actually achieved decides how much the
next trade risks.

**It stays on the defaults until the sample supports otherwise, and that is
the important part.** Kelly is violently sensitive to win rate - at a 1.5
win/loss ratio, moving win rate from 0.55 to 0.75 roughly triples the fraction
- so a strategy that opened with four winners would size up hard on noise.
The estimate switches over only at `edge_min_trades`, and even then is clamped
into a band a real equity strategy can plausibly occupy.

The clamps are not decoration. They are the difference between "measure the
edge" and "let a lucky fortnight set the risk".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from qat.config import Settings
from qat.domain.performance.metrics import compute_stats
from qat.domain.performance.trades import ClosedTrade

logger = logging.getLogger(__name__)

# A measured win rate outside this band is far likelier to be a small-sample
# artefact than a real edge, and Kelly reacts to the difference violently.
_MIN_WIN_RATE = 0.25
_MAX_WIN_RATE = 0.75
# Below 1:1 the sizer should be shrinking, not reasoning about ratios; above
# 4:1 on a handful of trades is one outsized winner, not a payoff profile.
_MIN_WIN_LOSS_RATIO = 0.5
_MAX_WIN_LOSS_RATIO = 4.0


class ClosedTradeSource(Protocol):
    def closed_trades(self, strategy: str | None = None) -> list[ClosedTrade]: ...


@dataclass(frozen=True, slots=True)
class Edge:
    win_rate: float
    win_loss_ratio: float
    source: Literal["measured", "default"]
    trade_count: int

    def describe(self) -> str:
        if self.source == "default":
            return (
                f"default edge ({self.win_rate:.0%} win rate, {self.win_loss_ratio:.2f} "
                f"win/loss) - {self.trade_count} closed trades, not enough to measure"
            )
        return (
            f"measured edge over {self.trade_count} closed trades: "
            f"{self.win_rate:.0%} win rate, {self.win_loss_ratio:.2f} win/loss"
        )


class EdgeEstimator:
    """What a strategy has actually achieved, or the default until it has."""

    def __init__(
        self,
        ledger: ClosedTradeSource | None,
        settings: Settings | None = None,
        default_win_rate: float = 0.55,
        default_win_loss_ratio: float = 1.5,
    ) -> None:
        self.ledger = ledger
        self.settings = settings or Settings()
        self.default_win_rate = default_win_rate
        self.default_win_loss_ratio = default_win_loss_ratio
        self._last_source: dict[str, str] = {}

    def estimate(self, strategy: str | None) -> Edge:
        default = Edge(
            win_rate=self.default_win_rate,
            win_loss_ratio=self.default_win_loss_ratio,
            source="default",
            trade_count=0,
        )
        if self.ledger is None or strategy is None:
            return default

        trades = self.ledger.closed_trades(strategy)
        if len(trades) < self.settings.edge_min_trades:
            return Edge(
                win_rate=self.default_win_rate,
                win_loss_ratio=self.default_win_loss_ratio,
                source="default",
                trade_count=len(trades),
            )

        stats = compute_stats(trades)
        if stats.win_rate is None or stats.average_win is None or stats.average_loss is None:
            return default
        average_loss = abs(stats.average_loss)
        if average_loss <= 0:
            # No losing trade yet. That is not a payoff ratio, it is a sample
            # too kind to learn from, and dividing by it would be worse.
            return Edge(
                win_rate=self.default_win_rate,
                win_loss_ratio=self.default_win_loss_ratio,
                source="default",
                trade_count=len(trades),
            )

        edge = Edge(
            win_rate=_clamp(stats.win_rate, _MIN_WIN_RATE, _MAX_WIN_RATE),
            win_loss_ratio=_clamp(
                stats.average_win / average_loss, _MIN_WIN_LOSS_RATIO, _MAX_WIN_LOSS_RATIO
            ),
            source="measured",
            trade_count=len(trades),
        )
        # Logged on the transition only. This changes every position size the
        # strategy takes from here on, and a line that appears once is the news
        # where one repeated per signal is wallpaper.
        if self._last_source.get(strategy) != "measured":
            logger.warning(
                "SIZING NOW USES MEASURED EDGE for %s - %s. Position sizes from here are "
                "set by what this strategy actually achieved, not by the defaults.",
                strategy,
                edge.describe(),
            )
        self._last_source[strategy] = "measured"
        return edge


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
