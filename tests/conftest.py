"""Test-wide isolation of the application's data directory.

Settings.data_dir defaults to "./data", which is the real one the running
application writes to. Once the risk audit trail and the decision journal
started persisting (M20), simply constructing a RiskEngine or an OMS in a test
appended to the operator's own files - a single suite run put 170KB of
synthetic decisions into a directory whose whole purpose is to be a truthful
record of real sessions.

Function-scoped and autouse: no test has to remember to opt in, and a test that
genuinely wants a specific directory still passes data_dir explicitly.
"""

from __future__ import annotations

import os
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
def isolate_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    # All durable state, including exit recovery, belongs to this test alone.
    # Restart tests reuse the directory within one test, never across tests.
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


@pytest.fixture(autouse=True)
def deny_test_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """All tests are offline; vendor doubles must intercept above the socket."""
    import asyncio
    import socket
    import types

    # Windows implements socketpair using a private loopback handshake.
    # Preserve ONLY that stdlib IPC constructor; application sockets remain
    # denied. Asyncio needs it for its internal wake-up pipe, even offline.
    if hasattr(socket.socketpair, "__code__"):
        original_connect = socket.socket.connect

        class IPCSocket(socket.socket):
            connect = original_connect

        pair_globals = dict(socket.socketpair.__globals__)
        pair_globals["socket"] = IPCSocket
        offline_pair = types.FunctionType(
            socket.socketpair.__code__,
            pair_globals,
            argdefs=socket.socketpair.__defaults__,
            closure=socket.socketpair.__closure__,
        )
        monkeypatch.setattr(socket, "socketpair", offline_pair)

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden in tests")

    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for cls in (asyncio.BaseEventLoop, asyncio.SelectorEventLoop):
        for name in ("create_connection", "create_datagram_endpoint", "sock_connect"):
            monkeypatch.setattr(cls, name, denied)
    if hasattr(asyncio, "ProactorEventLoop"):
        monkeypatch.setattr(asyncio.ProactorEventLoop, "sock_connect", denied)
