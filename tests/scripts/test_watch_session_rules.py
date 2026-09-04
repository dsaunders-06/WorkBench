"""The watcher's rules, checked against REAL log lines (item 60).

`scripts/watch_session.py` had no tests at all, and it carried a rule reading
`"carries a stop resting"` while `oms.py:961` logs `"%d of %d carry a stop
resting"` - plural, always, because it is a count. The rule matched nothing
ever, so the one line naming every adopted position and how many are protected
was invisible in the live view for the whole life of the tool.

⚠️ **Every string below is COPIED FROM `qat.log`, not written to match the
rule.** That direction is the entire point. A fixture phrased from the rule
would have passed against `"carries"` just as happily, which is how the bug
survived - and it is the same failure as a fixture that fills an order in one
execution when the broker fills it in 183.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from watch_session import _RULES, _classify  # noqa: E402

# Verbatim from the 27 August 2026 launch, trimmed only in length.
_REAL_LINES: tuple[tuple[str, str, str], ...] = (
    (
        "Adopted 11 pre-existing broker position(s) as the reconciliation baseline: "
        "A2M.AX 9636, ANZ.AX 640. 11 of 11 carry a stop resting at the broker, which "
        "is what their risk is measured to; 0 carry none",
        "INFO",
        "ADOPT",
    ),
    (
        "Restored 2 resting-order quarantine(s) from resting_order_anomalies.json: "
        "SEK.AX, WOW.AX",
        "WARNING",
        "QUARANTINE",
    ),
    (
        "Resting-order quarantine on SEK.AX cleared by operator (was: 2978 shares of "
        "resting sell the book does not justify) - ordinary order flow resumes",
        "WARNING",
        "QUARANTINE",
    ),
    (
        "RESTING ORDER SCAN: 22 working leg(s) across 11 symbol(s), nothing unjustified",
        "INFO",
        "SCAN",
    ),
    (
        "AUTONOMOUS EXECUTION IS ENABLED - qualifying orders will be signed off "
        "without confirmation. Promoted strategies: swing",
        "WARNING",
        "AUTO",
    ),
    (
        "The broker-fill watermark is 11.2 hours old, so this run will replay every "
        "execution since 2026-08-26T12:02:39+00:00.",
        "WARNING",
        "RESTORE",
    ),
    (
        "Order signed off and transmitted: order=6ac52ed8d8284a25a3fa81966e02fafe "
        "operator=autonomous-executor symbol=WOW.AX qty=1098.0",
        "INFO",
        "TRANSMIT",
    ),
    (
        "Corrected the recorded entry price for SEK.AX -> 14.8836 to what the broker charged",
        "INFO",
        "PRICEFIX",
    ),
    (
        "Aggregate risk-at-stop 5.03% is over the 5.00% cap - sweep is disabled, so "
        "nothing will be sold to correct it.",
        "WARNING",
        "AGGRISK",
    ),
    # M119's three lines. The recovery is the only POSITIVE evidence the retry
    # worked, it fires once, and it is WARNING - so it was invisible.
    ("yfinance market data has recovered", "WARNING", "FEED"),
    (
        "yfinance has returned no data 5 times consecutively - market data is down. "
        "Retrying with backoff.",
        "ERROR",
        "FEED",
    ),
    # ⚠️ The line above is HISTORY as of M167 - the source no longer emits it,
    # because all seven of its appearances in the live log were the 10:04 open
    # and every one was followed by a recovery. The rule stays so older logs
    # still read correctly. The line below is what a real outage says now, and
    # it must keep classifying: it is the only place a partial outage is
    # reported, and 3 September proved a partial outage is the shape that
    # actually happens.
    (
        "yfinance has returned nothing for 99 of 100 symbol(s) for 5 consecutive polls - "
        "market data is down for most of the book. Retrying with backoff. Failing: BHP.AX",
        "ERROR",
        "FEED",
    ),
    ("yfinance poll produced no ticks (3/5)", "WARNING", "FEED"),
    # Regressions - these worked before and must keep working.
    (
        "Build: M148 (0b1ecd6, built 26/08/2026 19:02:41 AEST, packaged)",
        "INFO",
        "BUILD",
    ),
    (
        "Trading session stood down - ASX is before open. The feed is idle",
        "INFO",
        "SESSION",
    ),
    (
        "Broker-fill watermark restored to 2026-08-26T12:02:39+00:00 - executions "
        "since then are replayed for the record",
        "INFO",
        "RESTORE",
    ),
)


@pytest.mark.parametrize(("message", "level", "expected"), _REAL_LINES)
def test_a_real_log_line_is_surfaced_under_the_right_label(
    message: str, level: str, expected: str
) -> None:
    assert _classify(message, level) == expected


def test_the_adopt_rule_matches_the_plural_the_app_actually_logs() -> None:
    """The specific regression, pinned on its own so it cannot be lost in a
    parametrised list.

    `oms.py` formats "%d of %d carry a stop resting" and never "carries" - the
    count makes it plural even at one, because it reads "1 of 1 carry". A rule
    written from memory of the singular matched neither.
    """
    assert not any(needle == "carries a stop resting" for needle, _ in _RULES)


def test_an_ordinary_info_line_is_still_dropped() -> None:
    """The watcher's value is what it LEAVES OUT. A rule set that surfaces
    everything is the raw log with extra steps."""
    assert _classify("Macro DGS10 = 4.64 (as of 2026-08-25)", "INFO") is None


def test_an_unmatched_error_still_falls_through() -> None:
    assert _classify("something nobody wrote a rule for", "ERROR") == "ERROR"


def test_the_connection_storm_stays_quiet() -> None:
    """3,141 of the 5,218 WARNING lines on record are this one message. Measured
    before deciding NOT to surface WARNING as a level - which was the tempting
    fix and would have buried the live view on the first disconnect."""
    assert _classify("Could not read the account from the broker: Not connected", "WARNING") is None
