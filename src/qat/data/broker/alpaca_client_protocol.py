"""The narrow slice of alpaca-py's TradingClient that AlpacaAdapter depends
on, defined as our own Protocol so tests can inject a fake without real API
credentials or network access - the same seam ib_client_protocol.py provides
for IBKR.

Deliberately typed against `object` returns rather than alpaca's concrete
models: the adapter reads a handful of attributes off them (see
alpaca_adapter.py), and pinning the full model types here would couple this
seam to alpaca's model layer without making the fakes any safer.
"""

from __future__ import annotations

from typing import Any, Protocol


class AlpacaClientProtocol(Protocol):
    def get_account(self) -> Any: ...

    # Any, not list[Any]: alpaca types this as list[Position] | dict[str, Any]
    # to cover its raw_data mode, which this adapter never enables. Narrowing
    # it here would make the real client fail to match structurally.
    def get_all_positions(self) -> Any: ...

    def submit_order(self, order_data: Any) -> Any: ...

    def cancel_order_by_id(self, order_id: str) -> None: ...

    def get_order_by_id(self, order_id: str) -> Any: ...
