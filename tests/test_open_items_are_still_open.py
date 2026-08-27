"""An item that gets fixed must not keep its OPEN heading (item 64).

Twelve headings in `docs/HANDOFF.md` outlived their findings in two days. The
first four were found by tripping over them - item 38 by beginning to
RE-IMPLEMENT a fix that already existed - and the last eight by an audit that
should have happened first. Item 37 was sitting on a work queue as tier-2 while
its fix ran live in a session that had already been read twice.

⚠️ **The rot runs one way, so the guard has to run that way too.** A test cannot
detect "this open item is secretly fixed" in general. What it CAN do is assert
that each open item's defect is STILL PRESENT - so the day someone fixes one
without updating the list, this goes red and names the item.

That inverts the usual direction and it is deliberate: **these tests are
expected to fail when the code improves.** A red here is not a regression, it is
the list falling behind, and the fix is to update `HANDOFF.md` and delete the
entry below.

Only claims that are genuinely grep-able live here. Most items cannot be pinned
this way and are not pretended to be - a guard that covered everything by
weakening what it asserts is the failure this file exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import qat

_SRC = Path(qat.__file__).parent
_REPO = _SRC.parent.parent


def _read(relative: str) -> str:
    """⚠️ A missing file FAILS rather than skipping. An allowlist naming a path
    that has been renamed is how a guard quietly stops covering anything - the
    lesson `test_corporate_action_has_every_reader` already records for itself."""
    for root in (_SRC, _REPO, _REPO / "scripts"):
        candidate = root / relative
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError(f"{relative} not found - item 64's own allowlist has gone stale")


def test_item_31_the_working_status_set_is_still_narrow() -> None:
    """Item 31: `_IB_WORKING_STATUSES` omits statuses IBKR really returns, and
    it feeds `_position_stops` - a sizing input."""
    source = _read("data/broker/ib_translate.py")

    assert '_IB_WORKING_STATUSES = frozenset({"PreSubmitted", "Submitted", "PendingSubmit"})' in (
        source
    ), "item 31 appears FIXED - widen or close it in HANDOFF.md and delete this test"


def test_item_25_preflight_still_derives_unprotected_from_held_only() -> None:
    """Item 25: a position the broker did not report cannot be seen to be
    unprotected, so the count is of what is HELD rather than of what is at
    risk."""
    source = _read("preflight.py")

    assert (
        "unprotected = [p.symbol for p in held if p.symbol not in stops]" in source
    ), "item 25 appears FIXED - close it in HANDOFF.md and delete this test"


def test_item_29_deployed_is_still_maintained_by_hand() -> None:
    """Item 29: `handoff_state.py` carries hand-written `# M<N> DEPLOYED` lines,
    so the deploy record is a thing a human remembers to update."""
    source = _read("handoff_state.py")

    assert (
        "DEPLOYED" in source and "# M" in source
    ), "item 29 appears FIXED - close it in HANDOFF.md and delete this test"


@pytest.mark.parametrize(
    ("item", "relative", "needle"),
    [
        # The other direction: a fix that NAMED its own milestone in the code is
        # worth pinning so a regression cannot quietly undo it.
        (35, "logging.py", "ib_async.wrapper"),
        (51, "data/broker/ib_adapter.py", "retrying a refused port"),
        (54, "logging.py", "possibly delisted; no price data found"),
        (58, "domain/oms/oms.py", "_COMMITTED_STATUSES"),
        (59, "domain/oms/resting_order_anomaly.py", "CLEAN_SCANS_BEFORE_CLEAR"),
        (63, "domain/performance/trades.py", "def repair_csv_header"),
    ],
)
def test_a_closed_item_has_not_quietly_regressed(item: int, relative: str, needle: str) -> None:
    assert needle in _read(relative), (
        f"item {item} is marked FIXED in HANDOFF.md but its evidence is gone from "
        f"{relative} - either it regressed or the claim was never true"
    )
