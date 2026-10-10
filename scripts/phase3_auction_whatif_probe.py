"""Preview an ASX opening-auction limit buy on the verified paper Gateway.

This is a what-if request only. It cannot transmit an order. Keep the raw
response and API errors outside Git so the broker's actual rejection or
acceptance can be reviewed before the separately staged paper order probe.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from phase3_daily_history_probe import (  # noqa: E402
    _checked_account,
    _paper_target,
    _safe_output_dir,
    _write_raw,
)

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_translate import to_ib_contract  # noqa: E402
from qat.data.broker.ticks import tick_size  # noqa: E402


def _order_size(reference_price: Decimal, limit: Decimal) -> int:
    if reference_price <= 0 or limit <= 0:
        raise ValueError("prices must be positive")
    if limit % tick_size(limit, "ASX"):
        raise ValueError("limit is not on the ASX tick grid")
    quantity = int((Decimal("500") / reference_price).to_integral_value(rounding=ROUND_CEILING))
    if quantity * limit > Decimal("800"):
        raise ValueError("limit implies more than AUD 800 maximum cost; choose a nearer limit")
    return quantity


async def _run(
    symbol: str, reference_price: Decimal, limit: Decimal, route: str, out_dir: Path
) -> int:
    from ib_async import IB, LimitOrder

    if symbol not in {"BHP.AX", "CBA.AX", "SUN.AX", "MFG.AX", "WGX.AX"}:
        raise ValueError("symbol must be one of the five authorized sample stocks")
    quantity = _order_size(reference_price, limit)
    settings = Settings(
        data_dir=tempfile.mkdtemp(prefix="qat-phase3-whatif-"),
        trading_mode="paper",
        market="ASX",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
    )
    host, port, client_id = _paper_target(settings)
    client = IB()
    await client.connectAsync(host, port, clientId=client_id + 1, readonly=False, timeout=15)
    try:
        _checked_account(client)
        errors: list[dict[str, str]] = []

        def record_error(*values: object) -> None:
            errors.append({"at_utc": datetime.now(UTC).isoformat(), "arguments_repr": repr(values)})

        client.errorEvent += record_error
        _checked_account(client)
        qualified = await client.qualifyContractsAsync(to_ib_contract(symbol, "ASX"))
        if len(qualified) != 1:
            raise ValueError(f"expected one qualified contract, received {len(qualified)}")
        qualified[0].exchange = route
        order = LimitOrder("BUY", quantity, float(limit), tif="OPG")
        order.whatIf = True
        response: Any = None
        exception: str | None = None
        try:
            _checked_account(client)
            response = await client.whatIfOrderAsync(qualified[0], order)
        except Exception as exc:  # noqa: BLE001 - rejection is the measurement
            exception = f"{type(exc).__name__}: {exc}"
        payload = {
            "probe": "auction_whatif",
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "account_prefix_verified": "DU",
            "symbol": symbol,
            "reference_price": str(reference_price),
            "limit": str(limit),
            "quantity": quantity,
            "route": route,
            "contract_repr": repr(qualified[0]),
            "order_repr": repr(order),
            "response_repr": repr(response),
            "exception": exception,
            "api_error_events": errors,
        }
    finally:
        client.disconnect()
    path, digest = _write_raw(out_dir, "auction-whatif", payload)
    print(f"paper what-if response: {path}\nSHA-256: {digest}")
    print(f"quantity: {quantity}, nonempty response: {bool(response)}")
    print(f"exception: {exception or 'none'}, API error events: {len(errors)}")
    return 0 if response and exception is None and not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--reference-price", type=Decimal, required=True)
    parser.add_argument("--limit", type=Decimal, required=True)
    parser.add_argument("--route", choices=("SMART", "ASX"), default="SMART")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(
        _run(
            args.symbol,
            args.reference_price,
            args.limit,
            args.route,
            _safe_output_dir(args.out_dir),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
