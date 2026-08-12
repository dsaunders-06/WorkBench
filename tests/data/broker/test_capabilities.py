"""The broker port's capabilities, asserted as properties rather than counts.

Deliberately no "IBAdapter is missing exactly four" assertion. This project
lost that argument four times in three days with hand-maintained counts; the
count belongs in the script's output, where it is derived every time it is
read. What is asserted here is what must stay TRUE as the count changes.
"""

from __future__ import annotations

import pytest

from qat.data.broker.capabilities import (
    CORE,
    KNOWN_ADAPTERS,
    OPTIONAL,
    inspect_adapter,
    protocol_methods,
    unclassified,
)


def test_every_protocol_method_is_classified() -> None:
    """A method added to BrokerAdapter and classified nowhere is a capability
    nobody audited. M80's register pattern: the test is the thing that stops
    the register drifting from what it registers."""
    assert unclassified() == frozenset(), (
        "these BrokerAdapter methods are neither CORE nor OPTIONAL, so nothing "
        f"says what breaks without them: {sorted(unclassified())}"
    )


def test_classification_covers_nothing_that_is_not_on_the_protocol() -> None:
    stale = (CORE | frozenset(OPTIONAL)) - protocol_methods()
    assert stale == frozenset(), f"classified but no longer on the Protocol: {sorted(stale)}"


@pytest.mark.parametrize("method", sorted(OPTIONAL))
def test_every_optional_capability_names_what_is_lost(method: str) -> None:
    """An optional capability whose absence is not described is exactly the
    silence this module exists to end."""
    consequence = OPTIONAL[method]
    assert consequence.strip(), f"{method} has no stated consequence"
    assert len(consequence) > 30, f"{method}'s consequence is too vague to act on: {consequence!r}"


@pytest.mark.parametrize("name", sorted(KNOWN_ADAPTERS()))
def test_no_known_adapter_is_missing_a_core_capability(name: str) -> None:
    """Core is the trading path itself. An adapter missing any of it cannot be
    a broker, and must never be resolvable as one."""
    caps = inspect_adapter(KNOWN_ADAPTERS()[name])
    assert (
        caps.missing_core == frozenset()
    ), f"{name} cannot trade: missing {sorted(caps.missing_core)}"
    assert caps.can_trade


def test_a_missing_optional_reports_its_consequence() -> None:
    """The whole point: absence must produce a sentence, not a silence."""
    caps = inspect_adapter(KNOWN_ADAPTERS()["ibkr"])
    if not caps.missing_optional:
        pytest.skip("IBAdapter now implements the whole protocol - the gap this guards is closed")
    assert len(caps.disabled) == len(caps.missing_optional)
    assert all(sentence.strip() for sentence in caps.disabled)
