from __future__ import annotations

import pandas as pd

from qat.data.store.parquet import (
    read_backtest_artifact,
    read_features,
    write_backtest_artifact,
    write_features,
)


def test_write_and_read_features_round_trip(tmp_path):
    df = pd.DataFrame({"return_1d": [0.01, -0.02], "atr": [1.5, 1.6]})

    write_features(tmp_path, "AAPL", "2024-01-01", df)
    result = read_features(tmp_path, "AAPL", "2024-01-01")

    pd.testing.assert_frame_equal(result, df)


def test_write_and_read_backtest_artifact_round_trip(tmp_path):
    df = pd.DataFrame({"equity": [100.0, 101.5, 99.8]})

    write_backtest_artifact(tmp_path, "run-123", df)
    result = read_backtest_artifact(tmp_path, "run-123")

    pd.testing.assert_frame_equal(result, df)
