"""Secret redaction must not destroy log records (spec M1, fixed M17).

The filter used to coerce every log argument to str. That looks harmless
until a message uses a numeric format specifier: "%.2f" % "100000.0" raises
TypeError, the record fails to format, and the line is *dropped* in favour
of a stderr traceback. It was caught in a packaged run, where
EquityMonitor's "day-start equity recorded as %.2f" vanished.
"""

from __future__ import annotations

import json
import logging

from qat.logging import JsonFormatter, RedactSecretsFilter


def _record(msg: str, args: object) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, "f.py", 1, msg, args, None)  # type: ignore[arg-type]


def test_numeric_arguments_survive_the_filter_and_format():
    record = _record("day-start equity recorded as %.2f", (100_000.0,))

    RedactSecretsFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "day-start equity recorded as 100000.00"


def test_mixed_argument_types_each_keep_their_own_formatting():
    record = _record("%s cost=%.2f attempt=%d", ("AAPL", 1234.5, 3))

    RedactSecretsFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "AAPL cost=1234.50 attempt=3"


def test_mapping_arguments_are_preserved_not_reduced_to_their_keys():
    """tuple(dict) yields the keys and throws the values away."""
    record = _record("%(symbol)s at %(price).2f", {"symbol": "MSFT", "price": 410.5})

    RedactSecretsFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "MSFT at 410.50"


def test_secrets_in_string_arguments_are_still_redacted(monkeypatch):
    monkeypatch.setattr("qat.logging.known_secret_names", lambda: frozenset({"TOKEN"}))
    monkeypatch.setattr("qat.security.get_secret", lambda name: "hunter2")
    record = _record("token=%s size=%.1f", ("hunter2", 2.5))

    RedactSecretsFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert "hunter2" not in payload["message"]
    assert "***REDACTED***" in payload["message"]
    assert "2.5" in payload["message"]  # the numeric arg still formatted


def test_secrets_in_the_message_itself_are_still_redacted(monkeypatch):
    monkeypatch.setattr("qat.logging.known_secret_names", lambda: frozenset({"TOKEN"}))
    monkeypatch.setattr("qat.security.get_secret", lambda name: "hunter2")
    record = _record("connecting with hunter2", None)

    RedactSecretsFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert "hunter2" not in payload["message"]
