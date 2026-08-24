"""The per-order cap is a share of cash, it trims a buy, and it never touches an exit.

Until 24 August 2026 this rail was `max_order_notional: float = 50_000.0`, a bare
default argument on `OMS.__init__` with no comment, no setting, no manual entry
and no recorded measurement - the only risk limit in the system carrying none of
its own reasoning, and the only one that was an absolute sum rather than a
fraction.

It bound for the first time on Monday's ASX open. Every other rail is a
percentage and grew with the account; this one did not. The half-Kelly sizer
asked for ~12.5% of ~1.0M AUD - about $125,000 - and the flat $50,000 refused
the first real ASX entry signal this system ever produced, 48 times in a row.

Three changes, all operator decisions of 24 August:

* it is a **fraction of available cash**, defaulting to 10%, because a sum tuned
  against a round 1M paper balance says nothing about a live account where
  liquidity binds long before the balance does;
* buys are **trimmed** rather than refused, matching the single-name cap, which
  has trimmed since M31c;
* exits are **exempt**. The old code refused a sell above the cap, so a position
  larger than the cap could not be closed by this application at all.
"""

from __future__ import annotations

import pytest

from qat.config import Settings


def test_the_default_is_ten_percent_of_cash():
    assert Settings(_env_file=None).max_order_pct_of_cash == 0.10


def test_it_is_a_fraction_not_a_sum():
    """The defect it replaced was an absolute figure that could not follow the
    account. A fraction travels from a 1M paper balance to a live one without
    being re-derived."""
    assert 0.0 <= Settings(_env_file=None).max_order_pct_of_cash <= 1.0


def test_the_whole_range_is_allowed():
    assert Settings(_env_file=None, max_order_pct_of_cash=0.0).max_order_pct_of_cash == 0.0
    assert Settings(_env_file=None, max_order_pct_of_cash=1.0).max_order_pct_of_cash == 1.0


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_outside_nought_to_one_is_refused(bad):
    """A percentage written as 10 rather than 0.10 is the obvious way to get
    this wrong, and it would read as 1000% of cash."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_order_pct_of_cash=bad)


def test_zero_is_a_usable_setting_not_a_misconfiguration():
    """Zero means no new entries: a trim to zero cannot make one whole share, so
    every buy is refused while exits stay exempt. That is a "stop opening
    positions and let the book run off" switch, which is why the range starts at
    0 rather than excluding it."""
    assert Settings(_env_file=None, max_order_pct_of_cash=0.0).max_order_pct_of_cash == 0.0
