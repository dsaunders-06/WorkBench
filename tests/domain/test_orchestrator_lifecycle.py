from __future__ import annotations

import pytest

from qat.domain.bus import EventBus
from qat.domain.orchestrator import Orchestrator


class RecordingEngine:
    name = "recording-engine"

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_start_all_with_no_engines_is_a_noop():
    orchestrator = Orchestrator(EventBus())
    await orchestrator.start_all()
    assert orchestrator.is_running


@pytest.mark.asyncio
async def test_start_all_starts_registered_engines():
    orchestrator = Orchestrator(EventBus())
    engine = RecordingEngine()
    orchestrator.register(engine)

    await orchestrator.start_all()

    assert engine.started
    assert orchestrator.is_running


@pytest.mark.asyncio
async def test_stop_all_stops_registered_engines():
    orchestrator = Orchestrator(EventBus())
    engine = RecordingEngine()
    orchestrator.register(engine)

    await orchestrator.start_all()
    await orchestrator.stop_all()

    assert engine.stopped
    assert not orchestrator.is_running


@pytest.mark.asyncio
async def test_start_all_is_idempotent():
    orchestrator = Orchestrator(EventBus())
    engine = RecordingEngine()
    orchestrator.register(engine)

    await orchestrator.start_all()
    engine.started = False  # reset to detect a second start() call
    await orchestrator.start_all()

    assert not engine.started


@pytest.mark.asyncio
async def test_stop_all_before_start_is_a_noop():
    orchestrator = Orchestrator(EventBus())
    engine = RecordingEngine()
    orchestrator.register(engine)

    await orchestrator.stop_all()

    assert not engine.stopped
