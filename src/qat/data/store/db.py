"""Storage engine factory. SQLite (local dev default) or TimescaleDB."""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

from qat.config import Settings


def get_engine(settings: Settings) -> Engine:
    connect_args = {"check_same_thread": False} if settings.storage_backend == "sqlite" else {}
    return create_engine(settings.database_url, connect_args=connect_args)


def create_db_and_tables(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
