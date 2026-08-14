"""A production object wired but never started is a rail holding its default.

Measured 13 August: `ReplaySession` started four engines and omitted the risk
engine, whose `start` is the only place it subscribes to `RegimeEvent`. The
exposure scalar held 1.0 for the whole G1 window while live varied
0.4/0.5/0.7/1.0, so the harness sized up to 2.5x larger than the book it was
being compared against - and SPY on 31 July crossed the cost-to-risk limit on
that difference alone.

NOTHING ERRORED. The rail simply held its default, and the default is the
permissive value. That is why this needs a test rather than vigilance.

A COMPROMISE, stated rather than glossed: the spec asked for this to be derived
from the live runtime's own engine-registration list. It is not. `ReplaySession`
deliberately holds a different set - no kill-switch engine, no reconciliation
monitor, no session controller - so the runtime's list is the wrong oracle for
it. The list below is hand-written, which is the weaker form. It still converts
"somebody must notice" into "a test fails", which is the gap that let the risk
engine go unstarted; a genuinely derived check needs a shared registry that does
not exist yet.
"""

from __future__ import annotations

import inspect

from qat.domain.backtester.replay_session import ReplaySession

# Every engine the session constructs and must drive. `regime_engine` is here
# too: it is started conditionally, on `start_regime`, which is how the regime
# gate is ablated - but the CALL must still be present, or ablation would be
# indistinguishable from the omission this test exists to catch.
_MUST_START = (
    "self.oms.risk_engine.start",
    "self.ledger.start",
    "self.regime_engine.start",
    "self.engine.start",
    "self.bridge.start",
    "self.executor.start",
)


def test_every_engine_the_session_holds_is_started():
    source = inspect.getsource(ReplaySession.run)

    missing = [name for name in _MUST_START if f"await {name}()" not in source]

    assert not missing, (
        f"ReplaySession.run does not start: {', '.join(missing)}. An engine that is "
        "constructed and never started holds its defaults silently - the risk engine did "
        "exactly that, and the regime rail was inert for the whole G1 window with nothing "
        "erroring."
    )


def test_every_started_engine_is_also_stopped():
    """A session that leaves subscribers on a bus it has finished with leaks
    them into whatever runs next - and an ablation runs two sessions back to
    back in one process."""
    source = inspect.getsource(ReplaySession.run)

    missing = [
        name.replace(".start", ".stop")
        for name in _MUST_START
        if f"await {name.replace('.start', '.stop')}()" not in source
    ]

    assert not missing, f"ReplaySession.run does not stop: {', '.join(missing)}"


def test_pending_orders_are_retried_every_simulated_day():
    """The executor's own retry loop is wall-clock driven and inert in a replay,
    so the session has to drive it. Without this a single blocked day loses the
    order for good: a time stop fired on Memorial Day 2024, the gate correctly
    refused to trade a US holiday, and nothing asked again."""
    source = inspect.getsource(ReplaySession.run)

    assert "await self.executor.retry_pending()" in source
    assert source.index("self.broker.advance()") < source.index("retry_pending"), (
        "the retry must follow the advance, or it reconsiders the order against the same "
        "day that just refused it"
    )


def test_the_absorb_sweep_runs_after_the_advance():
    """Order matters and is easy to lose in a refactor. `advance` is what fires
    stops and targets, so sweeping before it asks about a day on which nothing
    has happened yet - and the sweep is the only thing that turns a fired stop
    into a ClosedTrade."""
    source = inspect.getsource(ReplaySession.run)

    assert "await self.oms.absorb_broker_fills()" in source
    assert source.index("self.broker.advance()") < source.index("absorb_broker_fills")
