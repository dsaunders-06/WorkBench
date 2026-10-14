"""Read-only DU evidence for the Phase 1 exit-readiness batch.

No orders can be submitted through this script. Every post-connection Gateway
request checks the single managed account immediately before invocation. Raw
responses and their hashes are written only to an explicitly outside-Git path.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ib_async import IB, ExecutionFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase3_daily_history_probe import (  # noqa: E402
    SYMBOLS,
    _checked_account,
    _paper_target,
    _safe_output_dir,
    _write_raw,
)

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_adapter import IBAdapter  # noqa: E402
from qat.data.broker.ib_translate import from_ib_fill, to_ib_contract  # noqa: E402
from qat.domain.bus import EventBus  # noqa: E402


class GuardedReadOnlyClient:
    """No order methods; recheck DU before every outbound data request."""

    _DENIED = frozenset({"placeOrder", "cancelOrder", "reqGlobalCancel", "exerciseOptions"})

    def __init__(self, client: Any) -> None:
        self.client = client
        self.requests: list[dict[str, str]] = []

    def __getattr__(self, name: str) -> Any:
        if name in self._DENIED:
            raise RuntimeError("read-only DU check cannot submit or cancel orders")
        attribute = getattr(self.client, name)
        if not callable(attribute) or not (
            name.startswith("req")
            or name.startswith("qualify")
            or name in {"cancelMktData", "accountSummaryAsync"}
        ):
            return attribute

        def checked(*args: Any, **kwargs: Any) -> Any:
            _checked_account(self.client)
            self.requests.append(
                {
                    "method": name,
                    "checked_at_utc": datetime.now(UTC).isoformat(),
                    "args": repr(args),
                    "kwargs": repr(kwargs),
                }
            )
            return attribute(*args, **kwargs)

        return checked


def _position_row(row: Any) -> dict[str, Any]:
    contract = row.contract
    return {
        "repr": repr(row),
        "account": str(getattr(row, "account", "")),
        "con_id": int(getattr(contract, "conId", 0) or 0),
        "symbol": str(getattr(contract, "symbol", "")),
        "sec_type": str(getattr(contract, "secType", "")),
        "exchange": str(getattr(contract, "exchange", "")),
        "primary_exchange": str(getattr(contract, "primaryExchange", "")),
        "currency": str(getattr(contract, "currency", "")),
        "quantity": repr(getattr(row, "position", None)),
    }


async def _delayed_observation(guarded: GuardedReadOnlyClient, adapter: Any) -> Any:
    """Mirror the adapter's connection setup before its delayed BHP stream."""
    guarded.reqMarketDataType(3)
    return await adapter.price_observation("BHP.AX")


async def _capture(
    client: IB, account: str, settings: Settings, payload: dict[str, Any]
) -> dict[str, Any]:
    guarded = GuardedReadOnlyClient(client)
    adapter = IBAdapter(guarded, EventBus(), settings=settings, read_only=True)
    payload["account"] = account
    payload["requests"] = guarded.requests

    # reqPositions refreshes ib_async's keyed local cache. The wrapper checks
    # DU before the outbound request; positions()/portfolio() then read local
    # caches and cannot send an order.
    callbacks = await guarded.reqPositionsAsync()
    payload["position_callbacks"] = [_position_row(row) for row in callbacks]
    payload["position_cache"] = [_position_row(row) for row in client.positions()]

    qualified: dict[str, int] = {}
    for symbol in SYMBOLS:
        contracts = await guarded.qualifyContractsAsync(to_ib_contract(symbol, "ASX"))
        if len(contracts) != 1 or not int(getattr(contracts[0], "conId", 0) or 0):
            raise ValueError(f"{symbol} did not qualify to exactly one ASX conId")
        contract = contracts[0]
        qualified[symbol] = int(contract.conId)
        adapter._qualified_contracts[symbol] = contract
    payload["qualified_con_ids"] = qualified

    holdings = await adapter.positions()
    payload["classified_positions"] = [
        {
            **asdict(position),
            "mark_observed_at": (
                position.mark_observed_at.isoformat() if position.mark_observed_at else None
            ),
        }
        for position in holdings
    ]
    payload["account_snapshot"] = asdict(await adapter.account())

    observation = await _delayed_observation(guarded, adapter)
    payload["bhp_price_observation"] = {
        "value": repr(observation.value),
        "field": observation.field,
        "market_data_type": observation.market_data_type,
        "source_timestamp": (
            observation.source_timestamp.isoformat() if observation.source_timestamp else None
        ),
        "observed_timestamp": observation.observed_timestamp.isoformat(),
        "age_seconds": (
            (observation.observed_timestamp - observation.source_timestamp).total_seconds()
            if observation.source_timestamp
            else None
        ),
        "refusal": observation.refusal(
            max_age=timedelta(seconds=settings.current_quote_max_age_seconds)
        ),
    }

    # One account-filtered execution request; from_ib_fill is the batch's UTC
    # normalization boundary. No streamed callback timestamp is attributed.
    raw_fills = await guarded.reqExecutionsAsync(ExecutionFilter(acctCode=account))
    executions: list[dict[str, Any]] = []
    for raw in raw_fills:
        execution = raw.execution
        normalized = from_ib_fill(raw, "ASX")
        executions.append(
            {
                "repr": repr(raw),
                "exec_id": str(getattr(execution, "execId", "")),
                "account": str(getattr(execution, "acctNumber", "")),
                "con_id": int(getattr(raw.contract, "conId", 0) or 0),
                "execution_time_repr": repr(getattr(execution, "time", None)),
                "execution_time_type": type(getattr(execution, "time", None)).__name__,
                "execution_time_tzinfo": repr(
                    getattr(getattr(execution, "time", None), "tzinfo", None)
                ),
                "normalized": (
                    {
                        **asdict(normalized),
                        "filled_at": normalized.filled_at.isoformat(),
                    }
                    if normalized is not None
                    else None
                ),
            }
        )
    payload["executions"] = executions
    payload["finished_utc"] = datetime.now(UTC).isoformat()
    return payload


async def _run(out_dir: Path) -> int:
    safe_dir = _safe_output_dir(out_dir)
    settings = Settings(
        _env_file=None,
        market="ASX",
        trading_mode="paper",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
    )
    host, port, client_id = _paper_target(settings)
    client = IB()
    payload: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "host": host,
        "port": port,
        "client_id": client_id,
    }
    # Connection is the unavoidable bootstrap request: the account list is
    # available only after it succeeds. It is localhost paper-port and API
    # read-only; every subsequent request is guarded by the DU account check.
    try:
        await client.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)
        _checked_account(client)
        account = str(client.managedAccounts()[0])
        settings.ibkr_account_id = account
        await _capture(client, account, settings, payload)
    except Exception as exc:  # noqa: BLE001 - preserve partial evidence, then fail
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        client.disconnect()
    payload["finished_utc"] = datetime.now(UTC).isoformat()
    path, digest = _write_raw(safe_dir, "exit-readiness-du", payload)
    print(f"{path} SHA-256 {digest}")
    return 1 if "error" in payload else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    arguments = parser.parse_args()
    return asyncio.run(_run(arguments.out_dir))


if __name__ == "__main__":
    raise SystemExit(main())
