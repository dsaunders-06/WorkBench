"""The narrow slice of ib_async.IB's API IBAdapter depends on, defined as
our own Protocol so tests can inject a FakeIBClient without needing a real
socket connection or a running IB Gateway/TWS process.

Connection health is checked by polling isConnected()/reqCurrentTimeAsync()
(see ib_adapter.py's heartbeat loop) rather than subscribing to ib_async's
Event objects - simpler to model here and to fake in tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ib_async import AccountValue, Contract, Position
from ib_async.order import Order as IBOrder
from ib_async.order import Trade


class IBClientProtocol(Protocol):
    def isConnected(self) -> bool: ...

    async def connectAsync(
        self,
        host: str,
        port: int,
        clientId: int,
        timeout: float = 4.0,
        readonly: bool = False,
    ) -> None: ...

    def disconnect(self) -> None: ...

    async def reqCurrentTimeAsync(self) -> datetime: ...

    def placeOrder(self, contract: Contract, order: IBOrder) -> Trade: ...

    def cancelOrder(self, order: IBOrder, manualCancelOrderTime: str = "") -> Trade | None: ...

    def positions(self, account: str = "") -> list[Position]: ...

    def accountSummary(self, account: str = "") -> list[AccountValue]: ...

    async def reqHistoricalDataAsync(
        self,
        contract: Contract,
        endDateTime: object,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
    ) -> object: ...

    def reqMktData(
        self,
        contract: Contract,
        genericTickList: str = "",
        snapshot: bool = False,
        regulatorySnapshot: bool = False,
    ) -> object: ...
