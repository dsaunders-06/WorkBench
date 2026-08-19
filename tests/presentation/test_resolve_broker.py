"""A configured broker must never silently become a different one.

resolve_broker's own docstring says quietly trading against a simulator while
believing you are connected to a real account "would be worse than either" -
and until this test, the ibkr branch did exactly that.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.capabilities import KNOWN_ADAPTERS, inspect_adapter
from qat.data.broker.mock_broker import MockBroker
from qat.presentation.runtime import BrokerNotAvailableError, resolve_broker


def test_mock_is_returned_when_mock_is_configured() -> None:
    assert isinstance(resolve_broker(Settings(broker="mock")), MockBroker)


def test_ibkr_does_not_silently_resolve_to_a_mock() -> None:
    with pytest.raises(BrokerNotAvailableError):
        resolve_broker(Settings(broker="ibkr"))


def test_the_refusal_names_the_capabilities_ibkr_lacks() -> None:
    """Test the claim, not the arithmetic. The message asserts something about
    the adapter; if it stops being true the message must stop saying it.

    This named `resting_stops` outright until Stage 1 Task 4 implemented it,
    and then failed - correctly. The message is derived from what the adapter
    actually lacks, so it had already stopped saying it; the hardcoded name was
    the stale half. Derived here too, for the same reason `handoff_state.py`
    exists: a hand-maintained copy of a derived fact is a defect waiting for
    the fact to change.
    """
    missing = inspect_adapter(KNOWN_ADAPTERS()["ibkr"]).missing_optional
    assert missing, "IBKR now implements everything - this test has nothing left to check"

    with pytest.raises(BrokerNotAvailableError) as raised:
        resolve_broker(Settings(broker="ibkr"))
    message = str(raised.value)

    for capability in missing:
        assert capability in message, f"the refusal does not mention missing {capability}"
    assert "Gateway" in message
    assert "MockBroker" in message
