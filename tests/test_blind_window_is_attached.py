"""The blind-window filter must be on the handler that writes the LOG (item 67).

M151 shipped `BlindWindowFilter` and it worked - the unit tests proved
`filter()` suppresses and counts. **Nothing proved it was ATTACHED to the
handler that writes `qat.log`.** It was added to the stdout handler only, so on
28 August:

    10:20:36  yfinance market data has recovered - 678 per-symbol 'possibly
              delisted' error(s) were suppressed while the feed was inside its
              known delay window

    lines in the blind window : 797
    delisting errors IN THE LOG: 774

⚠️ **That is worse than the filter not working.** It suppressed on a stream
nobody reads and then ASSERTED the suppression on the line an operator would use
to conclude the log was clean. A missing fix is a gap; a fix that reports work
it did not do is a false assurance.

The packaged build is `--windowed` and has no console at all, so the stdout
handler is the one that discards everything - `configure_logging`'s own
docstring says exactly that.

⚠️ **This is item 59's mistake, repeated.** A guard built at a layer no path
from the defect reaches. So these tests drive `configure_logging` and inspect
the handlers it actually installs, never the filter object on its own.
"""

from __future__ import annotations

import logging

import pytest

from qat.logging import (
    BLIND_WINDOW_FILTER,
    BlindWindowFilter,
    JsonFormatter,
    configure_logging,
)


def _app_handlers(root: logging.Logger) -> list[logging.Handler]:
    """The handlers THIS APPLICATION installs, identified by the formatter
    `configure_logging` gives every one of them.

    ⚠️ Not `root.handlers`. pytest injects its own `LogCaptureHandler`, and
    asserting over everything on the root logger would fail on a handler the app
    never created - which is a test-environment artefact, not a defect. Narrowed
    to what the app owns rather than relaxed to "at least one", because "at
    least one" is exactly the assertion that would have passed while the filter
    sat on stdout alone.
    """
    return [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]


_DELISTED = "$PMV.AX: possibly delisted; no price data found  (period=1d)"


@pytest.fixture
def configured(tmp_path):
    root = logging.getLogger()
    saved = list(root.handlers)
    configure_logging(data_dir=tmp_path)
    yield root
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved:
        root.addHandler(handler)


def test_every_handler_carries_the_filter(configured) -> None:
    """The wiring, which is what was missing. Asserted over ALL handlers rather
    than 'at least one', because the one it was on is the one that is discarded
    in the packaged build."""
    handlers = _app_handlers(configured)
    assert len(handlers) >= 2, "expected a stdout handler AND a file handler"

    for handler in handlers:
        assert any(isinstance(f, BlindWindowFilter) for f in handler.filters), (
            f"{type(handler).__name__} does not carry BlindWindowFilter, so the delisting "
            f"storm reaches whatever it writes (item 67)"
        )


def test_the_file_handler_specifically_carries_it(configured) -> None:
    """Named separately because it is THE one that matters: the packaged build
    is --windowed and has no console, so stdout is discarded entirely."""
    from logging.handlers import RotatingFileHandler

    file_handlers = [h for h in _app_handlers(configured) if isinstance(h, RotatingFileHandler)]
    assert file_handlers, "no file handler was installed"

    for handler in file_handlers:
        assert any(isinstance(f, BlindWindowFilter) for f in handler.filters)


def test_one_record_is_counted_once_however_many_handlers_see_it() -> None:
    """⚠️ The bug the fix would have introduced. `filter()` runs once PER
    HANDLER, so with the filter correctly on both, a single suppressed record
    would increment the count TWICE and the recovery line would report double
    what it dropped.

    Fixing the attachment without this would have replaced a false assurance
    with a wrong number, which is not obviously better."""
    blind = BlindWindowFilter()
    blind.blind = True
    record = logging.LogRecord("yfinance", logging.ERROR, __file__, 1, _DELISTED, None, None)

    assert blind.filter(record) is False  # stdout handler
    assert blind.filter(record) is False  # file handler

    assert blind.suppressed == 1, "one record suppressed twice must count once"


def test_two_different_records_still_count_twice() -> None:
    """The other direction - the de-duplication must key on the RECORD, not
    become a latch that only ever counts one."""
    blind = BlindWindowFilter()
    blind.blind = True

    for _ in range(3):
        blind.filter(
            logging.LogRecord("yfinance", logging.ERROR, __file__, 1, _DELISTED, None, None)
        )

    assert blind.suppressed == 3


def test_the_shared_instance_is_the_one_installed(configured) -> None:
    """`BLIND_WINDOW_FILTER` is a module singleton because the FEED sets
    `blind` on it and the logging config attaches it. Two instances would mean
    the flag and the filter were different objects, and nothing would ever
    suppress."""
    for handler in _app_handlers(configured):
        installed = [f for f in handler.filters if isinstance(f, BlindWindowFilter)]
        assert installed and installed[0] is BLIND_WINDOW_FILTER
