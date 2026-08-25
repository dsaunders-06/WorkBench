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


def test_the_build_stamp_takes_its_DATE_from_the_converted_value_too(monkeypatch):
    """Item 50, and the half that is easy to get wrong.

    The stamp read `built 25/08/2026 12:01 UTC` on M144's Settings screen,
    where 12:01 UTC is 22:01 AEST - the labelled kind of the item 40 defect
    rather than the dangerous kind, but rendered to a human among fields that
    are session-local.

    Converting only the TIME would be worse than leaving it in UTC: a build at
    14:30 UTC is already the next day in Sydney, so the stamp would claim
    00:30 AEST on the PREVIOUS date and the two halves would disagree about
    which zone they were in. This pins the composition `_write_build_stamp`
    uses, so that cannot regress silently into the artefact - where it is baked
    at package time and a redeploy alone will not correct it.
    """
    from qat.domain.display_dates import format_display_date
    from qat.domain.market_calendar import MARKET_TIMEZONES

    def stamp_for(moment: datetime) -> str:
        local = moment.astimezone(MARKET_TIMEZONES["ASX"])
        return f"{format_display_date(local)} {format_session_time(moment)}"

    assert stamp_for(datetime(2026, 8, 25, 12, 1, tzinfo=UTC)) == "25/08/2026 22:01:00 AEST"
    # The rollover: same UTC date, next Sydney date.
    assert stamp_for(datetime(2026, 8, 25, 14, 30, tzinfo=UTC)) == "26/08/2026 00:30:00 AEST"


def test_the_build_stamp_composition_is_the_one_tasks_py_actually_writes():
    """The test above is only worth having if it pins the REAL call site.

    A test that reimplements the code it guards agrees with itself and with
    nothing shipped - which is exactly how the sector rail passed its tests
    while never running (item 44). So read `tasks.py` and assert the line.
    """
    import pathlib

    source = pathlib.Path("tasks.py").read_text(encoding="utf-8")
    assert 'local = now.astimezone(MARKET_TIMEZONES["ASX"])' in source
    assert 'built_at = f"{format_display_date(local)} {format_session_time(now)}"' in source
    assert (
        'UTC"' not in source.split("built_at =")[1].split("\n")[0]
    ), "the build stamp is rendering UTC again (item 50)"


def _watcher_module():
    """Load `scripts/watch_session.py`, which is a script rather than a package.

    Imported by path deliberately: the point is to test the code the operator
    actually runs, not a copy of its logic.
    """
    import importlib.util
    import pathlib

    path = pathlib.Path("scripts/watch_session.py").resolve()
    spec = importlib.util.spec_from_file_location("qat_watch_session", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_watcher_event_line_renders_the_market_zone_not_bare_utc():
    """The half of item 40 that M144 missed, in the file it called the WORST.

    The tally line in `watch_session.py` was converted; the PER-EVENT line
    twenty lines above it was not - it was `str(ts)[11:19]`, a raw slice of the
    log's UTC-with-offset field that discarded the offset and printed a bare
    UTC clock. Observed 26 August: an app launch at 08:53:34 AEST printed as
    `22:53:34`.

    This is the line that repeats hundreds of times during an incident, which
    is the only time anyone reads this tool.
    """
    watcher = _watcher_module()
    shown = watcher._event_time("2026-08-25T22:53:34.123456+00:00")
    assert shown.startswith("08:53:34"), shown
    assert "AEST" in shown or "AEDT" in shown, shown


def test_the_watcher_never_dies_on_a_malformed_timestamp():
    """It runs unattended for a whole session. A monitoring tool that raises on
    one bad line is worse than one showing an awkward stamp."""
    watcher = _watcher_module()
    for bad in (None, "", "garbage", 12345, "2026-13-45T99:99:99"):
        assert isinstance(watcher._event_time(bad), str)
