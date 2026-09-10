"""Which HELD positions are about to run into a scheduled earnings print (M41).

⚠️ **DETECTION ONLY. THIS PLACES, CANCELS AND RESIZES NOTHING**, deliberately.
What to DO about a print arriving mid-hold is an open policy question and the
options are not equal:

* **Exit before it** closes on the calendar rather than the thesis, and collides
  with `QAT_MIN_HOLDING_TRADING_DAYS` when the print falls inside the minimum
  hold.
* **Trim into it** is AVAILABLE. ⚠️ An earlier version of this docstring said it
  was blocked by a latent partial-exit defect. **That was read off a stale
  outstanding item** - `submit_exit_order` has released its protective legs on a
  partial since 9 September, tested at `reason="delever"`, and the remainder is
  re-armed by the protection sweep at the current holding. The remainder is
  briefly unprotected, bounded by `protection_sweep_seconds`, which is a cost
  accepted deliberately there.
* **Accept it**, which is the status quo and is what this module makes visible.

**The gap this closes is that the exposure was INVISIBLE.** `_days_to_earnings`
is consulted once, at signal time, to feed M57's entry-side halving. Afterwards
nothing looks again: `earnings_at_entry` and `held_through_earnings` are written
onto the CLOSED trade and read only by `diagnostics.py` for completeness
counting. A position whose print arrives three weeks into a hold passed
unremarked.

⚠️ Unlike M39's splits, this is NOT rare. Roughly quarterly per position across
ten positions is about forty announcements a year in the book, against a 6% gap
budget measured across 28,987 ORDINARY nights while earnings gaps run 15-20% -
and a stop does not help, because the price never trades there.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Far enough ahead to act on, near enough that the calendar is trustworthy.
# ⚠️ CONVENTIONAL, NOT MEASURED - the same caveat Phase 1's thresholds carry.
DEFAULT_WITHIN_TRADING_DAYS = 5


@dataclass(frozen=True, slots=True)
class EarningsExposure:
    symbol: str
    quantity: float
    trading_days_away: int

    def describe(self) -> str:
        when = "TODAY" if self.trading_days_away == 0 else f"in {self.trading_days_away} day(s)"
        return f"{self.symbol} x{self.quantity:g} reports {when}"


def positions_facing_earnings(
    held: dict[str, float],
    days_to_earnings: Callable[[str], int | None],
    within: int = DEFAULT_WITHIN_TRADING_DAYS,
) -> list[EarningsExposure]:
    """Held positions whose next print falls within `within` trading days.

    ⚠️ A symbol the calendar cannot answer for is NOT reported as safe. It is
    omitted, and the caller says how many were unreadable - "nothing pending"
    and "I could not find out" are different facts, and a screen that reports
    the first when the second is true asserts something false. That is M39's
    lesson and it applies unchanged here.

    Sorted soonest-first: the one that reports tomorrow matters more than the
    one that reports on Friday.
    """
    found: list[EarningsExposure] = []
    for symbol, quantity in held.items():
        if abs(quantity) <= 1e-9:
            continue
        try:
            days = days_to_earnings(symbol)
        except Exception:  # noqa: BLE001 - a diagnostic must never break a sweep
            logger.debug("Earnings distance unavailable for %s", symbol, exc_info=True)
            continue
        if days is None or days < 0 or days > within:
            continue
        found.append(EarningsExposure(symbol=symbol, quantity=quantity, trading_days_away=days))
    return sorted(found, key=lambda e: (e.trading_days_away, e.symbol))


def unreadable_symbols(
    held: dict[str, float], days_to_earnings: Callable[[str], int | None]
) -> list[str]:
    """Held symbols the calendar could not answer for, so silence is not read
    as safety."""
    out: list[str] = []
    for symbol, quantity in held.items():
        if abs(quantity) <= 1e-9:
            continue
        try:
            if days_to_earnings(symbol) is None:
                out.append(symbol)
        except Exception:  # noqa: BLE001
            out.append(symbol)
    return sorted(out)


def report(
    held: dict[str, float],
    days_to_earnings: Callable[[str], int | None],
    within: int = DEFAULT_WITHIN_TRADING_DAYS,
) -> Sequence[EarningsExposure]:
    """Log the exposure and return it. Never raises."""
    exposures = positions_facing_earnings(held, days_to_earnings, within)
    unreadable = unreadable_symbols(held, days_to_earnings)
    if exposures:
        logger.warning(
            "EARNINGS WITHIN %d TRADING DAY(S) on %d held position(s): %s. ⚠️ This is a "
            "REPORT, not a rail - nothing is sized, trimmed or exited for it. A 6%% gap "
            "budget was measured on ordinary nights and earnings gaps run 15-20%%, where a "
            "stop cannot fill.",
            within,
            len(exposures),
            "; ".join(e.describe() for e in exposures),
        )
    if unreadable:
        logger.warning(
            "EARNINGS UNREADABLE for %d held symbol(s): %s. This is NOT the same as "
            "'no print is due' - the calendar did not answer.",
            len(unreadable),
            ", ".join(unreadable),
        )
    return exposures
