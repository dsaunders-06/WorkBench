"""Times shown to a human must not be silent UTC (item 40).

Extends item 21, which is not closed. On 25 August four surfaces rendered UTC
where session-local was meant, on a screen whose other fields are local:

  * `watch_session.py:179` - the WORST of them, a bare `%H:%M:%S` of
    `datetime.now(UTC)` with no zone label at all, printed into the live
    console an operator reads during a session. Read 03:21:34 off it at 13:21
    AEST and correlate against the Blotter, the log, or your own watch, and a
    ten-hour error lands in the middle of an incident - the only time anyone
    is reading that output.
  * the Balances panel's "as of"
  * the Regime Monitor's transition history
  * the Blotter's timestamp column

The Risk Console's anomaly rows were NOT affected because they label the zone
explicitly. That is the pattern: convert to session-local, or say which zone
it is. Silent UTC among session-local fields is the failure, not UTC itself.

The log's own `ts` field stays UTC-with-offset and must - machine records want
one zone. This is only about what is rendered to a human.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.domain.display_dates import format_session_time


def test_a_utc_instant_renders_in_the_market_session_zone():
    """13:21 Sydney, not 03:21."""
    ts = datetime(2026, 8, 25, 3, 21, 34, tzinfo=UTC)
    shown = format_session_time(ts, "ASX")
    assert shown.startswith("13:21:34"), shown


def test_the_zone_is_always_named():
    """A time with no zone is what caused this. The label is not decoration."""
    ts = datetime(2026, 8, 25, 3, 21, 34, tzinfo=UTC)
    assert "AEST" in format_session_time(ts, "ASX") or "AEDT" in format_session_time(ts, "ASX")


def test_the_us_market_gets_its_own_zone():
    ts = datetime(2026, 8, 25, 14, 30, 0, tzinfo=UTC)
    shown = format_session_time(ts, "US")
    assert shown.startswith("10:30:00"), shown
    assert "ED" in shown or "ES" in shown


def test_a_naive_timestamp_is_treated_as_utc_rather_than_guessed():
    """Records written before this existed carry naive UTC. Assuming local
    would move them by ten hours; assuming UTC is what they actually are."""
    naive = datetime(2026, 8, 25, 3, 21, 34)
    assert format_session_time(naive, "ASX").startswith("13:21:34")
