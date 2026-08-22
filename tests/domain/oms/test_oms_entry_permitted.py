"""The allow-list rule, asked rather than re-derived.

`submit_order` opened with two membership tests. The symbol verdict needs the
same answer WITHOUT proposing anything, and a second copy of a rule is how the
two drift - the defect `minimum_hold_status` was extracted to prevent, and the
one `trading_date` had with one caller out of four (M120).
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate


def _oms(tmp_path, **kwargs) -> OMS:
    """Its own data_dir, per the standing constraint: conftest sets
    QAT_DATA_DIR session-wide and the anomaly store persists there, so one
    declared anomaly would leak a quarantine into every later test.

    `OMS.__init__` takes `broker`, `risk_engine`, and `kill_switch` as
    required positional arguments (see `tests/domain/oms/test_churn_control.py`
    for the same construction) - the brief's `OMS(settings=..., **kwargs)` does
    not match the real signature, so this builds the same minimal trio every
    other OMS test does and forwards everything else through.
    """
    from qat.config import Settings
    from qat.data.broker.mock_broker import MockBroker
    from qat.domain.bus import EventBus
    from qat.domain.risk_engine.engine import RiskEngine
    from qat.domain.risk_engine.kill_switch import KillSwitch

    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=settings)
    broker = MockBroker()
    return OMS(broker, engine, switch, bus=bus, settings=settings, **kwargs)


def test_no_allow_lists_permits_everything(tmp_path):
    oms = _oms(tmp_path)
    assert oms.entry_permitted("BHP.AX") is None


def test_a_symbol_off_the_symbol_allow_list_is_refused(tmp_path):
    oms = _oms(tmp_path, symbol_allow_list={"CBA.AX"})
    reason = oms.entry_permitted("BHP.AX")
    assert reason is not None
    assert "symbol not on the allow list" in reason


def test_a_symbol_off_the_entry_allow_list_is_refused(tmp_path):
    oms = _oms(tmp_path, entry_allow_list={"CBA.AX"})
    reason = oms.entry_permitted("BHP.AX")
    assert reason is not None
    assert "entry allow list" in reason


def test_the_symbol_allow_list_is_reported_first(tmp_path):
    """Order is the rule, not an accident: the symbol allow list governs
    HOLDING as well as entering, so it is the broader refusal and the one
    worth naming."""
    oms = _oms(tmp_path, symbol_allow_list={"CBA.AX"}, entry_allow_list={"CBA.AX"})
    assert "symbol not on the allow list" in (oms.entry_permitted("BHP.AX") or "")


def test_an_empty_entry_allow_list_refuses_everything(tmp_path):
    """An EMPTY set is not the same as None. None permits everything; an empty
    set permits nothing, which is what a cleared machinery-test list means."""
    oms = _oms(tmp_path, entry_allow_list=set())
    assert oms.entry_permitted("BHP.AX") is not None


@pytest.mark.asyncio
async def test_submit_order_reports_exactly_what_the_predicate_says(tmp_path):
    """THE test in this file, and the whole reason for the extraction.

    An earlier draft asserted only that `entry_permitted` returned something -
    which duplicated the test above it and would have passed even if
    `submit_order` stopped calling the predicate entirely. A guard that cannot
    fail for the reason it exists is not a guard.

    So this calls the REAL `submit_order` and asserts the refusal it records is
    the string the predicate produced for the same symbol. If the two
    implementations ever diverge, this is what says so.

    `Order` (src/qat/data/broker/adapter.py) carries no reason of its own - the
    refusal text lives only where `_new_rejected_order` sends it, the decision
    journal - so the journal is what this reads back rather than the brief's
    `order.rejection_reason or order.reason`, neither of which exists on the
    real dataclass.
    """
    from qat.domain.decision_journal import DecisionJournal

    journal = DecisionJournal(str(tmp_path))
    oms = _oms(tmp_path, entry_allow_list={"CBA.AX"}, journal=journal)
    expected = oms.entry_permitted("BHP.AX")
    assert expected is not None, "the fixture must actually be refused"

    candidate = OrderCandidate(
        symbol="BHP.AX",
        side="buy",
        price=41.50,
        atr=0.8,
        win_rate=0.5,
        win_loss_ratio=1.5,
        candidate_returns=pd.Series([0.0]),
    )
    order = await oms.submit_order(
        candidate, equity=1_000_000.0, existing_weights={}, existing_returns={}
    )

    assert order.status == "rejected"
    entries = journal.entries()
    assert entries, "submit_order must record its refusal"
    assert entries[-1]["order_id"] == order.order_id
    assert expected in entries[-1]["reason"]
