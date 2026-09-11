"""IBKR's own commission, checked against the model the ledger records (M175).

The ledger records the MODELLED charge, and that is deliberate: measured
11 September, IBKR's commission equals the model on 17 of 17 logged orders, and
a report only arrives for fills the app is connected for - so actuals could
never cover every row. What was wrong was that the actuals were thrown away.
Now every one the app hears about checks the model, in its own file joined to
the ledger on `order_id`, because a report arrives AFTER the fill is recorded
and marking the ledger row would mean amending rows already written.
"""

from __future__ import annotations

import csv
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qat.config import Settings
from qat.data.broker.adapter import BrokerCommission
from qat.domain import market_calendar as mc
from qat.domain.backtester.costs import CostModel

logger = logging.getLogger(__name__)

COMMISSION_CHECKS_FILENAME = "commission_checks.csv"
_FIELDS = (
    "checked_at",
    "order_id",
    "symbol",
    "side",
    "quantity",
    "notional",
    "actual",
    "modelled",
    "currency",
    "agrees",
)
# One cent. The model and IBKR agreed to the cent on every order measured.
_TOLERANCE = 0.01


@dataclass(frozen=True, slots=True)
class CommissionCheck:
    order_id: str
    symbol: str
    side: str
    quantity: float
    notional: float
    actual: float
    modelled: float
    currency: str
    agrees: bool


class CommissionAuditor:
    def __init__(
        self,
        data_dir: str | Path,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = Path(data_dir) / COMMISSION_CHECKS_FILENAME
        self._costs = CostModel.from_settings(settings)
        self._currency = mc.currency_for(settings.market)
        self._clock = clock
        self._lock = threading.Lock()
        # ib_async loads completed orders at connect and re-emits their
        # commission reports, and the adapter's record of what it already
        # reported lives in memory only - so every restart re-checked every
        # order still in IBKR's completed list and appended it again. The
        # file is the memory that survives.
        self._recorded = self._recorded_order_ids()

    def _recorded_order_ids(self) -> set[str]:
        """Order ids already in the file. Missing or unreadable: none - a
        duplicate row is a nuisance, a check lost to a bad file is not."""
        try:
            with self.path.open(newline="", encoding="utf-8") as handle:
                return {row["order_id"] for row in csv.DictReader(handle) if row.get("order_id")}
        except FileNotFoundError:
            return set()
        except (OSError, ValueError, KeyError, csv.Error):
            logger.warning(
                "Could not read %s to find the orders already checked - a restart may record "
                "some of them again",
                self.path,
                exc_info=True,
            )
            return set()

    def check(self, report: BrokerCommission) -> CommissionCheck:
        """Compare, record, and say so. Never raises: it is called from
        ib_async's own dispatch, where an exception would vanish.

        An order already in the file is compared and returned, but not
        appended again and not announced again (DEBUG only)."""
        modelled = self._costs.charge(report.notional)
        agrees = (
            abs(report.commission - modelled) <= _TOLERANCE and report.currency == self._currency
        )
        result = CommissionCheck(
            order_id=report.order_id,
            symbol=report.symbol,
            side=report.side,
            quantity=report.quantity,
            notional=report.notional,
            actual=report.commission,
            modelled=modelled,
            currency=report.currency,
            agrees=agrees,
        )
        with self._lock:
            already = report.order_id in self._recorded
        if already:
            logger.debug(
                "Commission report for order %s (%s %s) is already in %s - a redelivery at "
                "connect, not recorded again",
                report.order_id,
                report.side,
                report.symbol,
                self.path.name,
            )
            return result
        self._append(result)
        if agrees:
            logger.info(
                "COMMISSION VERIFIED: %s %s %g (order %s) - IBKR charged %.2f %s, the model "
                "says %.2f",
                report.side,
                report.symbol,
                report.quantity,
                report.order_id,
                report.commission,
                report.currency,
                modelled,
            )
        else:
            logger.warning(
                "COMMISSION DISAGREES: %s %s %g (order %s) - IBKR charged %.2f %s, the model "
                "says %.2f %s. The ledger records the MODEL, so this trade's costs are wrong by "
                "the difference until it is explained (M175).",
                report.side,
                report.symbol,
                report.quantity,
                report.order_id,
                report.commission,
                report.currency,
                modelled,
                self._currency,
            )
        return result

    def _append(self, result: CommissionCheck) -> None:
        row = {
            "checked_at": self._clock().isoformat(timespec="seconds"),
            "order_id": result.order_id,
            "symbol": result.symbol,
            "side": result.side,
            "quantity": round(result.quantity, 6),
            "notional": round(result.notional, 2),
            "actual": round(result.actual, 6),
            "modelled": round(result.modelled, 6),
            "currency": result.currency,
            "agrees": str(result.agrees),
        }
        try:
            with self._lock:
                new = not self.path.exists()
                with self.path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
                    if new:
                        writer.writeheader()
                    writer.writerow(row)
                self._recorded.add(result.order_id)
        except OSError:
            logger.exception("Could not record the commission check for order %s", result.order_id)
