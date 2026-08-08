"""Telling a clean stop from a death (M57c).

Confirmed on 7 August: the operator closed the application deliberately and the
log recorded nothing at all, which is exactly what the M56a crash looked like.
Until this existed the log could not distinguish them.
"""

from __future__ import annotations

import json

from qat.run_marker import MARKER_FILENAME, RunMarker, describe_previous_run


def test_a_first_ever_run_reports_no_predecessor(tmp_path):
    assert RunMarker(tmp_path).claim() is None


def test_a_clean_stop_leaves_nothing_behind(tmp_path):
    marker = RunMarker(tmp_path)
    marker.claim()
    assert (tmp_path / MARKER_FILENAME).exists()

    marker.release()

    assert not (tmp_path / MARKER_FILENAME).exists()
    assert RunMarker(tmp_path).claim() is None, "the next run must see a clean predecessor"


def test_a_run_that_never_released_is_reported_to_the_next_one(tmp_path):
    """The whole point. No release means the process did not reach its
    shutdown path."""
    RunMarker(tmp_path).claim()  # started, then died without releasing

    previous = RunMarker(tmp_path).claim()

    assert previous is not None
    assert previous.get("pid")
    assert previous.get("started_at")


def test_an_unreadable_marker_still_counts_as_unreleased(tmp_path):
    """Its presence is the signal; its contents are only detail. Treating a
    damaged file as evidence of a clean exit would report the reassuring
    answer on the strength of a corrupt one."""
    (tmp_path / MARKER_FILENAME).write_text("{ not json", encoding="utf-8")

    previous = RunMarker(tmp_path).claim()

    assert previous is not None


def test_claiming_replaces_the_stale_marker_with_this_run(tmp_path):
    """Otherwise one dirty shutdown would warn on every start forever."""
    RunMarker(tmp_path).claim()
    RunMarker(tmp_path).claim()  # reports the stale one, and takes ownership
    RunMarker(tmp_path).release()

    assert RunMarker(tmp_path).claim() is None


def test_a_read_only_directory_does_not_stop_a_run(tmp_path):
    """This is diagnostics. It must never be the reason the app fails to
    start, so every failure degrades to silence."""
    marker = RunMarker(tmp_path / "nonexistent" / "deeper")
    marker.claim()
    marker.release()


def test_the_warning_names_when_the_lost_run_started(tmp_path):
    text = describe_previous_run({"pid": "1234", "started_at": "2026-08-07T12:44:02+00:00"})

    assert text is not None
    assert "WITHOUT reaching its shutdown" in text
    assert "2026-08-07T12:44:02+00:00" in text
    assert "1234" in text


def test_no_warning_when_the_previous_run_stopped_cleanly():
    assert describe_previous_run(None) is None


def test_the_warning_survives_a_marker_with_no_detail():
    """A corrupt marker yields an empty dict, and the warning still has to be
    sayable - the absence of detail is not the absence of the fact."""
    text = describe_previous_run({})

    assert text is not None
    assert "WITHOUT reaching its shutdown" in text


def test_the_marker_round_trips_as_json(tmp_path):
    RunMarker(tmp_path).claim()

    written = json.loads((tmp_path / MARKER_FILENAME).read_text(encoding="utf-8"))

    assert set(written) == {"pid", "started_at"}
