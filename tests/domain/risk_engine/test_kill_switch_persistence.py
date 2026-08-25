"""A halt must survive a restart, and say so either way (item 32).

Found on 25 August the embarrassing way. The handoff said "THE KILL SWITCH IS
TRIPPED ... it is SAFE to reset", advice was given on that basis, and the
operator pointed at the app reporting INACTIVE. It had been cleared by that
morning's two restarts, not by anyone: `KillSwitch` held `_tripped` in memory
and persisted nothing, and `runtime.py` constructs a bare one every launch.

So a halt meant to hold until a human decides held only until the next start,
and was then cleared **silently** - no line in any log saying a halt had been
discarded.

This is the M50/M140 family: *this state did not survive a restart*. The
codebase already knows the fix twice over - `PositionAnomalyStore` and
`RestingOrderAnomalyStore` both persist deliberately. The switch, the most
consequential state in the application, did not.

Both halves are required and both are tested here: persist the trip, AND be
loud at startup about restoring or discarding one. Silence is the defect
either way.
"""

from __future__ import annotations

import logging

from qat.domain.risk_engine.kill_switch import KillSwitch


def test_a_trip_survives_a_restart(tmp_path):
    """THE regression. Before this, the second construction came up clear."""
    KillSwitch(tmp_path).trip("Broker reconciliation mismatch")

    restarted = KillSwitch(tmp_path)

    assert restarted.tripped, "the halt did not survive - this is item 32 exactly"
    assert restarted.reason == "Broker reconciliation mismatch", (
        "the REASON must survive too: 'halted' without why is not actionable, and "
        "the original cause is the thing an operator needs at 09:00"
    )


def test_restoring_a_halt_is_LOUD(tmp_path, caplog):
    """A restored halt that says nothing is how you end up believing you are
    trading when you are not."""
    KillSwitch(tmp_path).trip("Daily loss 5.00% >= limit 4.00%")

    with caplog.at_level(logging.CRITICAL):
        KillSwitch(tmp_path)

    assert "Daily loss" in caplog.text
    assert "halt" in caplog.text.lower() or "kill" in caplog.text.lower()


def test_a_reset_survives_a_restart_too(tmp_path):
    """The other direction. A cleared switch must not come back tripped."""
    switch = KillSwitch(tmp_path)
    switch.trip("Manual trigger by operator")
    switch.reset("operator")

    assert not KillSwitch(tmp_path).tripped


def test_no_data_dir_keeps_the_old_in_memory_behaviour(tmp_path):
    """Every existing test constructs `KillSwitch()` with no argument and must
    keep working untouched."""
    switch = KillSwitch()
    switch.trip("whatever")
    assert switch.tripped
    assert not KillSwitch().tripped, "a memory-only switch must not leak between instances"


def test_an_unreadable_state_file_does_not_stop_the_app(tmp_path, caplog):
    """The wrong direction, so it is logged at ERROR rather than swallowed - but
    an application that will not launch protects nothing at all."""
    (tmp_path / "kill_switch.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        switch = KillSwitch(tmp_path)

    assert not switch.tripped
    assert "kill_switch" in caplog.text.lower() or "halt" in caplog.text.lower()


def test_the_runtime_gives_the_switch_somewhere_to_persist():
    """The wiring, not just the capability. `PositionAnomalyStore` proves a
    persisted store can exist and still be constructed without its directory -
    which is exactly how this would silently stay in memory.
    """
    import inspect

    from qat.presentation import runtime

    source = inspect.getsource(runtime)
    assert "KillSwitch(" in source
    assert "KillSwitch()" not in source, (
        "runtime constructs a bare KillSwitch, so the halt has nowhere to "
        "persist and item 32 is not actually fixed in the running app"
    )
