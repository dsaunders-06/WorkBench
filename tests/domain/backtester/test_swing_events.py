"""Historical swing market events use exact immutable facts."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_events import (
    CashDividendEvent,
    DelistingEvent,
    SplitEvent,
    SuspensionEvent,
    SymbolChangeEvent,
)


def test_historical_market_events_are_frozen_and_decimal_or_rational() -> None:
    split = SplitEvent("split-1", "BHP.AX", date(2026, 1, 6), 2, 1)
    dividend = CashDividendEvent(
        "div-1",
        "BHP.AX",
        date(2026, 1, 7),
        date(2026, 1, 5),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 20),
        Decimal("0.25"),
    )
    symbol = SymbolChangeEvent("symbol-1", "OLD.AX", date(2026, 1, 8), "NEW.AX")
    suspension = SuspensionEvent("halt-1", "BHP.AX", date(2026, 1, 9), None)
    delisting = DelistingEvent("delist-1", "BHP.AX", date(2026, 1, 10), Decimal("0"))

    assert split.numerator == 2 and split.denominator == 1
    assert dividend.amount_per_share == Decimal("0.25")
    assert symbol.new_symbol == "NEW.AX"
    assert suspension.resume_session is None
    assert delisting.realizable_price == Decimal("0")
    with pytest.raises(FrozenInstanceError):
        split.numerator = 3  # type: ignore[misc]


def test_invalid_market_event_facts_are_rejected() -> None:
    with pytest.raises(ValueError):
        SplitEvent("bad", "BHP.AX", date(2026, 1, 6), 0, 1)
    with pytest.raises(ValueError):
        DelistingEvent("bad", "BHP.AX", date(2026, 1, 10), Decimal("NaN"))
