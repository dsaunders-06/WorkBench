"""Error 383 carries the broker's real size limit. Nothing was reading it.

`broker_max_order_shares` is a BELIEF - the limit lives in TWS's Precautionary
Settings and is not queryable through the API. A belief with nothing checking it
drifts silently, which is how a 790-share order met a 500-share limit.

⚠️ THE AUDIT NEVER APPLIES WHAT IT PARSES. A rail that depended on IBKR's error
wording staying stable would be one string change away from doing nothing while
still looking healthy. It warns; the configured value still governs.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter

_MESSAGE = (
    "The order size of 790 exceeds the Size Limit of 500 as set in the "
    "Presets for this instrument."
)


class _Bus:
    async def publish(self, event: object) -> None:
        return None


def _adapter(ceiling: int | None) -> IBAdapter:
    settings = Settings(_env_file=None, market="ASX", broker_max_order_shares=ceiling)
    return IBAdapter(_Client(), _Bus(), settings=settings)


class _Client:
    def isConnected(self) -> bool:
        return True


def test_an_unset_ceiling_is_named_with_the_number_to_set(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING):
        _adapter(None)._audit_size_limit(_MESSAGE)

    assert "500" in caplog.text
    assert "UNSET" in caplog.text


def test_a_disagreeing_ceiling_is_reported_with_both_numbers(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING):
        _adapter(400)._audit_size_limit(_MESSAGE)

    assert "400" in caplog.text and "500" in caplog.text


def test_a_matching_ceiling_says_nothing(caplog: Any) -> None:
    """60 rejections a session would bury the one that matters."""
    with caplog.at_level(logging.WARNING):
        _adapter(500)._audit_size_limit(_MESSAGE)

    assert caplog.text == ""


def test_wording_the_audit_cannot_parse_is_silent_rather_than_wrong(caplog: Any) -> None:
    """⚠️ IBKR may reword this at any time. The audit must then say NOTHING -
    not guess, and not raise inside an error handler."""
    with caplog.at_level(logging.WARNING):
        _adapter(500)._audit_size_limit("Your order was rejected for size reasons.")

    assert caplog.text == ""


@pytest.mark.parametrize("configured", [None, 400, 500])
def test_the_audit_never_changes_the_configured_value(configured: int | None) -> None:
    """The belief is what the sizer trims against; parsing must not rewrite it."""
    adapter = _adapter(configured)
    adapter._audit_size_limit(_MESSAGE)

    assert adapter.settings.broker_max_order_shares == configured
