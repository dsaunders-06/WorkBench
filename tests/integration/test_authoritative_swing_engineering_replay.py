"""Offline Phase 2C engineering runner contracts."""

from __future__ import annotations

import csv
import json
import socket
import subprocess
import urllib.request
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.research.run_authoritative_swing as runner
from qat.domain.backtester.swing_dataset import DatasetTier, validate_catalog
from qat.domain.backtester.swing_fills import AmbiguityPolicy
from qat.domain.backtester.swing_results import (
    LifecycleActionSeries,
    PostFillResistanceDiagnostic,
    ReplayArm,
    ReplayEquityPoint,
    RunStatus,
    SwingReplayResult,
)
from qat.domain.strategies.authoritative_swing.model import DecisionStatus
from scripts.research.run_authoritative_swing import _run_golden, _synthetic_golden, main
from tests.domain.backtester.test_swing_dataset import _fixture as signed_engineering_fixture


def _bundle(root: Path) -> Path:
    bundles = [path for path in root.iterdir() if path.is_dir()]
    assert len(bundles) == 1
    return bundles[0]


def test_synthetic_golden_creates_four_arm_non_promotional_bundle(tmp_path: Path) -> None:
    assert (
        main(
            ["--catalog", "synthetic-golden", "--partition", "development", "--out", str(tmp_path)]
        )
        == 0
    )
    bundle = _bundle(tmp_path)
    promotion = json.loads((bundle / "promotion.json").read_text(encoding="utf-8"))
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert promotion["status"] == "PORTFOLIO_RISK_DESIGN_PENDING"
    assert set(manifest["replay_status"]) == {
        "ema_pullback",
        "bull_flag",
        "double_bottom",
        "combined",
    }
    assert all(status == "valid" for status in manifest["replay_status"].values())
    assert manifest["dataset"]["catalog_id"] == "synthetic-golden"
    assert manifest["metrics"]["arms"]["combined"]["trades"] >= 4
    assert manifest["metrics"]["arms"]["combined"]["ambiguities"] >= 1
    assert manifest["signal_counts"]["combined"]["overlap_suppressed"] >= 1
    assert all(manifest["dataset"][key] for key in ("T0", "T1", "T10", "T11", "T64", "T65"))
    assert manifest["dataset"]["regime_provenance"]["max_input_session"] < manifest["dataset"]["T1"]
    report = (bundle / "report.md").read_text(encoding="utf-8")
    for label in (
        "Costs:",
        "Fill model:",
        "T0:",
        "T1:",
        "T10:",
        "T11:",
        "T64:",
        "T65:",
        "Terminal-valued trades:",
        "Maximum single-position notional exposure:",
        "Average single-position notional exposure:",
        "Cost to risk:",
        "Gap losses beyond planned 1% risk:",
        "Minimum-R stress:",
        "Method audit:",
        "Reference incidence:",
        "Duration feasibility:",
        "2% sizing",
    ):
        assert label in report
    with (bundle / "equity.csv").open(newline="", encoding="utf-8") as handle:
        equity_rows = list(csv.DictReader(handle))
    assert any(
        row["arm"] == "combined" and json.loads(row["position_marks"]) for row in equity_rows
    )


def test_single_position_exposure_uses_every_held_session_mark() -> None:
    replay = SwingReplayResult(
        RunStatus.VALID,
        ReplayArm.COMBINED,
        (),
        LifecycleActionSeries(),
        (),
        (),
        (),
        (
            ReplayEquityPoint(
                date(2026, 1, 5),
                Decimal("10000"),
                Decimal("9000"),
                Decimal("1000"),
                Decimal(0),
                position_marks=(("position-1", "AAA.AX", Decimal("1000")),),
            ),
            ReplayEquityPoint(
                date(2026, 1, 6),
                Decimal("11000"),
                Decimal("8800"),
                Decimal("2200"),
                Decimal(0),
                position_marks=(("position-1", "AAA.AX", Decimal("2200")),),
            ),
        ),
        (),
        (),
    )

    summary = runner._replay_summary(replay)

    assert summary["maximum_single_position_notional_exposure"] == Decimal("0.2")
    assert summary["average_single_position_notional_exposure"] == Decimal("0.15")


def test_engineering_replay_records_each_open_position_mark() -> None:
    fixture = _synthetic_golden(Decimal(1))
    replay = _run_golden(fixture, AmbiguityPolicy.CONSERVATIVE)[ReplayArm.COMBINED]

    held_points = [point for point in replay.equity if point.position_value > 0]
    assert held_points
    assert all(point.position_marks for point in held_points)
    assert all(
        sum((mark[2] for mark in point.position_marks), Decimal(0)) == point.position_value
        for point in held_points
    )


def test_golden_lifecycle_covers_overlap_dividend_halts_and_terminal_value() -> None:
    from decimal import Decimal

    fixture = _synthetic_golden(Decimal(1))
    replays = _run_golden(fixture, AmbiguityPolicy.CONSERVATIVE)
    combined = replays[ReplayArm.COMBINED]
    assert any(rule.code == "candidate_blocked" for rule in combined.abstentions)
    assert any(
        rule.code == "OVERLAPPING_EVENT" for rule in replays[ReplayArm.EMA_PULLBACK].abstentions
    )
    assert combined.dividend_entitlements
    equity_by_session = {point.session: point for point in combined.equity}
    assert equity_by_session[fixture.sessions[52]].dividend_receivables > 0
    assert equity_by_session[fixture.sessions[55]].dividend_receivables == 0
    assert all(trade.analysis_regime == "synthetic-bull" for trade in combined.trades)
    assert any(decision.status is DecisionStatus.REJECTED for decision in combined.decisions)
    assert any(
        decision.capacity_quantity < decision.risk_quantity
        for decision in combined.decisions
        if decision.status is DecisionStatus.QUALIFIED
    )
    assert any(
        bar.raw_to_adjusted_price_factor.numerator == 3
        and bar.raw_to_adjusted_price_factor.denominator == 10
        for bar in fixture.bars["SPLIT.AX"]
    )
    assert any(fill.reason == "terminal_zero" and fill.source_event_id for fill in combined.fills)
    assert (
        len([fill for fill in combined.fills if fill.symbol == "UNRES.AX" and fill.side == "sell"])
        == 1
    )
    assert all(fill.symbol != "TAIL.AX" for fill in combined.fills)
    assert any(
        trade.symbol == "HALT.AX"
        and trade.exit_session == fixture.sessions[86]
        and "time_stop" in trade.observed_triggers
        for trade in combined.trades
    )
    assert {trade.post_fill_resistance for trade in combined.trades} >= {
        PostFillResistanceDiagnostic.INSIDE_ZONE,
        PostFillResistanceDiagnostic.PATH_BLOCKED,
    }


def test_runner_denies_network_and_child_process_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline runner attempted network or process access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    try:
        import requests

        monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    except ImportError:
        pass
    try:
        import httpx

        monkeypatch.setattr(httpx.Client, "request", forbidden)
        monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    except ImportError:
        pass
    try:
        import aiohttp

        monkeypatch.setattr(aiohttp.ClientSession, "_request", forbidden)
    except ImportError:
        pass
    assert (
        main(
            ["--catalog", "synthetic-golden", "--partition", "development", "--out", str(tmp_path)]
        )
        == 0
    )


def test_phase2_rejects_promotion_and_service_capabilities(tmp_path: Path) -> None:
    assert main(["--catalog", "promotion-point-in-time", "--out", str(tmp_path)]) == 2
    assert (
        main(["--catalog", "synthetic-golden", "--service-profile", "live", "--out", str(tmp_path)])
        == 2
    )
    assert (
        main(
            [
                "--catalog",
                "synthetic-golden",
                "--engineering-mode",
                "mechanical_diagnostic",
                "--out",
                str(tmp_path),
            ]
        )
        == 2
    )
    assert not list(tmp_path.iterdir())


def test_authorized_signed_engineering_shard_replays_offline(tmp_path: Path) -> None:
    access = signed_engineering_fixture(tmp_path / "signed")
    key_path = tmp_path / "verification-key.bin"
    key_path.write_bytes(access.verification_key)
    output = tmp_path / "bundle"
    assert (
        main(
            [
                "--catalog",
                str(access.catalog_path),
                "--shard-root",
                str(access.shard_root),
                "--shard-id",
                access.shard_id,
                "--verification-key-file",
                str(key_path),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((_bundle(output) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"]["shard_ids"] == [access.shard_id]
    assert all(status == "valid" for status in manifest["replay_status"].values())
    assert {
        "volume_1.25",
        "volume_1.5",
        "volume_2.0",
        "optimistic_ambiguity",
        "doubled_costs",
        "doubled_liquidity_impact",
        "two_percent_sizing",
        "post_fill_resistance_exclusion",
        "minimum_r_stress",
    } <= set(manifest["sensitivities"])


def test_promotion_catalog_is_rejected_before_loading_any_shard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    access = signed_engineering_fixture(tmp_path / "signed")
    key_path = tmp_path / "verification-key.bin"
    key_path.write_bytes(access.verification_key)
    catalog = validate_catalog(access.catalog_path, access.verification_key)
    monkeypatch.setattr(
        runner,
        "validate_catalog",
        lambda *_args: replace(catalog, tier=DatasetTier.PROMOTION_POINT_IN_TIME),
        raising=False,
    )

    def forbidden_load(_access: object) -> None:
        raise AssertionError("promotion observations were opened")

    monkeypatch.setattr(runner, "load_swing_dataset", forbidden_load)
    assert (
        main(
            [
                "--catalog",
                str(access.catalog_path),
                "--shard-root",
                str(access.shard_root),
                "--shard-id",
                access.shard_id,
                "--verification-key-file",
                str(key_path),
                "--out",
                str(tmp_path / "out"),
            ]
        )
        == 2
    )


def test_static_asx_strict_bundle_discloses_provenance_and_missing_proxy(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--catalog",
                "static-asx",
                "--engineering-mode",
                "strict_authoritative",
                "--partition",
                "development",
                "--out",
                str(tmp_path),
            ]
        )
        == 0
    )
    bundle = _bundle(tmp_path)
    report = (bundle / "report.md").read_text(encoding="utf-8")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert "SURVIVORSHIP-BIASED — NOT PROMOTION EVIDENCE" in report.splitlines()[:8]
    assert "vendor-adjusted" in report
    assert "INSUFFICIENT_RESISTANCE_HISTORY" in report
    assert "benchmark proxy has missing sessions" in report
    assert manifest["dataset"]["symbol_count"] == 95
    assert manifest["dataset"]["official_session_count"] == 501
