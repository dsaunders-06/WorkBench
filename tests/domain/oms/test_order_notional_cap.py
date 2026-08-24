"""The per-order notional cap trims a buy and never touches an exit.

Until 24 August 2026 this rail was a bare default argument on `OMS.__init__` -
`max_order_notional: float = 50_000.0` - with no comment, no setting, no manual
entry and no recorded measurement. It was the only risk limit in the system
carrying none of its own reasoning.

It bound for the first time on Monday's ASX open. Every other rail here is a
PERCENTAGE of equity and grew with the account; this one is a fixed sum and did
not. The half-Kelly sizer asked for ~12.5% of ~1.0M AUD - about $125,000 - and
the flat $50,000 refused the first real ASX entry signal this system ever
produced, 48 times in a row, one a minute.

Two changes, both operator decisions of 24 August:

* **Buys TRIM rather than refuse**, matching the single-name cap, which has
  trimmed since M31c because "under the old reject semantics 15% would have
  refused every swing trade outright rather than making it smaller".
* **Exits are EXEMPT.** The old code refused a sell above the cap, so a
  position larger than the cap could not be closed by this application at all.
  Trimming a sell is no better - it leaves a residual the operator believes is
  closed. The autonomy gate already draws this line: risk-reducing orders are
  not gated on appetite limits, and a notional cap is an appetite limit.
"""

from __future__ import annotations

import pytest

from qat.config import Settings


def test_the_cap_is_a_setting_now(tmp_path):
    """It could not be changed without editing oms.py before this."""
    assert Settings(_env_file=None).max_order_notional == 50_000.0
    assert Settings(_env_file=None, max_order_notional=125_000.0).max_order_notional == 125_000.0


def test_the_cap_must_be_positive():
    """A cap of zero would refuse every order while looking like a configured
    limit rather than a mistake."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_order_notional=0)


def test_it_is_the_only_risk_limit_that_is_not_a_fraction():
    """Pinned because it is the whole reason this rail went stale: the others
    scale with equity and this one does not, so they agree at exactly one
    account size and diverge either side of it.

    50,000 / 0.15 = 333,333. Below that the concentration cap binds first;
    above it, this one does.
    """
    settings = Settings(_env_file=None)
    assert settings.max_order_notional > 1.0, "a fraction would be <= 1"
    assert settings.max_single_name_concentration_pct <= 1.0, "a sum would be > 1"
    agree_at = settings.max_order_notional / settings.max_single_name_concentration_pct
    assert round(agree_at) == 333_333
