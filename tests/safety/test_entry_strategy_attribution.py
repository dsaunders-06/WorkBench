"""Attribution must be STORED, not inferred from a config value (M86).

`open_position_entries.json` on the live book carries `"strategy": null` for
nine of the ten held positions. M49 added the field on 5 August; those nine
records were written on 31 July and 4 August, before it existed, and nothing
backfills them - `_on_fill` uses `setdefault` and both price-correcting writers
use `replace(entry, price=...)`, which preserves whatever strategy is there.

The held-over question was whether that means those positions close
unattributed. Measured: it does not, TODAY. `restore_open_lots` passes
`entry.strategy or self._sole_deployed_strategy()`, and with `swing` the only
deployed strategy the fallback credits swing to all of them. CVS proves it end
to end - it appears in `open_position_entries.json.bak-pre-m33b` with no
strategy field at all and closed as `swing`.

The defect is what that sentence depends on. `_sole_deployed_strategy` returns
None the moment a SECOND strategy is deployed, deliberately, so it never
fabricates an attribution. So attribution for nine of ten held positions is
inferred at restore time from a mutable config value, and **activating M84 or
M85 retroactively unattributes every one of them** - `closed_trades(strategy=)`
matches exactly, so a None counts towards no promotion gate. With a ten-day minimum
hold those nine will still be held when activation is considered.

That the nine are swing is recorded fact, not a guess: `decision_journal.csv`
carries `strategy=swing` for each, with `signed_off` transmit timestamps
matching `opened_at` to the second.

So the record heals itself, at the same point in startup where M65 heals the
price, and the resolution is written down while it can still be resolved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

# The live record's shape, reduced to three positions: two written before M49
# and so carrying null, one written after it and so carrying swing.
_LIVE_SHAPE = {
    "JNJ": {
        "opened_at": "2026-08-01T01:08:21+10:00",
        "price": 256.43,
        "stop_price": 240.5880357142857,
        "target_price": 288.11,
        "strategy": None,
    },
    "AMD": {
        "opened_at": "2026-08-04T14:01:25.595076+00:00",
        "price": 503.16,
        "stop_price": 405.54928571428576,
        "target_price": 698.3814285714286,
        "strategy": None,
    },
    "VRTX": {
        "opened_at": "2026-08-05T14:16:09.183962+00:00",
        "price": 487.2,
        "stop_price": 456.2678571428571,
        "target_price": 549.0642857142857,
        "strategy": "swing",
    },
}


class _Broker:
    """Holds exactly what the entry record names, at the recorded price."""

    def __init__(self, record: dict[str, dict]) -> None:
        self._record = record

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=10.0, avg_price=float(row["price"]))
            for symbol, row in self._record.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        return {}

    async def recent_fills(self, since, symbols=None):  # noqa: ANN001, ANN201
        return []


def _write_record(data_dir: Path, record: dict[str, dict]) -> Path:
    path = data_dir / "open_position_entries.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def _bridge(data_dir: Path, record: dict[str, dict], deployed: str):
    """Its OWN data_dir, per the standing rule - the anomaly store persists
    there and one declared anomaly would leak a quarantine into later tests."""
    settings = Settings(_env_file=None, data_dir=str(data_dir), deployed_strategies=deployed)
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _Broker(record),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    ledger = TradeLedger(bus, data_dir, settings=settings)
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings, trade_ledger=ledger)
    return bridge, ledger


# --- the fallback itself, which had no test at all ----------------------------


def test_the_fallback_resolves_the_only_deployed_strategy(tmp_path):
    _write_record(tmp_path, _LIVE_SHAPE)
    bridge, _ = _bridge(tmp_path, _LIVE_SHAPE, "swing")

    assert bridge._sole_deployed_strategy() == "swing"


def test_the_fallback_refuses_to_guess_between_two(tmp_path):
    """Deliberate: with two running, which opened a given position is genuinely
    unknown, and guessing would put a fabricated attribution into a per-strategy
    promotion decision."""
    _write_record(tmp_path, _LIVE_SHAPE)
    bridge, _ = _bridge(tmp_path, _LIVE_SHAPE, "swing,price_action")

    assert bridge._sole_deployed_strategy() is None


# --- what the null record costs, before and after the heal --------------------


@pytest.mark.asyncio
async def test_a_null_record_restores_attributed_while_swing_is_alone(tmp_path):
    """Today's live state. Nothing is being lost right now, and this is why."""
    _write_record(tmp_path, _LIVE_SHAPE)
    bridge, ledger = _bridge(tmp_path, _LIVE_SHAPE, "swing")

    await bridge.restore_open_lots()

    assert ledger.open_lots("JNJ")[0].strategy == "swing"
    assert ledger.open_lots("AMD")[0].strategy == "swing"


@pytest.mark.asyncio
async def test_the_heal_survives_a_second_strategy_being_deployed(tmp_path):
    """The whole point. Once the resolution is written down, activating M84 or
    M85 cannot take it away - the record answers, so the fallback is not asked."""
    _write_record(tmp_path, _LIVE_SHAPE)
    healed, _ = _bridge(tmp_path, _LIVE_SHAPE, "swing")
    await healed.reconcile_entry_strategies()

    # A later launch, with a second strategy now deployed, reading the record
    # the first one left behind.
    later, ledger = _bridge(tmp_path, _LIVE_SHAPE, "swing,price_action")
    await later.restore_open_lots()

    assert ledger.open_lots("JNJ")[0].strategy == "swing"
    assert ledger.open_lots("AMD")[0].strategy == "swing"


@pytest.mark.asyncio
async def test_the_closed_trade_counts_towards_the_gate_after_the_heal(tmp_path):
    """End to end, because an attributed lot is not the deliverable - a closed
    trade the promotion gate can count is."""
    _write_record(tmp_path, _LIVE_SHAPE)
    healed, _ = _bridge(tmp_path, _LIVE_SHAPE, "swing")
    await healed.reconcile_entry_strategies()

    later, ledger = _bridge(tmp_path, _LIVE_SHAPE, "swing,price_action")
    await later.restore_open_lots()
    await ledger._on_fill(
        OrderFilledEvent(
            order_id="exit-jnj",
            symbol="JNJ",
            side="sell",
            quantity=10.0,
            price=270.0,
            operator="broker (protective order)",
            exit_reason="target",
            ts=datetime(2026, 8, 12, tzinfo=UTC),
        )
    )

    assert ledger.strategies() == ["swing"]
    assert len(ledger.closed_trades(strategy="swing")) == 1


# --- what the heal writes, and what it refuses to write -----------------------


@pytest.mark.asyncio
async def test_the_resolved_strategy_reaches_the_file(tmp_path):
    """Written on the spot rather than held in memory: this file exists
    precisely for the restart that was not planned."""
    path = _write_record(tmp_path, _LIVE_SHAPE)
    bridge, _ = _bridge(tmp_path, _LIVE_SHAPE, "swing")

    healed = await bridge.reconcile_entry_strategies()

    assert sorted(healed) == ["AMD", "JNJ"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["JNJ"]["strategy"] == "swing"
    assert on_disk["AMD"]["strategy"] == "swing"


@pytest.mark.asyncio
async def test_it_does_not_touch_a_record_that_already_names_one(tmp_path):
    """VRTX was opened after M49 and carries its own attribution. A heal that
    overwrote it would be rewriting history rather than recovering it."""
    path = _write_record(tmp_path, _LIVE_SHAPE)
    bridge, _ = _bridge(tmp_path, _LIVE_SHAPE, "price_action")

    healed = await bridge.reconcile_entry_strategies()

    assert "VRTX" not in healed
    assert json.loads(path.read_text(encoding="utf-8"))["VRTX"]["strategy"] == "swing"


@pytest.mark.asyncio
async def test_it_refuses_to_guess_and_says_which_positions_are_exposed(tmp_path, caplog):
    """The state where attribution silently vanishes. It must not be silent -
    naming the symbols is what makes activating a second strategy a visible
    cost rather than a discovered one."""
    path = _write_record(tmp_path, _LIVE_SHAPE)
    bridge, _ = _bridge(tmp_path, _LIVE_SHAPE, "swing,price_action")

    with caplog.at_level("WARNING"):
        healed = await bridge.reconcile_entry_strategies()

    assert healed == []
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["JNJ"]["strategy"] is None, "guessed an attribution it could not know"
    assert on_disk["AMD"]["strategy"] is None

    warned = [r.getMessage() for r in caplog.records if "AMD" in r.getMessage()]
    assert warned, "the exposure was not reported at all"
    assert "JNJ" in warned[0]
    assert "VRTX" not in warned[0], "VRTX carries its own attribution and is not exposed"


@pytest.mark.asyncio
async def test_a_missing_record_is_not_an_error(tmp_path):
    """A first run, or a machine whose previous session opened nothing."""
    bridge, _ = _bridge(tmp_path, {}, "swing")

    assert await bridge.reconcile_entry_strategies() == []


@pytest.mark.asyncio
async def test_the_heal_runs_before_lots_are_restored(tmp_path):
    """Ordering, for the same reason M65's price reconciliation runs before it:
    the lot is built from the record, so a record healed afterwards heals
    nothing that matters until the next launch."""
    _write_record(tmp_path, _LIVE_SHAPE)
    bridge, ledger = _bridge(tmp_path, _LIVE_SHAPE, "swing")

    order: list[str] = []
    original_heal = bridge.reconcile_entry_strategies
    original_restore = bridge.restore_open_lots

    async def _heal():
        order.append("heal")
        return await original_heal()

    async def _restore(snapshot=None):
        order.append("restore")
        return await original_restore(snapshot)

    bridge.reconcile_entry_strategies = _heal  # type: ignore[method-assign]
    bridge.restore_open_lots = _restore  # type: ignore[method-assign]
    await bridge.start()
    if bridge._sweep_task is not None:
        bridge._sweep_task.cancel()
    if bridge._warm_task is not None:
        bridge._warm_task.cancel()

    assert order[: order.index("restore") + 1] == ["heal", "restore"]
    assert ledger.open_lots("JNJ")[0].strategy == "swing"
