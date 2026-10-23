"""Contract and paper-session guards for IBKR read-only history clients.

This module deliberately imports no QAT broker order or OMS type.
"""

from __future__ import annotations

from collections.abc import Sequence

from ib_async import Stock

from qat.config import Settings
from qat.data.symbols import to_ibkr

READONLY_CLIENT_ID = 99
_LIVE_PORTS = {4001, 7496}


def connection_target(settings: Settings) -> tuple[str, int, int]:
    if not settings.is_live and settings.ibkr_port in _LIVE_PORTS:
        raise ValueError("paper history cannot connect to a live IBKR port")
    return settings.ibkr_host, settings.ibkr_port, READONLY_CLIENT_ID


def check_paper_account(accounts: Sequence[str]) -> None:
    if any(not account.upper().startswith("DU") for account in accounts):
        raise ValueError("read-only history requires a paper account")


def to_asx_stock_contract(symbol: str) -> Stock:
    if not symbol.endswith(".AX"):
        raise ValueError("read-only history requires an ASX equity symbol")
    return Stock(to_ibkr(symbol), "SMART", "AUD", primaryExchange="ASX")
