"""Persistence models.

Table naming loosely follows the reference schema in ShareTrader's
db/database.py (stocks/historical_prices/orders/portfolio), adapted for
SQLModel and the timestamp discipline this project requires. Extended by
M2 (bars/ticks/features) and M6 (orders/positions).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Bar(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    ts: datetime = Field(index=True)
    open: float
    high: float
    low: float
    close: float
    volume: float


class Tick(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    ts: datetime = Field(index=True)
    price: float
    size: float


class MacroSeries(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    series: str = Field(index=True)
    ts: datetime = Field(index=True)
    value: float
