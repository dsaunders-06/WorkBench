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
    """Still true, and still the point - only the reason has moved. Without an
    EventBus the adapter cannot be built at all, and the refusal says so rather
    than handing back a simulator."""
    with pytest.raises(BrokerNotAvailableError):
        resolve_broker(Settings(broker="ibkr"))


def test_ibkr_no_longer_refuses_over_a_capability_the_operator_accepted() -> None:
    """This test has changed twice, and both times because the CODE changed
    truthfully underneath it.

    It first hardcoded `resting_stops` as a capability IBKR lacked, and failed
    when Task 4 implemented it - the derived message had already stopped
    saying it. Rewritten to derive the list, it then failed again when the
    wiring landed, because `resolve_broker` no longer refuses over
    capabilities at all: `announcements` is the only one left, IBKR publishes
    no structured corporate-action feed, and Task 5 DECIDED to accept that gap
    and report it as UNAVAILABLE. Refusing to start over a capability the
    operator deliberately accepted would contradict the decision.

    So what is asserted now is the current contract - the gap is STATED, not
    refused - and the refusal that remains is about the EventBus, which is a
    real construction requirement rather than a policy.
    """
    missing = inspect_adapter(KNOWN_ADAPTERS()["ibkr"]).missing_optional
    assert missing == {"announcements"}, (
        f"the accepted gap changed to {sorted(missing)} - re-read Task 5's decision before "
        "assuming this is still only about corporate actions"
    )
