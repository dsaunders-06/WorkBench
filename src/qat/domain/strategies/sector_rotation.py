"""Sector Rotation: rank sectors by average trailing return, favour symbols
in the top-ranked sector(s) that are also individually trending (paper §4.14).

Suitable regimes: Recovery - paper-explicit ("cyclicals via sector rotation").
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class SectorRotationStrategy:
    name = "sector_rotation"

    def __init__(self, top_sectors: int = 2) -> None:
        self.top_sectors = top_sectors

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.RECOVERY}

    def params(self) -> dict[str, Any]:
        return {"top_sectors": self.top_sectors}

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        sector_returns: dict[str, list[float]] = {}
        for context in snapshot.universe.values():
            ret = context.technical.get("return_1d")
            if ret is None:
                continue
            sector_returns.setdefault(context.fundamentals.sector, []).append(ret)
        if not sector_returns:
            return []

        sector_avg = {sector: sum(rets) / len(rets) for sector, rets in sector_returns.items()}
        ranked_sectors = sorted(sector_avg, key=lambda s: sector_avg[s], reverse=True)
        top = set(ranked_sectors[: self.top_sectors])

        own_sector = snapshot.context.fundamentals.sector
        own_trend = snapshot.context.technical.get("trend_pct_above_sma", 0.0)
        if own_sector not in top or own_trend <= 0:
            return []

        conviction = min(1.0, max(0.0, sector_avg[own_sector] * 20))
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"sector": own_sector, "sector_avg_return": sector_avg[own_sector]},
                ts=snapshot.as_of,
            )
        ]
