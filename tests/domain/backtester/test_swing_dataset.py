"""Signed, partition-scoped inputs for authoritative swing research."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from qat.domain.backtester.swing_dataset import (
    DatasetIntegrityError,
    DatasetTier,
    PartitionAccess,
    PointInTimeRegime,
    SessionKind,
    audit_regime_provenance,
    load_static_asx_engineering_dataset,
    load_swing_dataset,
    select_regime_audit_sessions,
    shard_merkle_root,
    validate_catalog,
)
from qat.domain.backtester.swing_events import CashDividendEvent, SplitEvent, SuspensionEvent
from qat.domain.strategies.authoritative_swing.model import AdjustmentStatus, FinalBar
from qat.domain.strategies.authoritative_swing.numeric import (
    normalize_reconstructed_raw,
    to_raw_price,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _daily(symbol: str, session: str, close: str = "0.011") -> dict[str, str]:
    adjusted = str(Decimal(close) * Decimal(3) / Decimal(10))
    return {
        "session": session,
        "raw_open": close,
        "raw_high": close,
        "raw_low": close,
        "raw_close": close,
        "raw_volume": "3000",
        "adjusted_open": adjusted,
        "adjusted_high": adjusted,
        "adjusted_low": adjusted,
        "adjusted_close": adjusted,
        "adjusted_volume": "10000",
        "split_factor_numerator": "3",
        "split_factor_denominator": "10",
        "source": f"fixture-{symbol}",
        "quality": "verified",
        "finalized": "true",
    }


def _fixture(
    tmp_path: Path,
    mutate_shard: Callable[[Path], None] | None = None,
    mutate_catalog: Callable[[dict[str, object]], None] | None = None,
) -> PartitionAccess:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    root = tmp_path / "development-signal"
    _write_csv(
        root / "sessions.csv",
        [
            {
                "calendar_date": day,
                "session_kind": kind,
                "open_time": "10:00" if kind == "FULL" else "",
                "close_time": "16:00" if kind == "FULL" else "",
                "source": "signed-fixture",
                "source_version": "v1",
                "source_notice": "",
                "reason": "ordinary session" if kind == "FULL" else "weekend",
                "retrieved_at": "2020-01-01T00:00:00+00:00",
                "source_hash": "calendar-source-hash",
                "finalized": "true",
            }
            for day, kind in (
                ("2020-01-02", "FULL"),
                ("2020-01-03", "FULL"),
                ("2020-01-04", "WEEKEND"),
            )
        ],
    )
    _write_csv(
        root / "membership.csv",
        [
            {"session": "2020-01-02", "symbol": "OLD.AX", "is_member": "true"},
            {"session": "2020-01-03", "symbol": "NEW.AX", "is_member": "true"},
        ],
    )
    _write_csv(root / "daily" / "OLD.AX.csv", [_daily("OLD.AX", "2020-01-02")])
    _write_csv(root / "daily" / "NEW.AX.csv", [_daily("NEW.AX", "2020-01-03")])
    _write_csv(
        root / "benchmark.csv",
        [_daily("BENCH.AX", day, "100") for day in ("2020-01-02", "2020-01-03")],
    )
    _write_csv(
        root / "corporate_actions.csv",
        [{
            "event_id": "old-delisting", "symbol": "OLD.AX", "declaration_date": "",
            "ex_session": "2020-01-03", "record_date": "", "payment_date": "",
            "kind": "delisting", "ratio_numerator": "", "ratio_denominator": "",
            "cash_amount": "", "new_symbol": "", "terminal_price": "0.011",
            "currency": "AUD",
        }],
    )
    _write_csv(
        root / "regimes.csv",
        [{
            "session": day, "label": "UNKNOWN", "probabilities_json": "{}",
            "model_version": "fixture-v1", "model_code_hash": "code-hash",
            "configuration_hash": "config-hash", "training_start": "2019-01-01",
            "training_end": "2019-12-31", "input_cutoff": day,
            "max_input_session": day, "input_hash": "fixture-input-hash",
            "fit_id": "fixture-fit", "output_hash": "fixture-output-hash",
        } for day in ("2020-01-02", "2020-01-03")],
    )
    if mutate_shard is not None:
        mutate_shard(root)
    with (root / "sessions.csv").open(newline="", encoding="utf-8") as stream:
        tradable = [
            row["calendar_date"] for row in csv.DictReader(stream)
            if row["session_kind"] in {"FULL", "SHORTENED"}
        ]
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }
    merkle_root = shard_merkle_root(files)
    holdout_files = {"secret.csv": "0" * 64}
    holdout_root = shard_merkle_root(holdout_files)
    payload: dict[str, object] = {
        "schema_version": "phase2-swing-dataset-v1",
        "tier": "engineering_synthetic",
        "source": "fixture",
        "adjustment_policy": "split_only",
        "currency": "AUD",
        "first_session": "2020-01-02",
        "last_session": "2026-01-02",
        "point_in_time_membership": True,
        "benchmark_kind": "accumulation_total_return",
        "coverage_limit_reason": "synthetic engineering fixture",
        "limitations": ["synthetic engineering only"],
        "shards": {
            "development-signal": {
                "shard_id": "development-signal", "partition": "development",
                "first_session": tradable[0], "last_session": tradable[-1],
                "files_sha256": files, "merkle_root": merkle_root,
                "shard_kind": "signal", "signal_months": ["2020-01"],
                "boundary_ids": {},
            },
            "holdout-signal": {
                "shard_id": "holdout-signal", "partition": "holdout",
                "first_session": "2026-01-02", "last_session": "2026-01-02",
                "files_sha256": holdout_files, "merkle_root": holdout_root,
                "shard_kind": "signal", "signal_months": ["2026-01"],
                "boundary_ids": {},
            },
        },
    }
    if mutate_catalog is not None:
        mutate_catalog(payload)
    def canonical(value: object) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    payload["dataset_id"] = hashlib.sha256(canonical(payload)).hexdigest()
    key = Ed25519PrivateKey.generate()
    payload["operator_signature"] = key.sign(canonical(payload)).hex()
    catalog_path = tmp_path / "dataset-catalog" / "manifest.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    return PartitionAccess(
        catalog_path=catalog_path,
        shard_id="development-signal",
        shard_root=root,
        verification_key=key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
    )


def _edit_csv(
    root: Path, relative: str, change: Callable[[list[dict[str, str]]], None]
) -> None:
    path = root / relative
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    change(rows)
    _write_csv(path, rows)


def test_membership_remains_point_in_time_without_trimming_symbol_histories(
    tmp_path: Path,
) -> None:
    dataset = load_swing_dataset(_fixture(tmp_path))
    assert dataset.catalog.tier is DatasetTier.ENGINEERING_SYNTHETIC
    assert dataset.members(date(2020, 1, 2)) == frozenset({"OLD.AX"})
    assert dataset.members(date(2020, 1, 3)) == frozenset({"NEW.AX"})
    assert tuple(dataset.bars) == ("NEW.AX", "OLD.AX")
    assert dataset.bars["OLD.AX"][-1].session < dataset.bars["NEW.AX"][-1].session
    assert dataset.bars["OLD.AX"][0].raw.close == Decimal("0.011")
    assert dataset.bars["OLD.AX"][0].raw_to_adjusted_price_factor.numerator == 3
    assert dataset.bars["OLD.AX"][0].raw_to_adjusted_price_factor.denominator == 10
    assert dataset.bars["OLD.AX"][0].adjustment is AdjustmentStatus.SPLIT_NORMALIZED
    bar = dataset.bars["OLD.AX"][0]
    assert normalize_reconstructed_raw(
        to_raw_price(bar.adjusted.close, bar.raw_to_adjusted_price_factor),
        bar.raw.close,
    ) == Decimal("0.011")


def test_catalog_signature_and_hash_are_verified_before_opening_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _fixture(tmp_path)
    opened: list[Path] = []
    original = Path.open

    def recorded_open(path: Path, *args: object, **kwargs: object):
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recorded_open)
    catalog = validate_catalog(access.catalog_path, access.verification_key)
    assert catalog.dataset_id
    assert opened == [access.catalog_path]

    changed = access.shard_root / "daily" / "OLD.AX.csv"
    changed.write_bytes(changed.read_bytes().replace(b"0.011", b"0.012", 1))
    with pytest.raises(DatasetIntegrityError, match="hash"):
        load_swing_dataset(access)


def test_development_access_never_opens_holdout_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _fixture(tmp_path)
    secret = tmp_path / "holdout-signal" / "secret.csv"
    secret.parent.mkdir()
    secret.write_text("sealed", encoding="utf-8")
    opened: list[Path] = []
    original = Path.open

    def recorded_open(path: Path, *args: object, **kwargs: object):
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recorded_open)
    dataset = load_swing_dataset(access)
    assert dataset.official_calendar.row(date(2020, 1, 4)).session_kind is SessionKind.WEEKEND
    assert secret not in opened


def test_unsigned_catalog_mutation_fails_before_shard_access(tmp_path: Path) -> None:
    access = _fixture(tmp_path)
    payload = json.loads(access.catalog_path.read_text(encoding="utf-8"))
    payload["currency"] = "USD"
    access.catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetIntegrityError, match="signature"):
        load_swing_dataset(access)


def test_signed_calendar_missing_civil_date_invalidates(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(root, "sessions.csv", lambda rows: rows.pop(1))

    with pytest.raises(DatasetIntegrityError, match="calendar row"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_signed_symbol_bar_on_closed_date_invalidates(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "daily/NEW.AX.csv",
            lambda rows: rows.append(_daily("NEW.AX", "2020-01-04")),
        )

    with pytest.raises(DatasetIntegrityError, match="closed calendar row"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_finite_malformed_symbol_bar_is_retained_as_unverified(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        def change(rows: list[dict[str, str]]) -> None:
            rows[0]["raw_high"] = "0.010"
            rows[0]["adjusted_high"] = "0.003"

        _edit_csv(root, "daily/OLD.AX.csv", change)

    dataset = load_swing_dataset(_fixture(tmp_path, mutate))
    assert dataset.bars["OLD.AX"][0].quality.value == "unverified"
    assert any("OLD.AX" in issue for issue in dataset.issues)


def test_nonfinite_symbol_price_invalidates_before_semantic_load(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(root, "daily/OLD.AX.csv", lambda rows: rows[0].update(raw_open="NaN"))

    with pytest.raises(DatasetIntegrityError, match="not finite"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_missing_delisting_outcome_invalidates(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "corporate_actions.csv",
            lambda rows: rows[0].update(terminal_price=""),
        )

    with pytest.raises(DatasetIntegrityError, match="terminal price"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_unresolved_symbol_change_lineage_invalidates(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "corporate_actions.csv",
            lambda rows: rows[0].update(kind="symbol_change", new_symbol="GHOST.AX"),
        )

    with pytest.raises(DatasetIntegrityError, match="symbol change lineage"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_benchmark_gap_invalidates(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(root, "benchmark.csv", lambda rows: rows.pop())

    with pytest.raises(DatasetIntegrityError, match="benchmark gaps"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_unlisted_file_in_authorized_shard_invalidates(tmp_path: Path) -> None:
    access = _fixture(tmp_path)
    (access.shard_root / "unlisted.csv").write_text("surprise", encoding="utf-8")
    with pytest.raises(DatasetIntegrityError, match="unlisted"):
        load_swing_dataset(access)


def test_malformed_signature_hex_is_an_integrity_error(tmp_path: Path) -> None:
    access = _fixture(tmp_path)
    payload = json.loads(access.catalog_path.read_text(encoding="utf-8"))
    payload["operator_signature"] = "not-hex"
    access.catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetIntegrityError, match="signature"):
        validate_catalog(access.catalog_path, access.verification_key)


def test_signed_ad_hoc_closure_overrides_rule_calendar_without_filling_bars(
    tmp_path: Path,
) -> None:
    def mutate(root: Path) -> None:
        def sessions(rows: list[dict[str, str]]) -> None:
            rows[1].update(
                session_kind="AD_HOC_CLOSED", open_time="", close_time="",
                source_notice="exchange-notice-2020-01-03", reason="ad hoc closure",
            )
            rows.append({**rows[2], "calendar_date": "2020-01-05"})
            rows.append({
                **rows[0], "calendar_date": "2020-01-06",
                "source_notice": "", "reason": "ordinary session",
            })

        _edit_csv(root, "sessions.csv", sessions)
        for relative in (
            "daily/NEW.AX.csv", "benchmark.csv", "membership.csv", "regimes.csv",
            "corporate_actions.csv",
        ):
            def move(rows: list[dict[str, str]], *, column: str) -> None:
                for row in rows:
                    if row.get(column) == "2020-01-03":
                        row[column] = "2020-01-06"

            column = "ex_session" if relative == "corporate_actions.csv" else "session"
            _edit_csv(root, relative, lambda rows, col=column: move(rows, column=col))

    dataset = load_swing_dataset(_fixture(tmp_path, mutate))
    closure = dataset.official_calendar.row(date(2020, 1, 3))
    assert closure.session_kind is SessionKind.AD_HOC_CLOSED
    assert closure.source_notice == "exchange-notice-2020-01-03"
    assert date(2020, 1, 3) not in dataset.official_sessions
    assert dataset.official_sessions == (date(2020, 1, 2), date(2020, 1, 6))
    assert any("rule-derived calendar" in issue for issue in dataset.issues)


def test_shortened_session_with_full_regular_hours_invalidates(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "sessions.csv",
            lambda rows: rows[1].update(session_kind="SHORTENED"),
        )

    with pytest.raises(DatasetIntegrityError, match="shortened"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_promotion_catalog_requires_point_in_time_membership(tmp_path: Path) -> None:
    def mutate(payload: dict[str, object]) -> None:
        payload["tier"] = "promotion_point_in_time"
        payload["point_in_time_membership"] = False

    access = _fixture(tmp_path, mutate_catalog=mutate)
    with pytest.raises(DatasetIntegrityError, match="point-in-time membership"):
        validate_catalog(access.catalog_path, access.verification_key)


def test_loaded_semantic_records_have_no_binary_float(tmp_path: Path) -> None:
    dataset = load_swing_dataset(_fixture(tmp_path))

    def inspect(value: object) -> None:
        assert not isinstance(value, float)
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                inspect(getattr(value, field.name))
        elif isinstance(value, Mapping):
            for key, item in value.items():
                inspect(key)
                inspect(item)
        elif isinstance(value, (tuple, list, frozenset)):
            for item in value:
                inspect(item)

    inspect(dataset)


def test_shard_root_is_a_pairwise_merkle_tree_over_names_and_hashes() -> None:
    first = hashlib.sha256(b"first").hexdigest()
    second = hashlib.sha256(b"second").hexdigest()
    left = hashlib.sha256(b"\x00a.csv\x00" + bytes.fromhex(first)).digest()
    right = hashlib.sha256(b"\x00b.csv\x00" + bytes.fromhex(second)).digest()
    expected = hashlib.sha256(b"\x01" + left + right).hexdigest()
    assert shard_merkle_root({"b.csv": second, "a.csv": first}) == expected


def test_regime_audit_hashes_every_prefix_and_recomputes_selected_labels(
    tmp_path: Path,
) -> None:
    dataset = load_swing_dataset(_fixture(tmp_path))

    def prefix_hash(session: date, prefix: tuple[FinalBar, ...]) -> str:
        del session
        identities = ",".join(bar.digest for bar in prefix)
        return hashlib.sha256(identities.encode()).hexdigest()

    regimes = {}
    for session, regime in dataset.regimes.items():
        prefix = tuple(
            bar for symbol in sorted(dataset.bars) for bar in dataset.bars[symbol]
            if bar.session <= session
        )
        regimes[session] = replace(regime, input_hash=prefix_hash(session, prefix))
    signed = replace(dataset, regimes=regimes)

    def recompute(
        regime: PointInTimeRegime, prefix: tuple[FinalBar, ...]
    ) -> tuple[str, dict[str, Decimal], str]:
        del prefix
        return regime.label, regime.probabilities, regime.output_hash

    clean = audit_regime_provenance(signed, prefix_hash, recompute)
    assert clean.checked_input_count == 2
    assert clean.sampled_sessions == signed.official_sessions
    assert clean.unknown_model_versions == frozenset()

    changed_later = replace(
        signed,
        bars={
            **signed.bars,
            "NEW.AX": (replace(signed.bars["NEW.AX"][0], digest="revised-source"),),
        },
    )
    changed = audit_regime_provenance(changed_later, prefix_hash, recompute)
    assert changed.failed_input_sessions == (date(2020, 1, 3),)
    assert changed.unknown_model_versions == frozenset({"fixture-v1"})


def test_regime_audit_sample_covers_each_model_year_and_transition() -> None:
    template = PointInTimeRegime(
        date(2020, 1, 2), "CALM", {}, "v1", "code", "config",
        date(2019, 1, 1), date(2019, 12, 31), date(2020, 1, 2),
        date(2020, 1, 2), "input", "fit", "output",
    )
    rows = {
        date(year, 1, day): replace(
            template,
            session=date(year, 1, day),
            label="STRESS" if day == 3 else "CALM",
        )
        for year in (2020, 2021)
        for day in range(2, 12)
    }
    sampled = select_regime_audit_sessions(rows)
    assert len(sampled) == len(rows)  # fewer than 100 rows per model: audit all
    assert date(2020, 1, 3) in sampled
    assert date(2021, 1, 3) in sampled


def test_corrected_source_with_same_filename_creates_new_dataset_lineage(
    tmp_path: Path,
) -> None:
    before = load_swing_dataset(_fixture(tmp_path / "before"))

    def mutate(root: Path) -> None:
        def correct(rows: list[dict[str, str]]) -> None:
            rows[0]["raw_close"] = "0.012"
            rows[0]["adjusted_close"] = "0.0036"

        _edit_csv(root, "daily/OLD.AX.csv", correct)

    after = load_swing_dataset(_fixture(tmp_path / "after", mutate))
    assert before.catalog.dataset_id != after.catalog.dataset_id
    assert before.manifest.merkle_root != after.manifest.merkle_root
    assert before.bars["OLD.AX"][0].digest != after.bars["OLD.AX"][0].digest


def test_typed_split_dividend_and_suspension_events_use_exact_facts(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        def events(rows: list[dict[str, str]]) -> None:
            rows.append({
                **rows[0], "event_id": "new-split", "symbol": "NEW.AX",
                "kind": "split", "ratio_numerator": "3", "ratio_denominator": "10",
                "terminal_price": "",
            })
            rows.append({
                **rows[0], "event_id": "new-dividend", "symbol": "NEW.AX",
                "kind": "cash_dividend", "declaration_date": "2020-01-02",
                "record_date": "2020-01-03", "payment_date": "2020-01-06",
                "cash_amount": "0.011", "terminal_price": "",
            })
            rows.append({
                **rows[0], "event_id": "old-suspension", "symbol": "OLD.AX",
                "kind": "suspension", "terminal_price": "",
            })

        _edit_csv(root, "corporate_actions.csv", events)

    dataset = load_swing_dataset(_fixture(tmp_path, mutate))
    split = next(event for event in dataset.corporate_actions if isinstance(event, SplitEvent))
    dividend = next(
        event for event in dataset.corporate_actions if isinstance(event, CashDividendEvent)
    )
    assert (split.numerator, split.denominator) == (3, 10)
    assert dividend.amount_per_share == Decimal("0.011")
    assert any(isinstance(event, SuspensionEvent) for event in dataset.corporate_actions)


def test_bad_corporate_ratio_and_currency_are_integrity_errors(tmp_path: Path) -> None:
    def bad_ratio(root: Path) -> None:
        _edit_csv(
            root, "corporate_actions.csv",
            lambda rows: rows[0].update(
                kind="split", ratio_numerator="0", ratio_denominator="2",
            ),
        )

    with pytest.raises(DatasetIntegrityError, match="split ratio"):
        load_swing_dataset(_fixture(tmp_path / "ratio", bad_ratio))

    def bad_currency(root: Path) -> None:
        _edit_csv(
            root, "corporate_actions.csv",
            lambda rows: rows[0].update(currency="USD"),
        )

    with pytest.raises(DatasetIntegrityError, match="currency mismatch"):
        load_swing_dataset(_fixture(tmp_path / "currency", bad_currency))


def test_nonfinalized_symbol_bar_is_retained_but_nonverified(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "daily/OLD.AX.csv",
            lambda rows: rows[0].update(finalized="false"),
        )

    dataset = load_swing_dataset(_fixture(tmp_path, mutate))
    assert dataset.bars["OLD.AX"][0].quality.value == "unverified"
    assert any("non-finalized" in issue for issue in dataset.issues)


def test_signed_daily_schema_rejects_unlisted_columns(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "daily/OLD.AX.csv",
            lambda rows: rows[0].update(hidden_return="0.5"),
        )

    with pytest.raises(DatasetIntegrityError, match="columns"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_signed_daily_schema_rejects_extra_cells(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        path = root / "daily" / "OLD.AX.csv"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] += ",unlisted"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(DatasetIntegrityError, match="row width"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_signed_shard_rejects_unknown_file_type(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        (root / "unmapped.csv").write_text("value\nsecret\n", encoding="utf-8")

    with pytest.raises(DatasetIntegrityError, match="unknown file"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_signed_non_split_adjustment_cannot_be_labeled_split_normalized(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, object]) -> None:
        payload["adjustment_policy"] = "vendor_adjusted"

    with pytest.raises(DatasetIntegrityError, match="split-only"):
        load_swing_dataset(_fixture(tmp_path, mutate_catalog=mutate))


def test_delisting_with_later_traded_bar_invalidates(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "daily/OLD.AX.csv",
            lambda rows: rows.append(_daily("OLD.AX", "2020-01-03")),
        )

    with pytest.raises(DatasetIntegrityError, match="delisting.*traded bar"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_promotion_catalog_needs_partition_tails_before_any_data_open(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, object]) -> None:
        payload["tier"] = "promotion_point_in_time"

    access = _fixture(tmp_path, mutate_catalog=mutate)
    with pytest.raises(DatasetIntegrityError, match="tail"):
        validate_catalog(access.catalog_path, access.verification_key)


def test_signed_adjusted_volume_must_match_split_factor(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        _edit_csv(
            root, "daily/OLD.AX.csv",
            lambda rows: rows[0].update(adjusted_volume="1"),
        )

    with pytest.raises(DatasetIntegrityError, match="volume lineage"):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_verified_catalog_and_dataset_mappings_cannot_be_mutated(tmp_path: Path) -> None:
    dataset = load_swing_dataset(_fixture(tmp_path))
    with pytest.raises(TypeError):
        dataset.catalog.shards["holdout-signal"] = dataset.manifest  # type: ignore[index]
    with pytest.raises(TypeError):
        dataset.manifest.files_sha256["sessions.csv"] = "0" * 64  # type: ignore[index]
    with pytest.raises(TypeError):
        dataset.bars["NEW.AX"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        dataset.regimes[date(2020, 1, 2)] = dataset.regimes[date(2020, 1, 3)]  # type: ignore[index]


def test_signed_catalog_rejects_duplicate_json_keys_even_if_last_value_is_signed(
    tmp_path: Path,
) -> None:
    access = _fixture(tmp_path)
    raw = access.catalog_path.read_text(encoding="utf-8")
    changed = raw.replace('"currency": "AUD"', '"currency": "USD", "currency": "AUD"', 1)
    assert changed != raw
    access.catalog_path.write_text(changed, encoding="utf-8")
    with pytest.raises(DatasetIntegrityError, match="duplicate JSON key"):
        validate_catalog(access.catalog_path, access.verification_key)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("duplicate-calendar", "calendar rows"),
        ("unknown-session-kind", "invalid calendar row"),
        ("missing-closure-reason", "calendar reason"),
        ("missing-ad-hoc-notice", "closure notice"),
        ("partial-bar", "raw close"),
        ("missing-bar-source", "bar source"),
        ("missing-bar-quality", "factor or quality"),
        ("future-regime-input", "regime provenance"),
    ],
)
def test_signed_structural_defects_fail_closed(
    tmp_path: Path, case: str, reason: str
) -> None:
    def mutate(root: Path) -> None:
        if case == "duplicate-calendar":
            _edit_csv(root, "sessions.csv", lambda rows: rows.append(dict(rows[1])))
        elif case == "unknown-session-kind":
            _edit_csv(root, "sessions.csv", lambda rows: rows[1].update(session_kind="OPEN"))
        elif case == "missing-closure-reason":
            _edit_csv(root, "sessions.csv", lambda rows: rows[2].update(reason=""))
        elif case == "missing-ad-hoc-notice":
            _edit_csv(
                root, "sessions.csv",
                lambda rows: rows[1].update(
                    session_kind="AD_HOC_CLOSED", open_time="", close_time="",
                ),
            )
        elif case == "partial-bar":
            _edit_csv(root, "daily/OLD.AX.csv", lambda rows: rows[0].update(raw_close=""))
        elif case == "missing-bar-source":
            _edit_csv(root, "daily/OLD.AX.csv", lambda rows: rows[0].update(source=""))
        elif case == "missing-bar-quality":
            _edit_csv(root, "daily/OLD.AX.csv", lambda rows: rows[0].update(quality=""))
        elif case == "future-regime-input":
            _edit_csv(
                root, "regimes.csv",
                lambda rows: rows[0].update(input_cutoff="2020-01-05"),
            )

    with pytest.raises(DatasetIntegrityError, match=reason):
        load_swing_dataset(_fixture(tmp_path, mutate))


def test_existing_static_cache_is_labeled_engineering_only() -> None:
    cache = Path(__file__).resolve().parents[3] / "scripts" / "research" / "asx_bars"
    dataset = load_static_asx_engineering_dataset(cache)

    assert dataset.catalog.tier is DatasetTier.ENGINEERING_STATIC
    assert dataset.catalog.operator_signature == "UNSIGNED_ENGINEERING_ONLY"
    assert len(dataset.bars) == 95
    assert all(len(history) == 500 for history in dataset.bars.values())
    assert dataset.official_sessions[0] == date(2024, 8, 23)
    assert dataset.official_sessions[-1] == date(2026, 8, 14)
    assert len(dataset.official_sessions) == 501
    assert dataset.benchmark == ()
    assert dataset.bars["BHP.AX"][0].adjustment is AdjustmentStatus.VENDOR_ADJUSTED
    assert any("survivorship" in limitation for limitation in dataset.catalog.limitations)
    assert any("raw" in limitation for limitation in dataset.catalog.limitations)
    assert any("missing sessions" in limitation for limitation in dataset.catalog.limitations)
