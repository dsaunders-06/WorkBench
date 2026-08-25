"""ib_async must not drown the app's own log (item 35).

On 25 August ordinary order activity rotated the 5 MiB log THREE TIMES IN
UNDER THREE MINUTES - 10:30:27, 10:32:20, 10:32:55 - and the lines recording
the day's five entries were one rotation from deletion when they were read.

`ib_async.wrapper` logs every `orderStatus` at INFO with the entire `Trade`
repr, including its full `TradeLogEntry` history. That grows as each order
accumulates status changes, so the noise scales with the number of live
brackets, exactly when a session is most worth diagnosing.

Same consequence as M137 - no log to diagnose from - by the opposite
mechanism. M137 was rotation FAILING; this is rotation THRASHING, and it
evicts precisely the app-level lines a live incident needs.

Quietened to WARNING rather than silenced: the library's genuine warnings and
errors (1100/1102 disconnects, order rejections) are exactly what IS wanted.
"""

from __future__ import annotations

import logging

from qat.logging import NOISY_LIBRARY_LOGGERS, configure_logging


def test_ib_async_wrapper_is_quietened(tmp_path):
    configure_logging(level=logging.INFO, data_dir=str(tmp_path))
    assert logging.getLogger("ib_async.wrapper").level >= logging.WARNING


def test_its_warnings_and_errors_still_get_through(tmp_path):
    """Quietened, not silenced. A 1100 disconnect must still reach the log."""
    configure_logging(level=logging.INFO, data_dir=str(tmp_path))
    assert logging.getLogger("ib_async.wrapper").isEnabledFor(logging.WARNING)
    assert logging.getLogger("ib_async.wrapper").isEnabledFor(logging.ERROR)


def test_the_apps_own_loggers_are_untouched(tmp_path):
    """The point is to keep the app's own lines, not to lose them too."""
    configure_logging(level=logging.INFO, data_dir=str(tmp_path))
    assert logging.getLogger("qat.domain.oms.oms").isEnabledFor(logging.INFO)


def test_the_noisy_set_is_named_not_scattered(tmp_path):
    """One list, so the next noisy library is a one-line change and the
    decision is visible rather than buried in a call."""
    assert "ib_async.wrapper" in NOISY_LIBRARY_LOGGERS
