"""Structured JSON logging with secret redaction.

Every log record is emitted as a single JSON line. The value of any secret
previously requested via security.get_secret() is redacted if it appears
in a log message, regardless of which record emits it.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from qat.security import known_secret_names

_REDACTED = "***REDACTED***"

LOG_DIRNAME = "logs"
LOG_FILENAME = "qat.log"
# Ten files of five megabytes: enough to cover several sessions of debate about
# what happened, without letting a chatty loop fill the disk.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 10
# How long to stop attempting a rename after one fails. Without this the
# handler retries a rename it already knows is failing on EVERY record.
ROLLOVER_RETRY_SECONDS = 60.0


class ResilientRotatingFileHandler(RotatingFileHandler):
    """A rotation failure must not take the log down with it.

    `RotatingFileHandler.doRollover` closes the stream, renames the file, then
    reopens. If the rename raises, the stream is left as None and `emit`'s
    except clause hands the record to `handleError`, which by default prints
    nothing anywhere the operator will look. **The application then logs
    nothing, for ever, and says so nowhere.**

    That is not theoretical. On Monday 24 August 2026 the log froze at
    5,242,781 bytes - 99 short of the 5 MiB cap - at 10:06:27, five minutes into
    the ASX open, and stayed frozen across a full application restart while the
    app went on trading normally and writing its ledgers. `scripts/watch_session.py`
    held the file open, and on Windows a plain `open()` does not grant
    delete-sharing, so `os.rename` failed with WinError 32 every time.

    It cost a wrong diagnosis: a feed that had recovered on its own looked hung,
    because the only evidence either way was a log that had stopped.

    **The trade this class makes: a log that grows past its cap is a far smaller
    problem than a log that stops.** So on failure it reopens the stream, keeps
    appending, and says loudly in the log itself what happened - once per
    cooldown, not once per record.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rollover_blocked_until = 0.0
        self.rollover_failures = 0
        # Failures we could not even announce. Should stay zero; if it does
        # not, the log is unwritable rather than merely unrotatable.
        self.unannounced_failures = 0

    def shouldRollover(self, record: logging.LogRecord) -> int:  # noqa: N802 - stdlib spelling
        if time.monotonic() < self._rollover_blocked_until:
            # Known to be failing. Reopen if a previous attempt left it closed,
            # and keep writing to the current file rather than trying a rename
            # per record - which is a syscall storm at the exact moment the
            # application is least able to afford one.
            if self.stream is None:
                self.stream = self._open()
            return 0
        return super().shouldRollover(record)

    def doRollover(self) -> None:  # noqa: N802 - stdlib spelling
        try:
            super().doRollover()
        except OSError as error:
            self.rollover_failures += 1
            self._rollover_blocked_until = time.monotonic() + ROLLOVER_RETRY_SECONDS
            # THE LINE THAT KEEPS THE LOG ALIVE. doRollover set stream to None
            # before the rename it failed on; without this the handler never
            # writes again.
            if self.stream is None:
                self.stream = self._open()
            self._announce_failure(error)

    def _announce_failure(self, error: OSError) -> None:
        """Write the failure into the log directly, not through `logging`.

        Going back through the logging module from inside a handler risks
        recursing into the handler that is currently failing, so the record is
        formatted and written by hand.
        """
        record = logging.LogRecord(
            name=__name__,
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg=(
                "LOG ROTATION FAILED (%s: %s). The log is being kept open and will grow "
                "past its %d-byte cap rather than going silent, and this is failure %d. "
                "On Windows this is usually another process holding the file open - "
                "scripts/watch_session.py did exactly that on 24 August 2026 and blinded "
                "the log for a whole session. Retrying in %.0fs."
            ),
            args=(
                type(error).__name__,
                error,
                self.maxBytes,
                self.rollover_failures,
                ROLLOVER_RETRY_SECONDS,
            ),
            exc_info=None,
        )
        try:
            if self.stream is not None:
                self.stream.write(self.format(record) + self.terminator)
                self.stream.flush()
        except Exception:  # noqa: BLE001 - a failed alarm must not raise into emit
            # COUNTED, not passed. If even the alarm cannot be written then the
            # log is beyond saving for now, and a bare `pass` would leave that
            # fact nowhere at all - which is the exact shape of the defect this
            # whole class exists to fix. The counter is at least readable from
            # a debugger or a test.
            self.unannounced_failures += 1


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            record.args = self._redact_args(record.args)
        return True

    def _redact_args(
        self, args: tuple[object, ...] | Mapping[str, object]
    ) -> tuple[object, ...] | Mapping[str, object]:
        """Redacts string arguments and leaves every other type untouched.

        Coercing all arguments to str looks harmless but silently destroys
        numeric format specifiers: "%.2f" % "100000.0" raises TypeError, the
        record then fails to format, and the line is *dropped* in favour of a
        stderr traceback. Only a str can contain a secret anyway, so there is
        nothing to gain by stringifying the rest.

        Mapping args (the %(name)s style) are preserved as a mapping - the
        previous tuple() comprehension iterated a dict's keys and threw the
        values away.
        """
        if isinstance(args, Mapping):
            return {
                key: self._redact(value) if isinstance(value, str) else value
                for key, value in args.items()
            }
        return tuple(self._redact(a) if isinstance(a, str) else a for a in args)

    def _redact(self, text: str) -> str:
        for secret in known_secret_names():
            value = None
            try:
                from qat.security import get_secret

                value = get_secret(secret)
            except Exception:  # pragma: no cover - defensive
                value = None
            if value:
                text = text.replace(value, _REDACTED)
        return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", data_dir: str | Path | None = None) -> None:
    """Log to stdout and, when a data_dir is given, to a rotating file.

    The file handler is not optional in practice (spec M20). The packaged
    build is --windowed, which means it has no console, so a stdout-only
    configuration discarded every line the moment the application was run the
    way it is actually shipped: session transitions, degraded-feed warnings,
    staleness, kill-switch trips and sign-off rejections all went nowhere. The
    logging was never the problem; nothing was reading it.

    Both handlers carry the redaction filter. A secret must not reach the
    console, and it must certainly not be written to a file that outlives the
    process.
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactSecretsFilter())
    root.addHandler(handler)

    if data_dir is None:
        return

    try:
        log_dir = Path(data_dir) / LOG_DIRNAME
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = ResilientRotatingFileHandler(
            log_dir / LOG_FILENAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(RedactSecretsFilter())
        root.addHandler(file_handler)
    except OSError:
        # An unwritable log directory must not stop the application starting.
        # stdout still has a handler, so this degrades rather than fails.
        root.warning("Could not open the log file in %s; logging to stdout only", data_dir)
    else:
        root.info("Logging to %s", log_dir / LOG_FILENAME)
