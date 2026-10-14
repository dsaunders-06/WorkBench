"""The shared account snapshot preserves broker contract identity."""

from __future__ import annotations

import pytest

from qat.data.broker.account_poller import AccountPoller
from qat.data.broker.adapter import AccountSummary, Position


class Broker:
    async def account(self) -> AccountSummary:
        return AccountSummary(100_000, 100_000, 100_000)

    async def positions(self) -> list[Position]:
        managed = Position("BHP.AX", 9, 60, account="DU1", con_id=1001)
        foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)
        return [managed, managed, foreign]


@pytest.mark.asyncio
async def test_snapshot_deduplicates_by_account_and_conid_and_exposes_foreign() -> None:
    snapshot = await AccountPoller(Broker()).snapshot()  # type: ignore[arg-type]

    assert [(row.identity, row.quantity) for row in snapshot.positions] == [
        (("DU1", 1001), 9),
        (("DU1", 2002), 18),
    ]
    assert [row.identity for row in snapshot.qat_positions] == [("DU1", 1001)]
    assert [row.identity for row in snapshot.foreign_positions] == [("DU1", 2002)]
