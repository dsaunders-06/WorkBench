"""Synthetic information-flow tests for the pre-outcome Stage A extracts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from hashlib import sha256

import pytest

from qat.promotion.structural_extract import (
    ExtractLockedError,
    ReferenceCatalog,
    StructuralDependencyClosure,
    authorize_reference_view,
    derive_structural_view,
)

H = "a" * 64


class RecordingAuthority:
    def __init__(self) -> None:
        self.head = H
        self.events: list[tuple[str, dict[str, object], str]] = []

    def append(self, state: str, payload: dict[str, object], *, expected_head: str):
        assert expected_head == self.head
        self.events.append((state, payload, expected_head))
        self.head = sha256(
            (self.head + state + json.dumps(payload, sort_keys=True)).encode()
        ).hexdigest()
        return {
            "state": state,
            "payload": payload,
            "previous_head": expected_head,
            "head": self.head,
        }

    def verify(
        self, receipt: object, *, state: str, payload: dict[str, object], expected_head: str
    ) -> bool:
        return receipt == {
            "state": state,
            "payload": payload,
            "previous_head": expected_head,
            "head": self.head,
        }


def _calendar() -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in range(1, 32))


def _catalog() -> ReferenceCatalog:
    return ReferenceCatalog(
        catalog_id="synthetic-catalog",
        source_shard_hash=H,
        holdout_start=date(2026, 1, 20),
        official_sessions=_calendar(),
    )


def _reference_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "issuer_id": "synthetic-issuer-a",
            "pseudonymous_issuer_id": "reference-pseudo-a",
            "window_start": date(2026, 1, 1),
            "window_end": date(2026, 1, 11),
            "eligible": True,
            "index_member": True,
            "market_cap_bucket": "small",
            "liquidity_bucket": "low",
            "corporate_event_category": "none",
            "event_onset_session": None,
            "consideration_category": "none",
        },
        {
            "issuer_id": "synthetic-issuer-b",
            "pseudonymous_issuer_id": "reference-pseudo-b",
            "window_start": date(2026, 1, 2),
            "window_end": date(2026, 1, 12),
            "eligible": True,
            "index_member": True,
            "market_cap_bucket": "large",
            "liquidity_bucket": "high",
            "corporate_event_category": "halt",
            "event_onset_session": date(2026, 1, 8),
            "consideration_category": "cash",
        },
    )


def test_reference_receipt_precedes_field_limited_view() -> None:
    authority = RecordingAuthority()
    access = authorize_reference_view(
        _reference_rows(),
        catalog=_catalog(),
        release_id="synthetic-reference-1",
        authority=authority,
    )
    assert [event[0] for event in authority.events] == ["REFERENCE_VIEW_RELEASED"]
    assert access.latest_receipt.state == "REFERENCE_VIEW_RELEASED"
    assert access.latest_receipt.row_count == 2
    assert access.latest_receipt.issuer_count == 2
    assert access.maximum_session < _catalog().holdout_start
    assert all(w.end < _catalog().holdout_start for w in access.exposure_windows)
    assert set(access.schema) == {
        "pseudonymous_issuer_id",
        "window_start",
        "window_end",
        "eligible",
        "index_member",
        "market_cap_bucket",
        "liquidity_bucket",
        "corporate_event_category",
        "event_onset_session",
        "consideration_category",
    }
    rendered = repr(access)
    assert "synthetic-issuer-a" not in rendered
    assert "synthetic-issuer-b" not in rendered
    assert "reference-pseudo-a" in rendered
    assert len(access.latest_receipt.source_record_hashes) == 2
    assert len(access.latest_receipt.official_calendar_hash) == 64
    assert len(access.latest_receipt.output_hash) == 64


@pytest.mark.parametrize(
    "extra",
    ["market_cap", "traded_value", "open", "high", "low", "close", "signal", "forward_return"],
)
def test_reference_rejects_exact_or_forward_fields(extra: str) -> None:
    rows = list(_reference_rows())
    rows[0] = {**rows[0], extra: "forbidden"}
    with pytest.raises(ExtractLockedError):
        authorize_reference_view(
            rows,
            catalog=_catalog(),
            release_id="synthetic-reference-1",
            authority=RecordingAuthority(),
        )


def test_reference_rejects_holdout_row_and_crossing_ten_session_window() -> None:
    crossing = {
        **_reference_rows()[0],
        "window_start": date(2026, 1, 10),
        "window_end": date(2026, 1, 20),
    }
    with pytest.raises(ExtractLockedError):
        authorize_reference_view(
            (crossing,),
            catalog=_catalog(),
            release_id="synthetic-reference-1",
            authority=RecordingAuthority(),
        )
    holdout = {
        **_reference_rows()[0],
        "window_start": date(2026, 1, 20),
        "window_end": date(2026, 1, 30),
    }
    with pytest.raises(ExtractLockedError):
        authorize_reference_view(
            (holdout,),
            catalog=_catalog(),
            release_id="synthetic-reference-1",
            authority=RecordingAuthority(),
        )


def test_reference_rejects_raw_identity_as_pseudonym_or_collision() -> None:
    rows = list(_reference_rows())
    rows[0] = {**rows[0], "pseudonymous_issuer_id": "synthetic-issuer-a"}
    with pytest.raises(ExtractLockedError):
        authorize_reference_view(
            rows,
            catalog=_catalog(),
            release_id="synthetic-reference-1",
            authority=RecordingAuthority(),
        )
    rows = list(_reference_rows())
    rows[1] = {**rows[1], "pseudonymous_issuer_id": "reference-pseudo-a"}
    with pytest.raises(ExtractLockedError):
        authorize_reference_view(
            rows,
            catalog=_catalog(),
            release_id="synthetic-reference-1",
            authority=RecordingAuthority(),
        )


def _closure() -> StructuralDependencyClosure:
    return StructuralDependencyClosure(
        extractor_hash="1" * 64,
        engine_hash="2" * 64,
        eligibility_hash="3" * 64,
        normalization_hash="4" * 64,
        official_calendar_hash="5" * 64,
        numeric_hash="6" * 64,
        cost_hash="7" * 64,
        sizing_hash="8" * 64,
        schema_hash="9" * 64,
        source_shard_hash="a" * 64,
    )


def _structural_rows() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "pattern": "ema_pullback",
            "signal_month": "2026-01",
            "stop_distance": str(i),
            "candidate_count": 1,
            "rejection_reason": "none",
            "price_bucket": "medium",
            "liquidity_bucket": "high",
            "cost_to_planned_risk": "0.02",
            "quantity": str(10 * i),
            "notional": str(100 * i),
        }
        for i in range(1, 6)
    )


def test_structural_extract_is_aggregate_only_and_receipted_first() -> None:
    authority = RecordingAuthority()
    view = derive_structural_view(
        _structural_rows(),
        patterns=("ema_pullback",),
        complete_months=("2026-01", "2026-02"),
        closure=_closure(),
        authority=authority,
    )
    assert [event[0] for event in authority.events] == ["DEV_STRUCTURE_DERIVED"]
    assert view.latest_receipt.state == "DEV_STRUCTURE_DERIVED"
    assert view.monthly_frequency == (
        ("ema_pullback", "2026-01", 5),
        ("ema_pullback", "2026-02", 0),
    )
    assert set(view.schema) == {"monthly_frequency", "pattern_summaries", "category_counts"}
    assert ("ema_pullback", "rejection_reason", "none", 5) in view.category_counts
    assert ("ema_pullback", "price_bucket", "medium", 5) in view.category_counts
    assert ("ema_pullback", "liquidity_bucket", "high", 5) in view.category_counts
    rendered = repr(view).lower()
    for forbidden in (
        "signal_id",
        "issuer_id",
        "entry_fill",
        "exit_price",
        "pnl",
        "mfe",
        "mae",
        "win_rate",
        "profit_factor",
        "drawdown",
    ):
        assert forbidden not in rendered
    assert view.latest_receipt.valid_for(_closure())
    assert view.latest_receipt.valid_for(_closure(), report_writer_hash="f" * 64)
    assert not view.latest_receipt.valid_for(replace(_closure(), engine_hash="b" * 64))


@pytest.mark.parametrize(
    "extra",
    [
        "issuer_id",
        "signal_id",
        "entry_fill",
        "exit_price",
        "pnl",
        "r_order",
        "mfe",
        "mae",
        "win_rate",
        "profit_factor",
        "drawdown",
    ],
)
def test_structural_extract_rejects_joinable_or_outcome_fields(extra: str) -> None:
    rows = list(_structural_rows())
    rows[0] = {**rows[0], extra: "forbidden"}
    with pytest.raises(ExtractLockedError):
        derive_structural_view(
            rows,
            patterns=("ema_pullback",),
            complete_months=("2026-01",),
            closure=_closure(),
            authority=RecordingAuthority(),
        )


def test_structural_extract_fails_closed_if_receipt_cannot_be_verified() -> None:
    class RejectingAuthority(RecordingAuthority):
        def verify(
            self, receipt: object, *, state: str, payload: dict[str, object], expected_head: str
        ) -> bool:
            return False

    with pytest.raises(ExtractLockedError):
        derive_structural_view(
            _structural_rows(),
            patterns=("ema_pullback",),
            complete_months=("2026-01",),
            closure=_closure(),
            authority=RejectingAuthority(),
        )
