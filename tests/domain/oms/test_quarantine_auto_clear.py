"""A quarantine the reconciler declared, the reconciler can lift (item 59).

Found 27 August at launch, from the app's own startup lines seventy seconds
apart:

    Restored 2 resting-order quarantine(s) ...: SEK.AX, WOW.AX
    RESTING ORDER SCAN: 22 working leg(s) across 11 symbol(s), nothing unjustified

`_reconcile_resting_orders` declares inside `for divergence in divergences:`, so
a CLEAN scan runs no loop body and there was no symmetric clear. `clear()` had
exactly one caller in the codebase - an operator button. The store could only
grow, and the two above outlived their cause by roughly 26 hours and a restart.

⚠️ **Why auto-clearing is defensible here specifically.** This is not "the
symptom went away". It is the SAME rail, over the SAME input, running the SAME
derivation and reporting the negation - a stronger warrant than a human clicking
without re-deriving anything.

⚠️ **Hysteresis, because a divergence can flap.** Clearing on the first clean
scan would let the store track noise, and an entry could slip through a clean
window that does not hold. Three consecutive clean scans is fifteen minutes at
the 300s poll. The codebase already uses this shape in `HysteresisGate`.

The manual button stays: an operator must still be able to release a symbol
without waiting three polls.
"""

from __future__ import annotations

import pytest

from qat.domain.oms.resting_order_anomaly import (
    CLEAN_SCANS_BEFORE_CLEAR,
    RestingOrderAnomalyStore,
)


@pytest.fixture
def store(tmp_path) -> RestingOrderAnomalyStore:
    return RestingOrderAnomalyStore(tmp_path)


def _declare(store: RestingOrderAnomalyStore, symbol: str = "SEK.AX") -> None:
    store.declare(
        symbol=symbol,
        reason="2978 shares of resting sell the book does not justify (holds 2978)",
        declared_by="order-reconciler",
        excess=2978.0,
    )


def test_a_clean_scan_alone_does_not_lift_it(store) -> None:
    """One clean scan is not evidence a divergence has stopped flapping."""
    _declare(store)

    store.saw_clean_scan({"SEK.AX"})

    assert store.is_quarantined("SEK.AX")


def test_it_lifts_after_the_full_run_of_clean_scans(store) -> None:
    _declare(store)

    for _ in range(CLEAN_SCANS_BEFORE_CLEAR):
        store.saw_clean_scan({"SEK.AX"})

    assert not store.is_quarantined("SEK.AX")


def test_a_divergence_resets_the_run(store) -> None:
    """⚠️ The flapping case, and the reason for hysteresis at all. A symbol that
    goes clean, dirty, clean must start counting again - otherwise the run is a
    tally of clean scans rather than of CONSECUTIVE ones."""
    _declare(store)
    for _ in range(CLEAN_SCANS_BEFORE_CLEAR - 1):
        store.saw_clean_scan({"SEK.AX"})

    _declare(store)  # the divergence is back
    store.saw_clean_scan({"SEK.AX"})

    assert store.is_quarantined("SEK.AX")


def test_a_symbol_the_scan_did_not_cover_does_not_count(store) -> None:
    """⚠️ The one that would be silent. A scan that could not see a symbol says
    NOTHING about it, and counting that as clean would lift a quarantine on
    absence of evidence - the fabricated-all-clear shape of items 34 and 37."""
    _declare(store)

    for _ in range(CLEAN_SCANS_BEFORE_CLEAR * 2):
        store.saw_clean_scan({"WOW.AX"})

    assert store.is_quarantined("SEK.AX")


def test_the_operator_can_still_release_it_immediately(store) -> None:
    """Hysteresis must not cost the operator fifteen minutes in an incident."""
    _declare(store)

    assert store.clear("SEK.AX", operator="operator (risk console)") is True
    assert not store.is_quarantined("SEK.AX")


def test_lifting_it_survives_a_restart(store, tmp_path) -> None:
    """The 26-hour failure was a quarantine RESTORED from disk. An auto-clear
    that lived only in memory would restore it on the next launch and the whole
    exercise would be theatre."""
    _declare(store)
    for _ in range(CLEAN_SCANS_BEFORE_CLEAR):
        store.saw_clean_scan({"SEK.AX"})

    assert not RestingOrderAnomalyStore(tmp_path).is_quarantined("SEK.AX")
