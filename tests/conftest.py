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
import pathlib
from collections.abc import Iterator

import pytest


@pytest.fixture
def advisory_runtime(tmp_path):
    """A runtime with only what the advisory builder reads.

    Deliberately not a real Runtime: the builder's contract is "every path
    degrades to nothing known", and a stub is how that gets exercised without
    a broker, a feed or a vendor.
    """
    from qat.config import Settings

    class _Bridge:
        earnings_calendar = None

    class _Runtime:
        def __init__(self):
            self.news_source = None
            self.settings = Settings(_env_file=None, data_dir=str(tmp_path))
            self.signal_bridge = _Bridge()

    return _Runtime()


@pytest.fixture(autouse=True)
def clear_persisted_halt() -> None:
    """Remove any persisted kill-switch state before each test (item 32).

    The switch now survives a restart, which is the point of item 32 - a halt
    that evaporates on the next launch is not a halt. But `isolate_data_dir`
    above is SESSION scoped, so every test shares one data directory, and
    without this a test that trips the switch halts every test that runs after
    it. Observed exactly that: three regime-banner tests and a Risk Console
    test began failing with "EXECUTION HALTED - KILL-SWITCH: Manual trigger by
    operator", a trip none of them made.

    Function scoped and autouse, so no test has to remember. Deleting the file
    rather than resetting a switch object, because each test builds its own.
    """
    state = pathlib.Path(os.environ["QAT_DATA_DIR"]) / "kill_switch.json"
    state.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def isolate_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    # An environment variable rather than a monkeypatched default, because
    # pydantic-settings reads the environment even when _env_file is None -
    # which is how most tests here build their Settings.
    #
    # QAT_HOME as well since M22: config and data now resolve to a per-user
    # directory, and without this the suite would read and write the operator's
    # real settings and records rather than the repository's.
    home = tmp_path_factory.mktemp("qat-home")
    overrides = {"QAT_HOME": str(home), "QAT_DATA_DIR": str(tmp_path_factory.mktemp("qat-data"))}
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
