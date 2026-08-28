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
        # Item 31, closed 28 August: the set is now the SHARED one, so a
        # regression is it becoming a literal again.
        (31, "data/broker/ib_translate.py", "_IB_WORKING_STATUSES = WORKING_STATUSES"),
        (22, "domain/oms/oms.py", "spendable_from("),
        # Item 44, closed 28 August: the field the bridge had been dropping.
        (44, "domain/oms/signal_bridge.py", "reference_price=event.reference_price"),
        # Item 18, closed 28 August. Pinned on the LOG line rather than the
        # caption: the caption is erased by the next RegimeEvent by design, so
        # the record is the thing a regression would take away.
        (18, "presentation/dashboard.py", "Regime note ACKNOWLEDGED by the operator"),
        # Items 21 and 40, closed 28 August (STALE - they were already fixed).
        # Pinned at the helper, because the defect was every call site
        # formatting its own clock and there being no one place to put this.
        (21, "domain/display_dates.py", "def format_session_time"),
        # Item 20, closed 28 August. `test_source_scanning_guards_cannot_go_
        # blind` already enforces this continuously; the pin is here so that
        # DELETING the helper - the one change that would silently restore the
        # old freedom - fails by item number rather than by import error.
        (20, "tests/support/source_corpus.py", "def source_files"),
        # Item 13, answered KEEP on 28 August. The answer RESTS on this
        # refusal: the case for deleting the Alpaca paths was that a US broker
        # could be pointed at an ASX book, and preflight already refuses that.
        # If the refusal goes, the answer has to be reopened, not inherited.
        (13, "preflight.py", 'settings.broker == "alpaca" and settings.market != "US"'),
    ],
)
def test_a_closed_item_has_not_quietly_regressed(item: int, relative: str, needle: str) -> None:
    assert needle in _read(relative), (
        f"item {item} is marked FIXED in HANDOFF.md but its evidence is gone from "
        f"{relative} - either it regressed or the claim was never true"
    )
