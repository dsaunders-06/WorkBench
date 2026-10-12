"""Summarise out-of-Git Phase 3 probe evidence without copying raw responses."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _request_summary(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("probe") == "paper_stop_lifecycle":
        plan = next(
            (
                event
                for event in payload.get("events", [])
                if event.get("event") == "bounded order plan"
            ),
            {},
        )
        return [
            {
                "symbol": "BHP.AX",
                "session": payload.get("session"),
                "gateway": "localhost:4002 DU paper",
                "order_sequence": "BUY MKT, SELL STP GTC, raise stop, cancel stop, SELL MKT",
                "reference_price": plan.get("reference"),
                "reference_market_data_type": plan.get("reference_market_data_type"),
                "reference_source_timestamp": plan.get("reference_source_timestamp"),
                "reference_age_seconds": plan.get("reference_age_seconds"),
                "quantity": plan.get("quantity"),
                "first_stop": plan.get("first_stop"),
                "raised_stop": plan.get("raised_stop"),
            }
        ]
    if payload.get("request") == "BHP.AX delayed streaming quote preflight":
        return [
            {
                "symbol": "BHP.AX",
                "gateway": "localhost:4002 DU paper",
                "request": payload["request"],
                "quote": payload.get("quote"),
                "quantity": payload.get("minimum_parcel_shares"),
                "reference_notional_aud": payload.get("reference_notional_aud"),
            }
        ]
    if "raw_file" in payload and "raw_sha256" in payload:
        return [{"raw_file": payload["raw_file"], "raw_sha256": payload["raw_sha256"]}]
    if "requests" in payload:
        requests = [
            {
                key: request.get(key)
                for key in (
                    "symbol",
                    "series",
                    "end",
                    "duration",
                    "use_rth",
                    "bar_size",
                    "started_utc",
                )
                if key != "bar_size" or key in request
            }
            for request in payload["requests"]
        ]
        requests.extend(
            {
                key: request.get(key)
                for key in (
                    "symbol",
                    "start_requested",
                    "desired_start_sydney",
                    "end_requested_sydney",
                    "number_of_ticks",
                    "what_to_show",
                    "use_rth",
                    "started_utc",
                )
            }
            for request in payload.get("tick_requests", [])
        )
        return requests
    if "responses" in payload:
        return [
            {key: response.get(key) for key in ("symbol", "start", "end")}
            for response in payload["responses"]
        ]
    if "rows" in payload:
        return [
            {
                key: row.get(key)
                for key in (
                    "symbol",
                    "route",
                    "requested_utc",
                    "request_contract_repr",
                    "what_if_order_repr",
                )
            }
            for row in payload["rows"]
        ]
    return [
        {
            key: payload.get(key)
            for key in (
                "symbol",
                "route",
                "contract_repr",
                "reference_price",
                "limit",
                "quantity",
                "order_repr",
            )
            if key in payload
        }
    ]


def create_manifest(raw_dir: Path, destination: Path) -> int:
    root = raw_dir.resolve(strict=True)
    if any((ancestor / ".git").exists() for ancestor in (root, *root.parents)):
        raise ValueError("raw evidence must be outside Git")
    entries = []
    for path in sorted(root.glob("phase3-*.json")):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        sidecar = path.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
        if digest != sidecar:
            raise ValueError(f"raw response hash mismatch: {path.name}")
        payload = json.loads(data)
        entries.append(
            {
                "filename": path.name,
                "sha256": digest,
                "retrieved_utc": payload.get("retrieved_utc")
                or payload.get("at_utc")
                or (payload.get("events") or [{}])[-1].get("at_utc"),
                "retrieved_sydney": payload.get("retrieved_sydney"),
                "probe": payload.get("probe") or payload.get("request"),
                "request_parameters": _request_summary(payload),
            }
        )
    destination.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(f"manifest entries: {create_manifest(args.raw_dir, args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
