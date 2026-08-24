"""A rotation failure must not silence the log.

MEASURED, not imagined. On Monday 24 August 2026 the application's log froze at
5,242,781 bytes - 99 short of the 5 MiB cap - at 10:06:27, five minutes into the
ASX open. It stayed frozen across a full application restart while the app went
on trading normally, evaluating fourteen sizing decisions and writing every one
of them to `risk_decisions.csv`. Nothing anywhere said the log had stopped.

The cause was a pair, and neither half was wrong on its own:

* `scripts/watch_session.py` held the log open for its whole run, and on Windows
  a plain `open()` does not grant delete-sharing;
* `RotatingFileHandler.doRollover` closes the stream, renames, reopens - and on
  a failed rename leaves `stream=None` and lets `emit`'s except clause swallow
  the error.

It cost a wrong diagnosis: a market-data feed that had recovered on its own
looked hung, because the only evidence either way was a log that had stopped.

The rule these tests pin: **a log that grows past its cap is a far smaller
problem than a log that stops.**
"""

from __future__ import annotations

import json
import logging
import os
import sys

import pytest

from qat.logging import (
    LOG_MAX_BYTES,
    JsonFormatter,
    ResilientRotatingFileHandler,
)


def _handler(tmp_path, max_bytes: int = 200) -> ResilientRotatingFileHandler:
    handler = ResilientRotatingFileHandler(
        tmp_path / "qat.log", maxBytes=max_bytes, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(JsonFormatter())
    return handler


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_the_cap_still_rotates_when_nothing_is_in_the_way(tmp_path):
    """The resilience must not have cost the feature it protects."""
    handler = _handler(tmp_path)
    for index in range(40):
        handler.emit(_record(f"line {index}"))
    handler.close()

    assert (tmp_path / "qat.log.1").exists(), "no rotation happened at all"


@pytest.mark.skipif(sys.platform != "win32", reason="delete-sharing semantics are Windows-specific")
def test_a_reader_holding_the_file_does_not_silence_the_log(tmp_path):
    """THE test. This is the live failure, reproduced.

    A reader holding the file the way `watch_session.py` used to is what made
    the rename fail. Before this handler existed, everything after that point
    was lost in silence.
    """
    handler = _handler(tmp_path)
    handler.emit(_record("before the reader arrives"))

    log_path = tmp_path / "qat.log"
    with log_path.open("r", encoding="utf-8", errors="replace") as reader:
        reader.seek(0, os.SEEK_END)
        for index in range(40):
            handler.emit(_record(f"while held {index}"))

    handler.close()
    text = log_path.read_text(encoding="utf-8", errors="replace")

    assert "while held 39" in text, "the log went silent - this is the 24 August defect"
    assert handler.rollover_failures > 0, "the rename did not fail, so this test proved nothing"


@pytest.mark.skipif(sys.platform != "win32", reason="delete-sharing semantics are Windows-specific")
def test_the_failure_announces_itself_in_the_log(tmp_path):
    """Silence was the whole defect. A rotation that cannot happen has to say
    so somewhere the operator already looks, which is the log itself."""
    handler = _handler(tmp_path)
    log_path = tmp_path / "qat.log"

    with log_path.open("r", encoding="utf-8", errors="replace") as reader:
        reader.seek(0, os.SEEK_END)
        for index in range(40):
            handler.emit(_record(f"held {index}"))

    handler.close()
    text = log_path.read_text(encoding="utf-8", errors="replace")

    assert "LOG ROTATION FAILED" in text
    assert "watch_session" in text, "the message should name the usual culprit"


@pytest.mark.skipif(sys.platform != "win32", reason="delete-sharing semantics are Windows-specific")
def test_it_does_not_attempt_a_rename_per_record(tmp_path):
    """A failing rename retried on every record is a syscall storm at exactly
    the moment the application can least afford one - and it would bury the
    announcement under thousands of copies of itself."""
    handler = _handler(tmp_path)
    log_path = tmp_path / "qat.log"

    with log_path.open("r", encoding="utf-8", errors="replace") as reader:
        reader.seek(0, os.SEEK_END)
        for index in range(200):
            handler.emit(_record(f"held {index}"))

    handler.close()

    assert (
        handler.rollover_failures == 1
    ), f"{handler.rollover_failures} rename attempts for 200 records - the cooldown is not holding"
    announcements = [
        line
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if "LOG ROTATION FAILED" in line
    ]
    assert len(announcements) == 1, f"announced {len(announcements)} times, expected once"


def test_every_line_stays_valid_json(tmp_path):
    """The announcement is written by hand, bypassing `logging`, so it is the
    one line that could plausibly break the format every consumer parses -
    watch_session.py and session_check both read this as JSON lines."""
    handler = _handler(tmp_path)
    log_path = tmp_path / "qat.log"

    with log_path.open("r", encoding="utf-8", errors="replace") as reader:
        reader.seek(0, os.SEEK_END)
        for index in range(40):
            handler.emit(_record(f"held {index}"))

    handler.close()

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            json.loads(line)


def test_the_shipped_cap_is_what_the_incident_reported(tmp_path):
    """5,242,880 is the number the frozen log stopped 99 bytes short of."""
    assert LOG_MAX_BYTES == 5 * 1024 * 1024 == 5_242_880
