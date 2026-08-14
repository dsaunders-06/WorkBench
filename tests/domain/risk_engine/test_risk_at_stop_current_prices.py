"""The aggregate cap must measure what is at risk NOW (M66).

`PortfolioGovernor.snapshot` computed each position's risk as
`prices.get(symbol) or pos.avg_price`, and `avg_price` is the broker's
`avg_entry_price`. The `prices` argument is threaded through `snapshot`,
`evaluate` and `delever_fraction` - and **nothing in the trading path ever
passed it**: `RiskEngine` and `DeleverSweep` both omit it, and only `adopted.py`,
a display, supplies it.

So every entry decision and every de-lever check this system has made was
measured against the prices its positions were OPENED at.

**The direction is what makes it serious.** Risk per share is `price - stop`, so
a position that has gained has further to fall. A winning book UNDERSTATES its
risk and believes it has headroom it does not have; a losing book overstates it
and refuses trades it could take. The bias is backwards from prudent and grows
with profit.

The fix is one fallback tier - `prices.get(...) or pos.current_price or
pos.avg_price` - because the governor already receives `positions`, and the
broker's own mark is the consolidated tape rather than the IEX feed the
application subscribes to.
"""

from __future__ import annotations

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.risk_engine.governor import PortfolioGovernor


def _governor() -> PortfolioGovernor:
    return PortfolioGovernor(settings=Settings(_env_file=None))


def test_a_position_is_measured_on_its_mark_not_its_entry():
    """100 shares bought at 100 with a stop at 90 is $1,000 at risk on entry
    prices. Marked at 120 the same position has $3,000 to lose before the stop
    catches it, and that is what the cap is supposed to be governing."""
    position = Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=120.0)

    snap = _governor().snapshot([position], {"AAA": 90.0}, equity=100_000.0)

    assert snap.risk_at_stop_dollars == 3_000.0


def test_without_a_mark_the_old_behaviour_is_unchanged():
    """Pinned deliberately. A broker that reports no mark - MockBroker, the IBKR
    seam, every existing test - must keep measuring exactly as it did, and
    `None` must never be read as a mark of zero, which would make the position
    look risk-free."""
    position = Position(symbol="AAA", quantity=100.0, avg_price=100.0)

    snap = _governor().snapshot([position], {"AAA": 90.0}, equity=100_000.0)

    assert snap.risk_at_stop_dollars == 1_000.0


def test_an_explicit_price_still_wins():
    """`adopted.py` supplies its own map and must be unaffected."""
    position = Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=120.0)

    snap = _governor().snapshot([position], {"AAA": 90.0}, equity=100_000.0, prices={"AAA": 110.0})

    assert snap.risk_at_stop_dollars == 2_000.0


def test_a_gained_position_raises_measured_risk_and_a_lost_one_lowers_it():
    """The direction of the defect, in one assertion. This is what made a
    winning book believe it had headroom it did not have."""
    gained = Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=120.0)
    lost = Position(symbol="BBB", quantity=100.0, avg_price=100.0, current_price=95.0)
    stops = {"AAA": 90.0, "BBB": 90.0}

    at_entry = _governor().snapshot(
        [Position("AAA", 100.0, 100.0), Position("BBB", 100.0, 100.0)], stops, equity=100_000.0
    )
    marked = _governor().snapshot([gained, lost], stops, equity=100_000.0)

    assert _governor().snapshot([gained], stops, 100_000.0).risk_at_stop_dollars > 1_000.0
    assert _governor().snapshot([lost], stops, 100_000.0).risk_at_stop_dollars < 1_000.0
    # 3,000 + 500 against 1,000 + 1,000 - the book as a whole reads higher.
    assert marked.risk_at_stop_dollars > at_entry.risk_at_stop_dollars


def test_a_position_below_its_stop_still_counts_its_whole_value():
    """The unknown-protection rule must survive the new tier. A mark at or under
    the stop means `_per_share_risk` returns the price, not a negative."""
    position = Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=85.0)

    snap = _governor().snapshot([position], {"AAA": 90.0}, equity=100_000.0)

    assert snap.risk_at_stop_dollars == 8_500.0


def test_a_book_that_has_gained_can_breach_a_cap_it_reports_as_clear():
    """The defect as the live book met it: measured on entry prices the book
    reads inside the cap, and on marks it is over. Every entry decision was
    gated on the first number."""
    stops = {f"S{i}": 90.0 for i in range(10)}
    at_entry = [Position(f"S{i}", 50.0, 100.0) for i in range(10)]
    marked = [Position(f"S{i}", 50.0, 100.0, current_price=118.0) for i in range(10)]
    governor = _governor()
    cap = governor.settings.max_aggregate_risk_at_stop_pct

    entry_pct = governor.snapshot(at_entry, stops, equity=100_000.0).risk_at_stop_pct
    marked_pct = governor.snapshot(marked, stops, equity=100_000.0).risk_at_stop_pct

    assert entry_pct <= cap, "on entry prices this book reports itself inside the cap"
    assert marked_pct > cap, "on marks it is over - and the marks are what is at risk"
