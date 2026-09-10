"""Every watched symbol must resolve to a real company name, not its own ticker.

⚠️ THIS EXISTS BECAUSE M161 WIDENED THE WATCHLIST WITHOUT IT - the SECOND time,
in the SAME widening. Five names (ALX, CWY, SDF, SOL, ANN) were added to the
megacap list and to neither `SECTOR_BY_SYMBOL` nor `INSTRUMENT_NAMES`. M162
added `test_watchlist_symbols_all_have_sectors` and fixed the sectors; the names
were left, and on 10 September the operator found them in the Screener still
rendering `ALX.AX` in the Name column beside `Aurizon Holdings Limited`.

**A guard was built for one field of the same widening and not the other.** That
is the shape of 10349 surviving from 4 to 9 September, and of the orphan rail
learning "in flight" on the protection side and not the entry side.

`name_for()` falls back to the symbol deliberately, so a missing name can never
raise and never shows a blank cell - which is exactly why nothing surfaced it
for weeks. `has_name()` exists to tell the two apart, and until now nothing
called it.

⚠️ Scoped to the RESOLVED watchlist for the same reason the sector test is: the
table deliberately retains delisted and unwatched symbols (AWC, IPL) so old
lists still resolve to something, and asserting over everything would fail on
them for no reason.
"""

from __future__ import annotations

from qat.config import Settings
from qat.data.instruments import has_name, name_for
from qat.data.universe import resolve_watchlist


def _watched() -> list[str]:
    settings = Settings(
        _env_file=None,
        market="ASX",
        watchlist_category="megacap",
        watchlist_max_symbols=200,
    )
    return list(resolve_watchlist(settings))


def test_watchlist_symbols_all_have_company_names() -> None:
    watched = _watched()
    assert watched, "an empty watchlist would make the assertion below vacuous"

    unnamed = sorted(symbol for symbol in watched if not has_name(symbol))

    assert not unnamed, (
        f"{len(unnamed)} watchlist symbol(s) have no company name, so the Screener "
        f"renders the ticker in the Name column: {unnamed}. "
        f"Add them to qat.data.instruments._ASX_NAMES."
    )


def test_no_watched_name_is_just_its_own_ticker() -> None:
    """The failure MODE, not just the missing key.

    ⚠️ `has_name` and `name_for` could drift apart - a table entry mapping a
    symbol to itself would satisfy the test above and still render the ticker.
    This asserts what the operator actually sees.
    """
    echoes = sorted(symbol for symbol in _watched() if name_for(symbol) == symbol)

    assert not echoes, f"Name column would show the ticker for: {echoes}"
