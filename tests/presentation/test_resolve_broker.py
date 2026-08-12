"""A configured broker must never silently become a different one.

resolve_broker's own docstring says quietly trading against a simulator while
believing you are connected to a real account "would be worse than either" -
and until this test, the ibkr branch did exactly that.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.presentation.runtime import BrokerNotAvailableError, resolve_broker


def test_mock_is_returned_when_mock_is_configured() -> None:
    assert isinstance(resolve_broker(Settings(broker="mock")), MockBroker)


def test_ibkr_does_not_silently_resolve_to_a_mock() -> None:
    with pytest.raises(BrokerNotAvailableError):
        resolve_broker(Settings(broker="ibkr"))


def test_the_refusal_names_the_capabilities_ibkr_lacks() -> None:
    """Test the claim, not the arithmetic. The message asserts something about
    the adapter; if it stops being true the message must stop saying it."""
    with pytest.raises(BrokerNotAvailableError) as raised:
        resolve_broker(Settings(broker="ibkr"))
    message = str(raised.value)
    assert "resting_stops" in message
    assert "Gateway" in message
    assert "MockBroker" in message
