"""Exchange price increments, and rounding onto them (M123).

An order price that is not a multiple of the instrument's tick is not a worse
price - it is not a price at all. IBKR rejects it (error 110, "does not conform
to the minimum price variation"), so the order never reaches the market and the
position it was meant to open or protect does not exist.

Nothing in this codebase computed ticks until now. That was survivable on the
US side by accident: `AlpacaAdapter` rounds to 2dp, and the US tick is $0.01
at every price a megacap trades at, so 2dp and "on tick" were the same thing.
The ASX move broke that coincidence - the increment there is $0.005 between
$0.10 and $2.00 - and the swing strategy derives its stop from ATR, so a stop
on a $1.91 stock comes out at something like 1.8734. Two of the names armed on
21 August sat in that band.

**Buys round down, sells round up.** One rule, and it is conservative on both
axes at once:

* a BUY never pays more than intended, and a buy-stop protecting a short moves
  closer to the market - it triggers sooner;
* a SELL never receives less than intended, and a sell-stop protecting a long
  moves closer to the market - it triggers sooner.

So rounding can tighten protection by up to one tick but can never loosen it,
and can never move a price in the direction that costs money. Position size is
computed from the unrounded stop, so the realised risk is at most a tick
smaller than the sized risk, never larger.

Decimal throughout. `1.8734 / 0.005` in binary floating point is not what it
looks like, and "is this on a tick" is exactly the comparison that gets it
wrong.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_FLOOR, ROUND_UP, Decimal

from qat.domain.market_calendar import Market

# (price below which this tick applies, tick). None means "and above".
#
# ASX: ASX Operating Rules price steps. US: SEC Rule 612 - a sub-dollar tick
# exists but no instrument this system trades reaches it, so it is here for
# correctness rather than because it is expected to fire.
_TICK_TABLES: dict[str, tuple[tuple[Decimal | None, Decimal], ...]] = {
    "ASX": (
        (Decimal("0.10"), Decimal("0.001")),
        (Decimal("2.00"), Decimal("0.005")),
        (None, Decimal("0.01")),
    ),
    "US": (
        (Decimal("1.00"), Decimal("0.0001")),
        (None, Decimal("0.01")),
    ),
}


def tick_size(price: float | Decimal, market: Market) -> Decimal:
    """The minimum price increment at `price` on `market`."""
    value = Decimal(str(price))
    for bound, tick in _TICK_TABLES[market]:
        if bound is None or value < bound:
            return tick
    raise AssertionError(f"no tick band for {price} on {market}")  # pragma: no cover


def round_to_tick(price: float, market: Market, side: str) -> float:
    """Move `price` onto a valid increment, in the direction that cannot hurt.

    `side` is the order's own side: "buy" rounds down, "sell" rounds up. See
    the module docstring - the same rule is right for entries, targets and
    protective stops, which is why there is no separate policy per order type.
    """
    if price <= 0:
        raise ValueError(f"cannot round a non-positive price onto a tick: {price}")

    value = Decimal(str(price))
    tick = tick_size(value, market)
    rounding = ROUND_DOWN if side == "buy" else ROUND_UP
    steps = (value / tick).to_integral_value(rounding=rounding)
    result = steps * tick

    # Flooring a price below one tick would produce zero, which is not a price.
    # No ASX or US instrument trades there, so this is a guard rather than a
    # branch anyone should reach - but returning 0.0 to a broker is the kind of
    # thing that gets discovered by a rejection.
    if result <= 0:
        result = tick

    # The band is chosen by the price, so rounding can cross a boundary - 1.9999
    # rounds up to 2.0000, which needs the $0.01 band's blessing rather than the
    # $0.005 band's. Re-floor onto the destination band when that happens.
    settled = tick_size(result, market)
    if settled != tick:
        result = (result / settled).to_integral_value(rounding=ROUND_FLOOR) * settled

    return float(result)


def is_on_tick(price: float, market: Market) -> bool:
    """Whether `price` is already a valid increment. The check a rejection makes."""
    if price <= 0:
        return False
    value = Decimal(str(price))
    return value % tick_size(value, market) == 0
