"""Parquet persistence for features and backtest artefacts (spec §D/§17.1).

Retaining features/backtests as Parquet is what makes any backtest
regenerable deterministically from retained raw data (spec's reproducibility
requirement) - this module is intentionally just read/write, no business logic.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def features_path(data_dir: Path, symbol: str, as_of_date: str) -> Path:
    return Path(data_dir) / "features" / symbol / f"{as_of_date}.parquet"


def write_features(data_dir: Path, symbol: str, as_of_date: str, df: pd.DataFrame) -> Path:
    path = features_path(data_dir, symbol, as_of_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_features(data_dir: Path, symbol: str, as_of_date: str) -> pd.DataFrame:
    return pd.read_parquet(features_path(data_dir, symbol, as_of_date))


def backtest_artifact_path(data_dir: Path, run_id: str) -> Path:
    return Path(data_dir) / "backtests" / f"{run_id}.parquet"


def write_backtest_artifact(data_dir: Path, run_id: str, df: pd.DataFrame) -> Path:
    path = backtest_artifact_path(data_dir, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_backtest_artifact(data_dir: Path, run_id: str) -> pd.DataFrame:
    return pd.read_parquet(backtest_artifact_path(data_dir, run_id))
