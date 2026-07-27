"""Test-wide isolation of the application's data directory.

Settings.data_dir defaults to "./data", which is the real one the running
application writes to. Once the risk audit trail and the decision journal
started persisting (M20), simply constructing a RiskEngine or an OMS in a test
appended to the operator's own files - a single suite run put 170KB of
synthetic decisions into a directory whose whole purpose is to be a truthful
record of real sessions.

Session-scoped and autouse: no test has to remember to opt in, and a test that
genuinely wants a specific directory still passes data_dir explicitly.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolate_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    # An environment variable rather than a monkeypatched default, because
    # pydantic-settings reads the environment even when _env_file is None -
    # which is how most tests here build their Settings.
    previous = os.environ.get("QAT_DATA_DIR")
    os.environ["QAT_DATA_DIR"] = str(tmp_path_factory.mktemp("qat-data"))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("QAT_DATA_DIR", None)
        else:
            os.environ["QAT_DATA_DIR"] = previous
