"""IB holdings and marks must be identified by account and qualified conId."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from qat.data.broker.ib_adapter import IBAdapter


def _contract(con_id: int, *, sec_type: str = "STK", currency: str = "AUD") -> SimpleNamespace:
    return SimpleNamespace(
        symbol="BHP",
        conId=con_id,
        secType=sec_type,
        exchange="SMART",
        primaryExchange="ASX",
        currency=currency,
    )


def _position(account: str, contract: SimpleNamespace, quantity: float) -> SimpleNamespace:
    return SimpleNamespace(account=account, contract=contract, position=quantity, avgCost=60.0)


def _adapter(rows: list[SimpleNamespace], marks: list[SimpleNamespace]) -> IBAdapter:
    async def qualify(contract: object) -> list[SimpleNamespace]:
        return [_contract(1001)]

    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = SimpleNamespace(
        positions=lambda: rows,
        portfolio=lambda: marks,
        qualifyContractsAsync=qualify,
    )
    adapter.settings = SimpleNamespace(
        market="ASX", ibkr_account_id="DU123", ibkr_call_timeout_seconds=1
    )
    adapter._qualified_contracts = {}
    return adapter


@pytest.mark.asyncio
async def test_duplicate_callback_is_one_qat_holding() -> None:
    bhp = _position("DU123", _contract(1001), 9)
    adapter = _adapter([bhp, bhp], [])

    holdings = await adapter.positions()

    assert len(holdings) == 1
    assert holdings[0].quantity == 9
    assert holdings[0].qat_holding is True
    assert holdings[0].identity == ("DU123", 1001)


@pytest.mark.asyncio
async def test_same_symbol_other_conid_cannot_borrow_qat_mark() -> None:
    qat = _position("DU123", _contract(1001), 9)
    foreign = _position("DU123", _contract(2002), 18)
    marks = [
        SimpleNamespace(account="DU123", contract=_contract(1001), marketPrice=61.0),
        SimpleNamespace(account="DU123", contract=_contract(2002), marketPrice=77.0),
    ]
    holdings = await _adapter([qat, foreign], marks).positions()

    assert [(row.identity, row.qat_holding) for row in holdings] == [
        (("DU123", 1001), True),
        (("DU123", 2002), False),
    ]
    assert [row.current_price for row in holdings] == [61.0, 77.0]
    assert all(row.mark_observed_at is not None for row in holdings)


@pytest.mark.asyncio
async def test_fresh_position_poll_does_not_retimestamp_an_unchanged_old_mark() -> None:
    mark = SimpleNamespace(account="DU123", contract=_contract(1001), marketPrice=61.0)
    adapter = _adapter([_position("DU123", _contract(1001), 9)], [mark])
    old = datetime(2026, 10, 1, tzinfo=UTC)
    adapter._mark_cache = {("DU123", 1001, ""): (61.0, old)}

    holdings = await adapter.positions()

    assert holdings[0].mark_observed_at == old


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account", "sec_type", "currency"),
    [
        ("DU999", "STK", "AUD"),
        ("DU123", "OPT", "AUD"),
        ("DU123", "STK", "USD"),
    ],
)
async def test_other_account_nonstock_and_non_aud_are_foreign(
    account: str, sec_type: str, currency: str
) -> None:
    row = _position(account, _contract(1001, sec_type=sec_type, currency=currency), 9)
    holdings = await _adapter([row], []).positions()

    assert len(holdings) == 1
    assert holdings[0].qat_holding is False
    assert holdings[0].account == account
    assert holdings[0].sec_type == sec_type
    assert holdings[0].currency == currency
