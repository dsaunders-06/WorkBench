"""Read ASX contract capabilities and preview auction forms on the paper Gateway.

No order is transmitted. Every Gateway request checks the current DU account.
Raw responses and API errors are saved outside Git with a SHA-256 sidecar.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from phase3_daily_history_probe import _paper_target, _safe_output_dir, _write_raw  # noqa: E402

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_probe import check_paper_account  # noqa: E402
from qat.data.broker.ib_translate import to_ib_contract  # noqa: E402

SYMBOLS = ("SUN.AX", "MFG.AX", "BHP.AX", "CBA.AX", "WGX.AX")
ROUTES = ("SMART", "ASX", "ASXCEN")


def _checked_account(client: Any) -> None:
    accounts = list(client.managedAccounts())
    if len(accounts) != 1:
        raise ValueError("probe requires exactly one managed account")
    check_paper_account(accounts)


async def _run(mode: str, out_dir: Path) -> int:
    from ib_async import IB, LimitOrder

    settings = Settings(
        data_dir=tempfile.mkdtemp(prefix="qat-phase3-capabilities-"),
        trading_mode="paper",
        market="ASX",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        ibkr_client_id=102,
    )
    host, port, client_id = _paper_target(settings)
    client = IB()
    await client.connectAsync(
        host, port, clientId=client_id, readonly=mode == "details", timeout=15
    )
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    def record_error(*values: object) -> None:
        errors.append({"at_utc": datetime.now(UTC).isoformat(), "arguments_repr": repr(values)})

    client.errorEvent += record_error
    try:
        for symbol in SYMBOLS if mode == "details" else ("BHP.AX",):
            for route in ROUTES[:2] if mode == "details" else ROUTES:
                started = datetime.now(UTC).isoformat()
                contract = to_ib_contract(symbol, "ASX")
                contract.exchange = route if route != "ASXCEN" else "SMART"
                _checked_account(client)
                try:
                    details = await asyncio.wait_for(client.reqContractDetailsAsync(contract), 15)
                    detail_rows = [
                        {
                            "contract_repr": repr(detail.contract),
                            "orderTypes": detail.orderTypes,
                            "validExchanges": detail.validExchanges,
                        }
                        for detail in details
                    ]
                    row: dict[str, Any] = {
                        "symbol": symbol,
                        "route": route,
                        "requested_utc": started,
                        "request_contract_repr": repr(contract),
                        "details": detail_rows,
                    }
                    if mode == "preview" and details:
                        # IBKR documents LMT/OPG as its limit-on-open encoding.
                        # AUC forms are not tried: IBKR says they may rest as
                        # ordinary limits after the auction, violating this intent.
                        order = LimitOrder("BUY", 9, 61.06, tif="OPG")
                        order.whatIf = True
                        # IBKR requires transmit=True for what-if validation;
                        # whatIf=True makes this a preview, not a live order.
                        order.transmit = True
                        details[0].contract.exchange = route
                        _checked_account(client)
                        try:
                            response = await asyncio.wait_for(
                                client.whatIfOrderAsync(details[0].contract, order), 15
                            )
                            row["what_if_response_repr"] = repr(response)
                        except Exception as exc:  # noqa: BLE001 - rejection is evidence
                            row["what_if_exception"] = f"{type(exc).__name__}: {exc}"
                        row["what_if_order_repr"] = repr(order)
                except Exception as exc:  # noqa: BLE001 - capture request failure
                    row = {
                        "symbol": symbol,
                        "route": route,
                        "requested_utc": started,
                        "request_contract_repr": repr(contract),
                        "exception": f"{type(exc).__name__}: {exc}",
                    }
                rows.append(row)
    finally:
        client.disconnect()
    path, digest = _write_raw(
        out_dir,
        "contract-capability",
        {
            "probe": mode,
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "rows": rows,
            "errors": errors,
        },
    )
    print(f"raw response: {path}\nSHA-256: {digest}")
    for row in rows:
        print(row["symbol"], row["route"], row.get("details", row.get("exception")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("details", "preview"), required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(_run(args.mode, _safe_output_dir(args.out_dir)))


if __name__ == "__main__":
    raise SystemExit(main())
