# Live Book Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute portfolio VaR/ES/concentration over the book actually held, on a timer, and show it beside the figure the last risk decision recorded — so the AI advisory and the operator's tiles stop depending on a decision that has not happened since 31 August.

**Architecture:** A pure function (`compute_book_risk`) reusing the existing `PortfolioRiskChecker` internals so the live and decision numbers are computed by the same instrument; a `BookRiskMonitor` engine that samples it on a timer from the *shared throttled* account poller rather than the broker; and three readers that treat a stale snapshot exactly as they treat a missing one.

**Tech Stack:** Python 3.12, pandas, numpy, pydantic-settings, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-live-book-risk-design.md`

## Global Constraints

- **Absent is `None`, never `0.0`.** This is the single rule the whole feature turns on. `compute_historical_var` and `compute_expected_shortfall` both `return 0.0` below two observations (`portfolio_risk.py:30`, `:39`), so every call site gates on the observation count *before* calling.
- **Same instrument as the decision path.** Reuse `PortfolioRiskChecker._combined_portfolio_returns`, `compute_historical_var`, `compute_expected_shortfall`. Do not reimplement any of them.
- **Weights are `quantity * avg_price`** (cost basis), matching `signal_bridge.py:1467`. Do **not** use `Position.mark`.
- **The monitor makes no direct broker call.** Positions and equity come from `AccountPoller.snapshot()`.
- **A stale snapshot is treated identically to no snapshot.** No third state.
- Run the four checks **separately**, never chained: `python -m ruff check .`, `python -m black --check .`, `python -m mypy src`, `python -m bandit -q -r src`. `black --check` can exit 0 while printing "1 file would be reformatted", so `&&` hides a failure.
- Use `.venv\Scripts\python.exe -m <tool>`, never a bare tool name — the venv's Scripts directory is not on PATH.
- Every commit message ends with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Nothing here is visible until a build, deploy and read-back, which happens after a market close and is **not** part of this plan.

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/domain/risk_engine/book_risk.py` | **Create.** `BookRisk` dataclass + `compute_book_risk` (pure) + `BookRiskMonitor` (engine). One file because the three change together and the monitor is ~60 lines. |
| `tests/domain/risk_engine/test_book_risk.py` | **Create.** Tests for the pure function. |
| `tests/domain/risk_engine/test_book_risk_monitor.py` | **Create.** Tests for the engine, including the "no broker call" assertion. |
| `tests/data/test_book_risk_settings.py` | **Create.** The three settings and the derived bound. |
| `tests/presentation/test_risk_metrics_sees_the_book.py` | **Create.** Tasks 1 and 7. |
| `tests/presentation/test_book_risk_monitor_is_wired.py` | **Create.** Task 6. |
| `tests/presentation/test_kpi_tile_caption.py` | **Create.** Task 8. |
| `tests/presentation/test_risk_tiles_read_the_live_book.py` | **Create.** Task 9. |
| `tests/presentation/test_workbench_var_tile.py` | **Create.** Task 10. |
| `src/qat/config.py` | **Modify.** Three settings beside `equity_poll_seconds` (line 98). |
| `src/qat/presentation/advisory_account.py` | **Modify.** `risk_metrics()` at line 202. |
| `src/qat/domain/ai_advisory/context.py` | **Modify.** Type of `risk_metrics` field at line 24. |
| `src/qat/presentation/runtime.py` | **Modify.** Construct, register and expose the monitor. |
| `src/qat/presentation/risk_console.py` | **Modify.** `_refresh_from_audit_log` at line 574. |
| `src/qat/presentation/dashboard.py` | **Modify.** `var_tile` update at line 479. |
| `src/qat/presentation/widgets.py` | **Modify.** `KpiTile` gains an optional caption line. |

### ⚠️ Test conventions in this repo — read before writing any test

Verified against the tree, because the first draft of this plan guessed all seven
paths wrong.

- **Test files are named for the BEHAVIOUR, not the module.** There is no
  `test_dashboard.py` or `test_widgets.py`. There is
  `test_advisory_account_is_auditable.py`, `test_risk_console_anomalies.py`,
  `test_workbench_equity_axis.py`. Create new behaviour-named files; do not
  append to a module-named file that does not exist.
- **The Qt binding is PySide6**, not PyQt6 (`pyproject.toml` sets
  `qt_api = "pyside6"`).
- **Screens are built with `Runtime.build_demo(...)` and the `qtbot` fixture:**

```python
def _build_screen(qtbot, tmp_path) -> tuple[RiskConsoleScreen, Runtime]:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    return screen, runtime
```

  ⚠️ **`_env_file=None` is not optional.** Without it `Settings()` loads the
  operator's live `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env` and the test runs
  against real configuration.
- **The cached account snapshot is seeded directly**, because screens read the
  poller's cache rather than awaiting one:

```python
runtime.account_poller._snapshot = AccountSnapshot(
    summary=None,
    balances=AccountBalances(cash=0.0, buying_power=0.0, equity=1_000_000.0),
    positions=(Position(symbol="A2M.AX", quantity=1000.0, avg_price=120.0),),
    taken_at=datetime.now(UTC),
)
```

- `asyncio_mode = "auto"`, but existing async tests still carry
  `@pytest.mark.asyncio`. Match the surrounding file.
- Screen classes are `DashboardScreen` and `RiskConsoleScreen`.
- Every test module opens with a docstring saying **why the test exists** —
  usually naming the defect and its date. Follow that; it is the house style and
  it is what makes these files readable a month later.
- `tests/presentation/conftest.py` makes any real modal dialog fail loudly. Do
  not open one.

---

### Task 1: Widen the audit read (spec section D)

Smallest and independent. Lands alone so it is worth having even if everything after it is deferred.

**Files:**
- Modify: `src/qat/presentation/advisory_account.py:202-224`
- Create: `tests/presentation/test_risk_metrics_sees_the_book.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `risk_metrics(runtime) -> dict[str, float]` — unchanged signature, now returning up to five keys instead of two. Task 6 rewrites this function's return shape and must fold this widened tuple into its `at_last_decision` group.

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/test_risk_metrics_sees_the_book.py`:

```python
"""The advisory has never seen portfolio risk, and two fields were dropped.

Measured 2 September 2026: `portfolio_check` appears in 63 of 3,596 audit rows,
because it is written one rail AFTER the governor's position-count refusal and
the book has been at 10 of 10 since 31 August. Of the 63 that DO carry one,
`var_99` and `single_name_pct` are non-null in all 63 and were discarded anyway
by a hardcoded two-name tuple.
"""

from __future__ import annotations

from types import SimpleNamespace

from qat.presentation.advisory_account import risk_metrics


def _entry(inputs: dict) -> SimpleNamespace:
    return SimpleNamespace(inputs=inputs)


def _runtime_with_audit_entries(entries: list) -> SimpleNamespace:
    return SimpleNamespace(
        risk_engine=SimpleNamespace(audit_log=SimpleNamespace(entries=lambda: entries)),
        book_risk_monitor=None,
    )
```

Then the tests:

```python
def test_risk_metrics_returns_every_field_the_check_recorded():
    """var_99 and single_name_pct are non-null in 63 of 63 recorded rows and
    were dropped anyway by a hardcoded two-name tuple."""
    runtime = _runtime_with_audit_entries(
        [
            _entry(
                inputs={
                    "portfolio_check": {
                        "var_95": 0.0108,
                        "var_99": 0.0148,
                        "es_975": 0.0166,
                        "single_name_pct": 0.125,
                        "sector_pct": 0.125,
                    }
                }
            )
        ]
    )

    assert risk_metrics(runtime) == {
        "var_95": 0.0108,
        "var_99": 0.0148,
        "es_975": 0.0166,
        "single_name_pct": 0.125,
        "sector_pct": 0.125,
    }


def test_risk_metrics_omits_sector_pct_when_the_check_did_not_record_one():
    """sector_pct is null in 60 of 63 rows. Absent is omitted, not zeroed."""
    runtime = _runtime_with_audit_entries(
        [
            _entry(
                inputs={
                    "portfolio_check": {
                        "var_95": 0.0108,
                        "var_99": 0.0148,
                        "es_975": 0.0166,
                        "single_name_pct": 0.125,
                        "sector_pct": None,
                    }
                }
            )
        ]
    )

    assert "sector_pct" not in risk_metrics(runtime)
    assert risk_metrics(runtime)["var_99"] == 0.0148
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_risk_metrics_sees_the_book.py -v
```

Expected: FAIL. The first with a dict missing `var_99`, `single_name_pct` and `sector_pct`; the second with a `KeyError` on `var_99`.

- [ ] **Step 3: Widen the tuple**

In `src/qat/presentation/advisory_account.py`, replace the return of `risk_metrics`:

```python
    return {
        name: float(value)
        for name in ("var_95", "var_99", "es_975", "single_name_pct", "sector_pct")
        if (value := portfolio_check.get(name)) is not None
    }
```

And add to the docstring, after the existing paragraph:

```
    ⚠️ The tuple was ("var_95", "es_975"). Measured across all 63 audit rows
    that carry a portfolio_check: var_99 and single_name_pct are non-null in
    63 of 63 and were being discarded, while sector_pct is non-null in only 3
    and is omitted by the `is not None` filter on the other 60 - which is the
    same "absent is omitted rather than zeroed" discipline, working correctly.
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_risk_metrics_sees_the_book.py -v
```

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add src/qat/presentation/advisory_account.py tests/presentation/test_risk_metrics_sees_the_book.py
git commit -m "risk_metrics: stop dropping var_99 and single_name_pct"
```

---

### Task 2: `BookRisk` and `compute_book_risk` — the empty and thin cases

The rail first. This task deliberately covers **only** the cases that must return `None`, because those are the ones a naive implementation gets wrong by returning `0.0`.

**Files:**
- Create: `src/qat/domain/risk_engine/book_risk.py`
- Create: `tests/domain/risk_engine/test_book_risk.py`

**Interfaces:**
- Consumes: `PortfolioRiskChecker._combined_portfolio_returns`, `compute_historical_var`, `compute_expected_shortfall` from `qat.domain.risk_engine.portfolio_risk`.
- Produces:
  - `BookRisk(computed_at: datetime, symbols: int, observations: int, var_95: float | None, var_99: float | None, es_975: float | None, single_name_pct: float | None, sector_pct: float | None, notes: tuple[str, ...])`
  - `compute_book_risk(*, weights: dict[str, float], returns: dict[str, pd.Series], total_equity: float, sector_by_symbol: dict[str, str] | None, now: datetime, min_observations: int) -> BookRisk`

- [ ] **Step 1: Write the failing tests**

Create `tests/domain/risk_engine/test_book_risk.py`:

```python
from datetime import UTC, datetime

import pandas as pd

from qat.domain.risk_engine.book_risk import BookRisk, compute_book_risk

NOW = datetime(2026, 9, 2, 17, 0, tzinfo=UTC)


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range("2026-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=index)


def test_an_empty_book_is_absent_not_zero():
    result = compute_book_risk(
        weights={},
        returns={},
        total_equity=1_000_000.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.var_99 is None
    assert result.es_975 is None
    assert result.single_name_pct is None
    assert result.sector_pct is None
    assert result.symbols == 0
    assert any("no positions held" in note for note in result.notes)


def test_one_observation_is_absent_not_zero():
    """⚠️ THE TEST THIS TASK EXISTS FOR. compute_historical_var returns 0.0
    below two observations, so a live path that called it blindly would tell
    the model 'no tail risk' about a book it could not measure - the exact
    failure risk_metrics' own docstring was written to prevent."""
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01])},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.es_975 is None
    assert result.observations < 30
    assert any("30" in note for note in result.notes)


def test_below_the_floor_the_concentration_fields_still_report():
    """single_name_pct needs no return history, so a thin book still gets it."""
    result = compute_book_risk(
        weights={"A2M.AX": 250_000.0, "ANZ.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01, -0.02]), "ANZ.AX": _series([0.0, 0.01])},
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples", "ANZ.AX": "Financials"},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.single_name_pct == 0.25
    assert result.sector_pct == 0.25


def test_no_equity_is_absent_not_zero():
    result = compute_book_risk(
        weights={"A2M.AX": 100_000.0},
        returns={"A2M.AX": _series([0.01] * 60)},
        total_equity=0.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    assert result.var_95 is None
    assert result.single_name_pct is None
    assert any("equity" in note for note in result.notes)


def test_computed_at_is_the_clock_it_was_given():
    result = compute_book_risk(
        weights={},
        returns={},
        total_equity=1.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    assert result.computed_at == NOW
    assert isinstance(result, BookRisk)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/risk_engine/test_book_risk.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'qat.domain.risk_engine.book_risk'`.

- [ ] **Step 3: Write the module**

Create `src/qat/domain/risk_engine/book_risk.py`:

```python
"""Portfolio risk over the book ACTUALLY HELD, independent of any decision.

⚠️ WHY THIS EXISTS. `risk_metrics()` read the last risk decision's
`portfolio_check`, which is written one rail AFTER the governor's position-count
rejection. With the book at 10 of 10 every candidate is refused before the
portfolio checker runs, so 3,533 of 3,596 audit rows carry no number at all - and
`AuditLog._entries` is in-memory, so `entries()` is empty at every startup
regardless. The model was being told "none available" on every run.

⚠️ ABSENT IS None, NEVER 0.0. `compute_historical_var` and
`compute_expected_shortfall` both return 0.0 below two observations. Calling them
blindly on a thin book would hand the model "no tail risk" about something it
could not measure, which is precisely the failure `risk_metrics`' docstring names:
"a metric the last check did not record reached the model as a MEASURED ZERO".
Every gate here happens BEFORE the call.

The computation reuses `PortfolioRiskChecker`'s own internals rather than
reimplementing them, because the live figure is displayed BESIDE the decision
figure and two numbers measured with different instruments cannot be compared.
That is the 8 August lesson: 5.02% against a true 5.87%.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from qat.domain.risk_engine.portfolio_risk import (
    PortfolioRiskChecker,
    compute_expected_shortfall,
    compute_historical_var,
)

logger = logging.getLogger(__name__)

_VAR_CONFIDENCE_95 = 0.95
_VAR_CONFIDENCE_99 = 0.99
_ES_CONFIDENCE = 0.975


@dataclass(frozen=True, slots=True)
class BookRisk:
    """One measurement of the held book. Every metric is optional, and `None`
    means "not measurable", which is a DIFFERENT CLAIM from zero."""

    computed_at: datetime
    symbols: int
    observations: int
    var_95: float | None
    var_99: float | None
    es_975: float | None
    single_name_pct: float | None
    sector_pct: float | None
    notes: tuple[str, ...]

    @property
    def has_any(self) -> bool:
        return any(
            value is not None
            for value in (
                self.var_95,
                self.var_99,
                self.es_975,
                self.single_name_pct,
                self.sector_pct,
            )
        )

    def age_seconds(self, now: datetime) -> float:
        return (now - self.computed_at).total_seconds()


def _absent(now: datetime, notes: tuple[str, ...], symbols: int = 0) -> BookRisk:
    return BookRisk(
        computed_at=now,
        symbols=symbols,
        observations=0,
        var_95=None,
        var_99=None,
        es_975=None,
        single_name_pct=None,
        sector_pct=None,
        notes=notes,
    )


def compute_book_risk(
    *,
    weights: dict[str, float],
    returns: dict[str, pd.Series],
    total_equity: float,
    sector_by_symbol: dict[str, str] | None,
    now: datetime,
    min_observations: int,
) -> BookRisk:
    """Measure the held book. Never raises; never substitutes zero for absent.

    ⚠️ `single_name_pct` and `sector_pct` are the LARGEST in the book, where the
    decision path's fields of the same name are the CANDIDATE's. There is no
    candidate here. Wherever the two are displayed together they must be
    labelled differently, or a coincidence reads as agreement.
    """
    held = {symbol: value for symbol, value in weights.items() if value}
    if not held:
        return _absent(now, ("no positions held",))
    if total_equity <= 0:
        return _absent(now, ("equity is not available, so nothing can be measured",), len(held))

    # Concentration needs no return history, so it is computed first and
    # survives a book too thin for VaR.
    single_name_pct = max(abs(value) for value in held.values()) / total_equity

    sector_pct: float | None = None
    if sector_by_symbol:
        by_sector: dict[str, float] = {}
        for symbol, value in held.items():
            sector = sector_by_symbol.get(symbol)
            if sector is None:
                continue
            by_sector[sector] = by_sector.get(sector, 0.0) + abs(value)
        if by_sector:
            sector_pct = max(by_sector.values()) / total_equity

    notes: list[str] = []
    if sector_pct is None:
        notes.append("no held symbol is in the sector map, so sector concentration is unknown")

    portfolio_returns = PortfolioRiskChecker._combined_portfolio_returns(
        held, returns, total_equity
    )
    observations = len(portfolio_returns)

    # ⚠️ THE GATE, BEFORE THE CALL. Below the floor these three stay None.
    if observations < min_observations:
        notes.append(
            f"{observations} overlapping return observation(s) across {len(held)} position(s), "
            f"below the {min_observations} needed - VaR and ES are UNKNOWN, not zero"
        )
        return BookRisk(
            computed_at=now,
            symbols=len(held),
            observations=observations,
            var_95=None,
            var_99=None,
            es_975=None,
            single_name_pct=single_name_pct,
            sector_pct=sector_pct,
            notes=tuple(notes),
        )

    return BookRisk(
        computed_at=now,
        symbols=len(held),
        observations=observations,
        var_95=compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_95),
        var_99=compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_99),
        es_975=compute_expected_shortfall(portfolio_returns, _ES_CONFIDENCE),
        single_name_pct=single_name_pct,
        sector_pct=sector_pct,
        notes=tuple(notes),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/risk_engine/test_book_risk.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/risk_engine/book_risk.py tests/domain/risk_engine/test_book_risk.py
git commit -m "book_risk: measure the held book, and refuse to call absent zero"
```

---

### Task 3: `compute_book_risk` on a real book, proved equal to the checker

The comparability claim is the reason the whole side-by-side display is honest. Assert it rather than assume it.

**Files:**
- Modify: `tests/domain/risk_engine/test_book_risk.py`

**Interfaces:**
- Consumes: `compute_book_risk` from Task 2; `PortfolioRiskChecker` from `qat.domain.risk_engine.portfolio_risk`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/domain/risk_engine/test_book_risk.py`:

```python
import numpy as np

from qat.domain.risk_engine.portfolio_risk import PortfolioRiskChecker


def _noisy(seed: int, n: int = 120) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.Series(rng.normal(0.0, 0.01, n), index=index)


def test_a_real_book_reports_every_metric():
    weights = {"A2M.AX": 120_000.0, "ANZ.AX": 90_000.0, "BOQ.AX": 60_000.0}
    returns = {"A2M.AX": _noisy(1), "ANZ.AX": _noisy(2), "BOQ.AX": _noisy(3)}

    result = compute_book_risk(
        weights=weights,
        returns=returns,
        total_equity=1_000_000.0,
        sector_by_symbol={"A2M.AX": "Consumer Staples", "ANZ.AX": "Financials", "BOQ.AX": "Financials"},
        now=NOW,
        min_observations=30,
    )

    assert result.symbols == 3
    assert result.observations >= 30
    assert result.var_95 is not None and result.var_95 > 0
    assert result.var_99 is not None and result.var_99 >= result.var_95
    assert result.es_975 is not None and result.es_975 > 0
    # Largest single name is A2M at 120k of 1M.
    assert result.single_name_pct == 0.12
    # Largest SECTOR is Financials: ANZ 90k + BOQ 60k = 150k of 1M.
    assert result.sector_pct == 0.15
    assert result.notes == ()


def test_var_matches_the_checker_measured_on_the_same_inputs():
    """⚠️ THE COMPARABILITY CLAIM, ASSERTED. These two numbers are displayed
    side by side, so they must be produced by the same instrument. Measuring a
    rail with a different instrument than the rail uses is how 8 August read
    5.02% against a true 5.87%."""
    weights = {"A2M.AX": 120_000.0, "ANZ.AX": 90_000.0}
    returns = {"A2M.AX": _noisy(1), "ANZ.AX": _noisy(2)}
    equity = 1_000_000.0

    live = compute_book_risk(
        weights=weights,
        returns=returns,
        total_equity=equity,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    # The checker with a candidate of ZERO exposure sees the same book.
    checker = PortfolioRiskChecker()
    decision = checker.check(
        existing_weights=weights,
        existing_returns=returns,
        candidate_symbol="A2M.AX",
        candidate_dollar_exposure=0.0,
        candidate_returns=returns["A2M.AX"],
        total_equity=equity,
    )

    assert live.var_95 == decision.historical_var_95
    assert live.var_99 == decision.historical_var_99
    assert live.es_975 == decision.expected_shortfall_975


def test_a_symbol_with_no_returns_is_excluded_from_var_but_not_concentration():
    """The state after a restart before the warm start finishes: a held symbol
    whose aggregator frame is still empty."""
    result = compute_book_risk(
        weights={"A2M.AX": 120_000.0, "ANZ.AX": 300_000.0},
        returns={"A2M.AX": _noisy(1)},
        total_equity=1_000_000.0,
        sector_by_symbol={},
        now=NOW,
        min_observations=30,
    )

    # ANZ has no series, so it cannot enter the combined return math...
    assert result.var_95 is not None
    # ...but it is still held, so it still dominates concentration.
    assert result.single_name_pct == 0.3
    assert result.symbols == 2
```

- [ ] **Step 2: Run the tests to verify they fail or pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/risk_engine/test_book_risk.py -v
```

Expected: these three PASS against Task 2's implementation. If
`test_var_matches_the_checker_measured_on_the_same_inputs` FAILS, the
implementation has diverged from the checker — **fix the implementation, never
the assertion**. If `test_a_real_book_reports_every_metric` fails on
`result.notes == ()`, a note is being added on a clean path; remove it.

- [ ] **Step 3: Commit**

```bash
git add tests/domain/risk_engine/test_book_risk.py
git commit -m "book_risk: assert the live figure equals the checker's, not merely resembles it"
```

---

### Task 4: Settings

**Files:**
- Modify: `src/qat/config.py:98` (immediately after `equity_poll_seconds`)
- Create: `tests/data/test_book_risk_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.book_risk_poll_seconds: float = 60.0`, `Settings.book_risk_min_observations: int = 30`, `Settings.book_risk_max_age_seconds: float = 180.0`.

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_book_risk_settings.py`:

```python
"""The staleness bound is DERIVED from the poll cadence, not chosen.

Item 6 refused searching back through the audit CSV because the most recent
stored value was two days old and measured on a book that no longer existed. A
live value with no age bound is that same failure with a fresher face, so the
bound is asserted here against the cadence rather than written as a magic number.
"""

from __future__ import annotations

from qat.config import Settings


def test_book_risk_defaults():
    # _env_file=None: otherwise this loads the operator's live .env.
    settings = Settings(_env_file=None)
    assert settings.book_risk_poll_seconds == 60.0
    assert settings.book_risk_min_observations == 30
    # Three polls. The bound is DERIVED from the cadence, not chosen.
    assert settings.book_risk_max_age_seconds == 3 * settings.book_risk_poll_seconds
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_book_risk_settings.py -v
```

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'book_risk_poll_seconds'`.

- [ ] **Step 3: Add the settings**

In `src/qat/config.py`, directly after the `equity_poll_seconds` field:

```python
    # --- Live book risk (2026-09-02 spec) ------------------------------------
    # Portfolio risk measured over the book ACTUALLY HELD, because the figure
    # the advisory used to read comes from the last risk DECISION - and with the
    # book at 10 of 10, no decision reaches the portfolio checker at all.
    book_risk_poll_seconds: float = Field(default=60.0, gt=0)

    # Below this many overlapping return observations, VaR and ES are reported
    # as UNKNOWN rather than computed. ⚠️ Not a tuning knob: the underlying
    # compute_historical_var returns 0.0 below two observations, and a zero
    # reaching the model reads as "no tail risk".
    book_risk_min_observations: int = Field(default=30, ge=2)

    # A snapshot older than this is treated exactly as a missing one. Three
    # polls. Item 6 refused a search back through the audit CSV because the most
    # recent stored value was two days old and measured on a book that no longer
    # existed; a live value with no age bound is the same failure with a fresher
    # face.
    book_risk_max_age_seconds: float = Field(default=180.0, gt=0)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_book_risk_settings.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qat/config.py tests/data/test_book_risk_settings.py
git commit -m "config: the three live-book-risk settings, with the staleness bound derived"
```

---

### Task 5: `BookRiskMonitor`

**Files:**
- Modify: `src/qat/domain/risk_engine/book_risk.py`
- Create: `tests/domain/risk_engine/test_book_risk_monitor.py`

**Interfaces:**
- Consumes: `compute_book_risk`, `BookRisk` (Task 2); `Settings` fields (Task 4).
- Produces: `BookRiskMonitor(account_poller, bars, settings=None, sector_by_symbol=None, clock=None)` with `name = "book-risk-monitor"`, `latest: BookRisk | None`, `async start()`, `async stop()`, `async poll() -> BookRisk | None`, and `fresh(now=None) -> BookRisk | None` which returns `latest` only when inside `book_risk_max_age_seconds`.

- [ ] **Step 1: Write the failing tests**

Create `tests/domain/risk_engine/test_book_risk_monitor.py`:

```python
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.risk_engine.book_risk import BookRiskMonitor

NOW = datetime(2026, 9, 2, 17, 0, tzinfo=UTC)


def _bars(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    return pd.DataFrame(
        {"ts": pd.date_range("2026-01-01", periods=n, freq="D"), "close": closes}
    )


class _Aggregator:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def frame_if_present(self, symbol: str, include_forming: bool = True):
        return self._frames.get(symbol)


class _Poller:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot
        self.calls = 0

    async def snapshot(self, force: bool = False):
        self.calls += 1
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot


def _snapshot(positions, equity):
    return SimpleNamespace(
        positions=tuple(positions),
        balances=SimpleNamespace(equity=equity),
    )


def _position(symbol: str, quantity: float, avg_price: float):
    return SimpleNamespace(symbol=symbol, quantity=quantity, avg_price=avg_price)


def _monitor(poller, aggregator, **kwargs) -> BookRiskMonitor:
    return BookRiskMonitor(
        account_poller=poller,
        bars=aggregator,
        settings=Settings(),
        sector_by_symbol={"A2M.AX": "Consumer Staples", "ANZ.AX": "Financials"},
        clock=lambda: NOW,
        **kwargs,
    )


def test_latest_is_none_before_the_first_poll():
    """The state at every startup, which is where the bug this replaces lives."""
    monitor = _monitor(_Poller(_snapshot([], 1.0)), _Aggregator({}))
    assert monitor.latest is None
    assert monitor.fresh() is None


@pytest.mark.asyncio
async def test_a_poll_measures_the_book():
    poller = _Poller(
        _snapshot(
            [_position("A2M.AX", 1000, 120.0), _position("ANZ.AX", 3000, 30.0)],
            1_000_000.0,
        )
    )
    aggregator = _Aggregator({"A2M.AX": _bars(), "ANZ.AX": _bars()})

    result = await _monitor(poller, aggregator).poll()

    assert result is not None
    assert result.symbols == 2
    assert result.var_95 is not None
    assert result.single_name_pct == 0.12


@pytest.mark.asyncio
async def test_a_snapshot_with_no_equity_leaves_latest_alone():
    """AccountSnapshot.balances.equity is None on a failed read. Real state."""
    good = _Poller(
        _snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0)
    )
    aggregator = _Aggregator({"A2M.AX": _bars()})
    monitor = _monitor(good, aggregator)
    await monitor.poll()
    before = monitor.latest
    assert before is not None

    monitor.account_poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], None))
    await monitor.poll()

    assert monitor.latest is before


@pytest.mark.asyncio
async def test_a_raising_poller_is_logged_and_the_previous_value_survives():
    good = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(good, _Aggregator({"A2M.AX": _bars()}))
    await monitor.poll()
    before = monitor.latest

    monitor.account_poller = _Poller(RuntimeError("broker down"))
    await monitor.poll()

    assert monitor.latest is before


@pytest.mark.asyncio
async def test_a_held_symbol_with_no_frame_still_counts_for_concentration():
    poller = _Poller(
        _snapshot(
            [_position("A2M.AX", 1000, 120.0), _position("ANZ.AX", 10000, 30.0)],
            1_000_000.0,
        )
    )
    # ANZ has no frame - the state during a warm start.
    aggregator = _Aggregator({"A2M.AX": _bars()})

    result = await _monitor(poller, aggregator).poll()

    assert result is not None
    assert result.symbols == 2
    assert result.single_name_pct == 0.3


@pytest.mark.asyncio
async def test_it_never_touches_the_broker():
    """⚠️ EquityMonitor's own comment: a separate poller doubles broker traffic
    to record the same number. This engine reads the SHARED throttled poller."""

    class _ExplodingBroker:
        def __getattr__(self, name):
            raise AssertionError(f"BookRiskMonitor called broker.{name}")

    poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(poller, _Aggregator({"A2M.AX": _bars()}))
    monitor.broker = _ExplodingBroker()

    await monitor.poll()

    assert poller.calls == 1


@pytest.mark.asyncio
async def test_fresh_refuses_a_stale_snapshot():
    poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(poller, _Aggregator({"A2M.AX": _bars()}))
    await monitor.poll()

    inside = NOW + timedelta(seconds=179)
    outside = NOW + timedelta(seconds=181)

    assert monitor.fresh(now=inside) is not None
    assert monitor.fresh(now=outside) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/risk_engine/test_book_risk_monitor.py -v
```

Expected: FAIL with `ImportError: cannot import name 'BookRiskMonitor'`.

- [ ] **Step 3: Add the monitor**

Append to `src/qat/domain/risk_engine/book_risk.py`. Add `asyncio`, `contextlib` and `Callable` to the imports at the top:

```python
import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC
from typing import Any
```

Then:

```python
def _returns_from_bars(bars: pd.DataFrame | None) -> pd.Series:
    """Close-to-close returns indexed by TIMESTAMP.

    Deliberately the same shape as `signal_bridge._returns_by_ts`: correlating
    two symbols on a positional index compares one symbol's fifth bar to
    another's fifth bar, which are the same day only if both have identical
    history. Duplicated timestamps are collapsed last-wins, because a duplicated
    index fails the whole portfolio computation - which refused every order for
    a full session on 3 August.
    """
    if bars is None or len(bars) < 2 or "ts" not in bars or "close" not in bars:
        return pd.Series(dtype=float)
    frame = bars[["ts", "close"]]
    frame = frame[~frame["ts"].duplicated(keep="last")]
    if len(frame) < 2:
        return pd.Series(dtype=float)
    closes = frame["close"].astype(float)
    closes.index = pd.DatetimeIndex(frame["ts"])
    return closes.pct_change().dropna()


class BookRiskMonitor:
    """Engine (per domain.orchestrator.Engine protocol).

    ⚠️ IT DOES NOT POLL THE BROKER. `EquityMonitor` already states the principle
    for its own sampler - "a separate poller would double the broker traffic to
    record the same number" - and the dashboard calls `AccountPoller` "one
    shared, throttled read rather than two broker calls per tick". This engine
    reads that same shared poller.
    """

    name = "book-risk-monitor"

    def __init__(
        self,
        account_poller: Any,
        bars: Any,
        settings: Any | None = None,
        sector_by_symbol: dict[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from qat.config import Settings

        self.account_poller = account_poller
        self.bars = bars
        self.settings = settings or Settings()
        self.sector_by_symbol = sector_by_symbol or {}
        self._clock = clock or (lambda: datetime.now(UTC))
        self.latest: BookRisk | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a bad poll must not kill the rails
                logger.exception("Book-risk poll failed; continuing")
            await asyncio.sleep(self.settings.book_risk_poll_seconds)

    async def poll(self) -> BookRisk | None:
        """One measurement.

        ⚠️ A failure LEAVES THE PREVIOUS VALUE STANDING rather than clearing it.
        That is safe only because every value carries `computed_at` and readers
        go through `fresh()`.
        """
        try:
            snapshot = await self.account_poller.snapshot()
        except Exception:  # noqa: BLE001 - the previous measurement survives
            logger.warning("Could not read the account for book risk; keeping the last measurement")
            return self.latest

        equity = getattr(snapshot.balances, "equity", None)
        if equity is None:
            logger.debug("No equity in the account snapshot; keeping the last book-risk measurement")
            return self.latest

        weights = {
            position.symbol: position.quantity * position.avg_price
            for position in snapshot.positions
            if position.quantity
        }
        returns = {
            symbol: series
            for symbol in weights
            if not (series := _returns_from_bars(self.bars.frame_if_present(symbol))).empty
        }

        self.latest = compute_book_risk(
            weights=weights,
            returns=returns,
            total_equity=float(equity),
            sector_by_symbol=self.sector_by_symbol,
            now=self._clock(),
            min_observations=self.settings.book_risk_min_observations,
        )
        return self.latest

    def fresh(self, now: datetime | None = None) -> BookRisk | None:
        """The latest measurement, or None if it is too old to be believed.

        ⚠️ A stale snapshot is treated IDENTICALLY to a missing one. There is no
        third state and no "probably still fine" path - that is what item 6
        refused when it rejected searching back through the audit CSV.
        """
        if self.latest is None:
            return None
        age = self.latest.age_seconds(now or self._clock())
        if age > self.settings.book_risk_max_age_seconds:
            return None
        return self.latest
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/risk_engine/test_book_risk_monitor.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Run the four checks separately**

```bash
.venv/Scripts/python.exe -m ruff check .
```
```bash
.venv/Scripts/python.exe -m black --check .
```
```bash
.venv/Scripts/python.exe -m mypy src
```
```bash
.venv/Scripts/python.exe -m bandit -q -r src
```

Read each output. `black --check` can exit 0 while printing "1 file would be reformatted" — the printed text is the result, not the exit code.

- [ ] **Step 6: Commit**

```bash
git add src/qat/domain/risk_engine/book_risk.py tests/domain/risk_engine/test_book_risk_monitor.py
git commit -m "BookRiskMonitor: sample the book on a timer, off the shared poller"
```

---

### Task 6: Wire the monitor into the runtime

**Files:**
- Modify: `src/qat/presentation/runtime.py` (import; construct near line 644; register in the tuple ending near line 901; add the field near line 528; pass in the `cls(...)` call near line 904)
- Create: `tests/presentation/test_book_risk_monitor_is_wired.py`

**Interfaces:**
- Consumes: `BookRiskMonitor` (Task 5).
- Produces: `Runtime.book_risk_monitor: BookRiskMonitor | None = None`.

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/test_book_risk_monitor_is_wired.py`:

```python
"""An engine that is written but never registered measures nothing.

M119 is the precedent: deployed, correct, and untested by anything for three
days because nothing exercised it. A monitor absent from the orchestrator's
register list would leave every reader on `None` forever while every unit test
passed.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.runtime import Runtime


def test_the_book_risk_monitor_is_built_and_registered(tmp_path):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))

    assert runtime.book_risk_monitor is not None
    assert runtime.book_risk_monitor.name == "book-risk-monitor"

    names = [engine.name for engine in runtime.orchestrator._engines]
    assert "book-risk-monitor" in names, f"registered engines: {names}"


def test_it_shares_the_account_poller_rather_than_holding_a_broker(tmp_path):
    """⚠️ A second poller would double broker traffic to record the same
    number - EquityMonitor's own comment says so."""
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))

    assert runtime.book_risk_monitor.account_poller is runtime.account_poller
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_book_risk_monitor_is_wired.py -v
```

Expected: FAIL with `AttributeError: 'Runtime' object has no attribute 'book_risk_monitor'`.

- [ ] **Step 3: Wire it**

Import beside the other risk-engine imports (near line 74):

```python
from qat.domain.risk_engine.book_risk import BookRiskMonitor
```

Construct it after `signal_bridge` exists (it needs `signal_bridge.bars`), and after `account_poller`:

```python
        # Reads the SHARED throttled poller, never the broker: a second poller
        # would double broker traffic to record the same number. `bars` is the
        # signal bridge's aggregator, warm started with 300 daily bars per
        # symbol - the same source the decision path uses for existing_returns,
        # so the live and decision figures stay comparable.
        book_risk_monitor = BookRiskMonitor(
            account_poller=account_poller,
            bars=signal_bridge.bars,
            settings=settings,
            sector_by_symbol=SECTOR_BY_SYMBOL,
        )
```

Add it to the registration tuple, immediately before `session_controller`:

```python
            book_risk_monitor,
```

Add the dataclass field beside `closer`:

```python
    # Live portfolio risk over the held book (2026-09-02 spec). Optional for the
    # same reason `closer` is: every existing construction of Runtime, including
    # tests that build one directly, stays unaffected.
    book_risk_monitor: BookRiskMonitor | None = None
```

And pass it in the `cls(...)` call:

```python
            book_risk_monitor=book_risk_monitor,
```

If `SECTOR_BY_SYMBOL` is not already imported in `runtime.py`, add:

```python
from qat.data.sectors import SECTOR_BY_SYMBOL
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_book_risk_monitor_is_wired.py -v
```

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add src/qat/presentation/runtime.py tests/presentation/test_book_risk_monitor_is_wired.py
git commit -m "Runtime: build and register the book-risk monitor"
```

---

### Task 7: `risk_metrics()` returns both groups

**Files:**
- Modify: `src/qat/presentation/advisory_account.py:202-224`
- Modify: `src/qat/domain/ai_advisory/context.py:24`
- Modify: `tests/presentation/test_risk_metrics_sees_the_book.py` (Task 1)

**Interfaces:**
- Consumes: `Runtime.book_risk_monitor` (Task 6); the widened tuple (Task 1).
- Produces: `risk_metrics(runtime) -> dict[str, Any]` with keys `book_now`, `book_now_age_seconds`, `book_now_notes`, `at_last_decision` — **each omitted entirely when it has nothing to say**.

- [ ] **Step 1: Write the failing tests**

Append to `tests/presentation/test_risk_metrics_sees_the_book.py` (created in Task 1):

```python
from datetime import UTC, datetime

from qat.domain.risk_engine.book_risk import BookRisk


def _book_risk(**overrides) -> BookRisk:
    base = dict(
        computed_at=datetime(2026, 9, 2, 17, 0, tzinfo=UTC),
        symbols=10,
        observations=299,
        var_95=0.011,
        var_99=0.015,
        es_975=0.017,
        single_name_pct=0.12,
        sector_pct=0.15,
        notes=(),
    )
    base.update(overrides)
    return BookRisk(**base)


class _Monitor:
    def __init__(self, value):
        self._value = value

    def fresh(self, now=None):
        return self._value


def test_a_fresh_book_measurement_reaches_the_model():
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _Monitor(_book_risk())

    metrics = risk_metrics(runtime)

    assert metrics["book_now"]["var_95"] == 0.011
    assert metrics["book_now"]["single_name_pct"] == 0.12
    assert "at_last_decision" not in metrics
    assert "book_now_notes" not in metrics


def test_a_stale_book_measurement_is_absent_not_stale():
    """fresh() already returns None past the bound; risk_metrics must not
    reach around it to self.latest."""
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _Monitor(None)

    assert risk_metrics(runtime) == {}


def test_notes_travel_with_the_measurement():
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = _Monitor(
        _book_risk(var_95=None, var_99=None, es_975=None, notes=("only 4 observations",))
    )

    metrics = risk_metrics(runtime)

    assert "var_95" not in metrics["book_now"]
    assert metrics["book_now_notes"] == ["only 4 observations"]


def test_both_groups_when_both_exist():
    runtime = _runtime_with_audit_entries(
        [_entry(inputs={"portfolio_check": {"var_95": 0.02, "es_975": 0.03}})]
    )
    runtime.book_risk_monitor = _Monitor(_book_risk())

    metrics = risk_metrics(runtime)

    assert metrics["book_now"]["var_95"] == 0.011
    assert metrics["at_last_decision"] == {"var_95": 0.02, "es_975": 0.03}


def test_neither_group_is_still_an_empty_dict():
    runtime = _runtime_with_audit_entries([])
    runtime.book_risk_monitor = None

    assert risk_metrics(runtime) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_risk_metrics_sees_the_book.py -v
```

Expected: FAIL — `risk_metrics` returns the flat decision dict, so `metrics["book_now"]` raises `KeyError`.

- [ ] **Step 3: Rewrite `risk_metrics`**

Replace the whole function in `src/qat/presentation/advisory_account.py`:

```python
_DECISION_FIELDS = ("var_95", "var_99", "es_975", "single_name_pct", "sector_pct")


def risk_metrics(runtime: Any) -> dict[str, Any]:
    """Portfolio risk for the model: the book NOW, and what the last decision saw.

    This read `portfolio_check.get("var_95", 0.0)`, so a metric the last check
    did not record reached the model as a MEASURED ZERO - "no tail risk" - and
    a language model has no way to ask which it was. `to_prompt_text` applies
    exactly this discipline to fundamentals, and says so in the prompt: "fields
    the vendor could not answer are omitted rather than zeroed". Absent is
    omitted here for the same reason.

    ⚠️ TWO GROUPS, BECAUSE THEY ARE NOT THE SAME MEASUREMENT. `at_last_decision`
    is written one rail AFTER the governor's position-count refusal, so with the
    book at 10 of 10 it is absent from 3,533 of 3,596 audit rows - and the audit
    log is in-memory, so it is absent at every startup regardless. `book_now`
    is the book actually held, sampled on a timer.

    ⚠️ `single_name_pct` and `sector_pct` mean DIFFERENT THINGS in the two
    groups: largest-in-book for `book_now`, the CANDIDATE's for
    `at_last_decision`. The prompt text must say so, or the model reads a
    coincidence as agreement.

    Every key is omitted entirely when it has nothing to say. A run with neither
    group returns {}, which `AdvisoryContext` already renders as "none available
    ... treat this as UNKNOWN, not as zero risk".
    """
    metrics: dict[str, Any] = {}

    monitor = getattr(runtime, "book_risk_monitor", None)
    live = monitor.fresh() if monitor is not None else None
    if live is not None:
        book_now = {
            name: float(value)
            for name in _DECISION_FIELDS
            if (value := getattr(live, name)) is not None
        }
        if book_now:
            metrics["book_now"] = book_now
            metrics["book_now_age_seconds"] = round(live.age_seconds(datetime.now(UTC)), 1)
        if live.notes:
            metrics["book_now_notes"] = list(live.notes)

    entries = runtime.risk_engine.audit_log.entries()
    portfolio_check = entries[-1].inputs.get("portfolio_check") if entries else None
    if portfolio_check:
        at_last_decision = {
            name: float(value)
            for name in _DECISION_FIELDS
            if (value := portfolio_check.get(name)) is not None
        }
        if at_last_decision:
            metrics["at_last_decision"] = at_last_decision

    return metrics
```

Add `from datetime import UTC, datetime` and `from typing import Any` to that module's imports if not already present.

- [ ] **Step 4: Widen the context type**

In `src/qat/domain/ai_advisory/context.py` line 24:

```python
    risk_metrics: dict[str, Any]
```

Add `from typing import Any` if absent. Then extend the prompt line so the model is told what the two groups mean — replace the `f"Risk metrics: {self.risk_metrics}"` branch:

```python
            (
                "Risk metrics: "
                + str(self.risk_metrics)
                + " - 'book_now' measures the portfolio you currently hold; "
                "'at_last_decision' is what the risk check saw when it last "
                "evaluated a candidate trade, which may be days old. In "
                "'book_now' the concentration figures are the LARGEST single "
                "name and sector in the book; in 'at_last_decision' they are "
                "the candidate's own. A field that is absent is UNKNOWN, not "
                "zero."
                if self.risk_metrics
                else "Risk metrics: none available - no portfolio risk check has been recorded "
                "yet this session. Treat this as UNKNOWN, not as zero risk."
            ),
```

Also update `advisory_account.py:61` (`risk_metrics: dict[str, float] = field(default_factory=dict)`) to `dict[str, Any]`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_risk_metrics_sees_the_book.py tests/domain/ai_advisory tests/presentation/test_advisory_call_sites_agree.py -v
```

⚠️ Task 1's two tests WILL now fail: they assert the flat shape. Update them to
read `metrics["at_last_decision"]` — that is the fold-in the Interfaces block
warned about, and it is expected, not a regression.

⚠️ `tests/presentation/test_advisory_call_sites_agree.py` exists and asserts the
advisory call sites stay consistent. If it fails, it is telling you a call site
was missed — fix the call site, not the test.

- [ ] **Step 6: Commit**

```bash
git add src/qat/presentation/advisory_account.py src/qat/domain/ai_advisory/context.py tests/
git commit -m "risk_metrics: the book now, and what the last decision saw, told apart"
```

---

### Task 8: `KpiTile` gains a caption

**Files:**
- Modify: `src/qat/presentation/widgets.py:12-26`
- Create: `tests/presentation/test_kpi_tile_caption.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KpiTile.set_caption(text: str | None) -> None`. Passing `None` or `""` **hides** the caption label entirely.

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/test_kpi_tile_caption.py`:

```python
"""A caption that is always present is furniture.

Item 4 of the 2 September milestone scope is about exactly this: a screen region
that never changes is one an operator stops seeing, and the day it says something
alarming it reads as furniture too. So the second line is ABSENT when it has
nothing to say - not a dash, not an empty string.
"""

from __future__ import annotations

from qat.presentation.widgets import KpiTile


def test_a_tile_with_no_caption_hides_the_line_entirely(qtbot):
    """⚠️ Not a dash. Item 4 of the milestone scope is about a screen region
    that is always occupied becoming furniture an operator stops seeing."""
    tile = KpiTile("Portfolio VaR (95%)")
    qtbot.addWidget(tile)
    assert tile._caption.isVisibleTo(tile) is False

    tile.set_caption("at last decision: 2.00%")
    assert tile._caption.text() == "at last decision: 2.00%"
    assert tile._caption.isVisibleTo(tile) is True

    tile.set_caption(None)
    assert tile._caption.isVisibleTo(tile) is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_kpi_tile_caption.py -v
```

Expected: FAIL with `AttributeError: 'KpiTile' object has no attribute '_caption'`.

- [ ] **Step 3: Add the caption**

In `src/qat/presentation/widgets.py`, inside `KpiTile.__init__` after `layout.addWidget(self._value)`:

```python
        # A second line that appears ONLY when it has something to say. A
        # caption that is always present - even as a dash - is the furniture
        # problem: an operator stops reading a region that never changes.
        self._caption = QLabel("")
        self._caption.setStyleSheet(theme.text(theme.MUTED, size=theme.CAPTION))
        self._caption.setVisible(False)
        layout.addWidget(self._caption)
```

And add the method:

```python
    def set_caption(self, text: str | None) -> None:
        self._caption.setText(text or "")
        self._caption.setVisible(bool(text))
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_kpi_tile_caption.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qat/presentation/widgets.py tests/presentation/test_kpi_tile_caption.py
git commit -m "KpiTile: an optional caption that is absent rather than empty"
```

---

### Task 9: Risk Console reads live, captions the decision

**Files:**
- Modify: `src/qat/presentation/risk_console.py:136-140` (labels) and `:570-586` (`_refresh_from_audit_log`)
- Create: `tests/presentation/test_risk_tiles_read_the_live_book.py`

**Interfaces:**
- Consumes: `Runtime.book_risk_monitor.fresh()` (Task 6), `KpiTile.set_caption` (Task 8).
- Produces: nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/test_risk_tiles_read_the_live_book.py`:

```python
"""The VaR tiles have shown "-" since 31 August, and nothing was broken.

They read `audit_log.entries()[-1].inputs["portfolio_check"]` and returned early
when it was absent - which is every startup, because the audit log is in-memory,
and every 10-of-10 day, because the governor refuses one rail before that dict is
written. They now read the book actually held, with the last decision's figure as
a caption BENEATH, and only when there is one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from qat.config import Settings
from qat.domain.risk_engine.book_risk import BookRisk
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _book_risk(**overrides) -> BookRisk:
    base = dict(
        computed_at=datetime.now(UTC),
        symbols=10,
        observations=299,
        var_95=0.011,
        var_99=0.015,
        es_975=0.017,
        single_name_pct=0.12,
        sector_pct=0.15,
        notes=(),
    )
    base.update(overrides)
    return BookRisk(**base)


class _Monitor:
    name = "book-risk-monitor"

    def __init__(self, value):
        self._value = value

    def fresh(self, now=None):
        return self._value


def _entry(inputs: dict) -> SimpleNamespace:
    return SimpleNamespace(inputs=inputs)


def _build(qtbot, tmp_path, book_risk, audit_entries):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    runtime.book_risk_monitor = _Monitor(book_risk)
    runtime.risk_engine.audit_log._entries = list(audit_entries)
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def test_live_value_is_the_headline_and_the_decision_is_the_caption(qtbot, tmp_path):
    console = _build(
        qtbot,
        tmp_path,
        _book_risk(),
        [_entry({"portfolio_check": {"var_95": 0.02, "var_99": 0.03,
                                     "es_975": 0.04, "single_name_pct": 0.05}})],
    )

    console._refresh_risk_tiles()

    assert console.var95_tile._value.text() == "1.10%"
    assert "2.00%" in console.var95_tile._caption.text()


def test_no_decision_means_no_caption_at_all(qtbot, tmp_path):
    """The common case: the audit log is in-memory and empty at every startup."""
    console = _build(qtbot, tmp_path, _book_risk(), [])

    console._refresh_risk_tiles()

    assert console.var95_tile._value.text() == "1.10%"
    assert console.var95_tile._caption.isVisibleTo(console.var95_tile) is False


def test_no_live_measurement_shows_a_dash_not_a_zero(qtbot, tmp_path):
    console = _build(qtbot, tmp_path, None, [])

    console._refresh_risk_tiles()

    assert console.var95_tile._value.text() == "-"


def test_the_concentration_tile_is_relabelled(qtbot, tmp_path):
    """⚠️ The decision path's single_name_pct is the CANDIDATE's; the live one
    is the largest in the book. One label over two meanings invites a reader to
    treat a coincidence as agreement."""
    console = _build(qtbot, tmp_path, _book_risk(), [])

    assert "Largest single name" in console.concentration_tile._label.text()
```

⚠️ If `KpiTile` does not expose `_label`, read `widgets.py` and use whatever it
does expose. Do not add a public accessor purely for the test.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_risk_tiles_read_the_live_book.py -v
```

Expected: FAIL — `_refresh_risk_tiles` does not exist.

- [ ] **Step 3: Rewrite the refresh**

Rename `_refresh_from_audit_log` to `_refresh_risk_tiles` (update its call site in the same file) and replace the body:

```python
    def _refresh_risk_tiles(self) -> None:
        """Live book risk as the headline; the last decision's figure as a
        caption, and ONLY when there is one.

        ⚠️ This used to read `entries[-1].inputs["portfolio_check"]` and return
        early when it was absent - which is every startup, because the audit log
        is in-memory, and every 10-of-10 day, because the governor refuses one
        rail before that dict is written. The tiles sat at "-" from 31 August.
        """
        monitor = getattr(self.runtime, "book_risk_monitor", None)
        live = monitor.fresh() if monitor is not None else None

        entries = self.runtime.risk_engine.audit_log.entries()
        decision = entries[-1].inputs.get("portfolio_check") if entries else None

        es_limit = self.runtime.settings.portfolio_es_limit_pct

        def _pct(value: float | None) -> str:
            return "-" if value is None else f"{value:.2%}"

        def _caption(name: str) -> str | None:
            if not decision:
                return None
            value = decision.get(name)
            return None if value is None else f"at last decision: {value:.2%}"

        self.var95_tile.set_value(_pct(getattr(live, "var_95", None)))
        self.var95_tile.set_caption(_caption("var_95"))

        self.var99_tile.set_value(_pct(getattr(live, "var_99", None)))
        self.var99_tile.set_caption(_caption("var_99"))

        es_value = getattr(live, "es_975", None)
        self.es_tile.set_value(
            "-" if es_value is None else f"{es_value:.2%} / {es_limit:.0%}",
            color=None if es_value is None else (theme.DANGER if es_value >= es_limit else theme.SUCCESS),
        )
        self.es_tile.set_caption(_caption("es_975"))

        self.concentration_tile.set_value(_pct(getattr(live, "single_name_pct", None)))
        caption = _caption("single_name_pct")
        self.concentration_tile.set_caption(
            None if caption is None else caption.replace("at last decision", "candidate at last decision")
        )
```

Relabel the two concentration tiles at their construction (lines 136-139):

```python
        self.concentration_tile = KpiTile("Largest single name")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/ -k risk_console -v
```
```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_risk_tiles_read_the_live_book.py -v
```

Expected: PASS. ⚠️ There are five existing `test_risk_console_*.py` files; if any
calls `_refresh_from_audit_log` by name, update the call site there too.

- [ ] **Step 5: Commit**

```bash
git add src/qat/presentation/risk_console.py tests/presentation/test_risk_tiles_read_the_live_book.py
git commit -m "Risk Console: the book now as the headline, the last decision beneath"
```

---

### Task 10: Dashboard VaR tile reads live

**Files:**
- Modify: `src/qat/presentation/dashboard.py:476-481`
- Create: `tests/presentation/test_workbench_var_tile.py`

**Interfaces:**
- Consumes: `Runtime.book_risk_monitor.fresh()` (Task 6).
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/test_workbench_var_tile.py`. It sits beside the
existing `test_workbench_equity_axis.py` and `test_workbench_levels.py`, which is
where Workbench/dashboard behaviour is tested in this repo:

```python
"""The Workbench VaR tile measured the last DECISION, not the book.

Same root cause as the Risk Console tiles: `portfolio_check` is written one rail
after the governor's position-count refusal, so at 10 of 10 it is never written,
and the audit log is in-memory so it is empty at startup regardless. This tile
now reads the book actually held. No side-by-side here - one summary tile on a
crowded screen; the Risk Console carries the comparison.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.domain.risk_engine.book_risk import BookRisk
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime


def _book_risk(**overrides) -> BookRisk:
    base = dict(
        computed_at=datetime.now(UTC),
        symbols=10,
        observations=299,
        var_95=0.011,
        var_99=0.015,
        es_975=0.017,
        single_name_pct=0.12,
        sector_pct=0.15,
        notes=(),
    )
    base.update(overrides)
    return BookRisk(**base)


class _Monitor:
    name = "book-risk-monitor"

    def __init__(self, value):
        self._value = value

    def fresh(self, now=None):
        return self._value


def _build(qtbot, tmp_path, book_risk):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    runtime.book_risk_monitor = _Monitor(book_risk)
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)
    return screen


@pytest.mark.asyncio
async def test_the_var_tile_reads_the_live_book(qtbot, tmp_path):
    dashboard = _build(qtbot, tmp_path, _book_risk())

    await dashboard._refresh()

    assert dashboard.var_tile._value.text() == "1.10%"


@pytest.mark.asyncio
async def test_the_var_tile_shows_a_dash_with_no_live_measurement(qtbot, tmp_path):
    dashboard = _build(qtbot, tmp_path, None)

    await dashboard._refresh()

    assert dashboard.var_tile._value.text() == "-"
```

⚠️ `_refresh` awaits `account_poller.snapshot()`. Read
`test_workbench_equity_axis.py` first — if it seeds the poller's cached
`_snapshot` before calling `_refresh`, do the same here rather than letting the
demo broker be hit.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_workbench_var_tile.py -v
```

Expected: FAIL — the tile still reads the audit log.

- [ ] **Step 3: Replace the tile update**

In `src/qat/presentation/dashboard.py`, replace:

```python
        latest_decisions = self.runtime.risk_engine.audit_log.entries()
        if latest_decisions:
            portfolio_check = latest_decisions[-1].inputs.get("portfolio_check")
            if portfolio_check and "var_95" in portfolio_check:
                self.var_tile.set_value(f"{portfolio_check['var_95']:.2%}")
```

with:

```python
        # The book NOW, not the last decision. One summary tile on a crowded
        # screen, so no side-by-side here - the Risk Console carries that.
        monitor = getattr(self.runtime, "book_risk_monitor", None)
        live = monitor.fresh() if monitor is not None else None
        var_95 = getattr(live, "var_95", None)
        self.var_tile.set_value("-" if var_95 is None else f"{var_95:.2%}")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/ -k workbench -v
```

Expected: PASS, including the existing workbench tests.

- [ ] **Step 5: Commit**

```bash
git add src/qat/presentation/dashboard.py tests/presentation/test_workbench_var_tile.py
git commit -m "Dashboard: the VaR tile reads the book now"
```

---

### Task 11: Full verification

**Files:** none modified unless a check fails.

- [ ] **Step 1: Run the whole suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: every test passes. The count should be roughly 3,076 + ~30 new. Read the final line — do not infer from the exit code alone.

- [ ] **Step 2: Run ruff**

```bash
.venv/Scripts/python.exe -m ruff check .
```

- [ ] **Step 3: Run black**

```bash
.venv/Scripts/python.exe -m black --check .
```

⚠️ Read the printed output. This command can exit 0 while printing "1 file would be reformatted".

- [ ] **Step 4: Run mypy**

```bash
.venv/Scripts/python.exe -m mypy src
```

- [ ] **Step 5: Run bandit**

```bash
.venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 6: Sabotage check — prove the central rail bites**

⚠️ **Commit everything first.** `git checkout` on an *uncommitted* file discards
the real edit along with the sabotage; that happened on 2 September.

```bash
git status --porcelain
```

Expected: empty. If not, commit before continuing.

Then temporarily change `book_risk.py` so the observation gate is skipped —
replace `if observations < min_observations:` with `if False:` — and run:

```bash
.venv/Scripts/python.exe -m pytest tests/domain/risk_engine/test_book_risk.py -k one_observation -v
```

Expected: **FAIL**, showing `var_95 == 0.0` instead of `None`. That is the whole
point of the rail, seen to bite. Restore it:

```bash
git checkout src/qat/domain/risk_engine/book_risk.py
```

Then confirm the restore:

```bash
git status --porcelain
```

Expected: empty.

- [ ] **Step 7: Commit the milestone note**

Bump `MILESTONE` in `src/qat/version.py` with a comment block covering: why the
advisory saw no portfolio risk (the governor rail ordering plus the in-memory
audit log), the absent-is-None rule and the 0.0 trap it avoids, that the live and
decision numbers are computed by the same instrument, and that the two
concentration fields mean different things and are labelled differently.

```bash
git add src/qat/version.py
git commit -m "M164: portfolio risk measured on the book actually held"
```

- [ ] **Step 8: Report, do not deploy**

Deploying is a separate, operator-gated step: build, check the dist hash MOVED,
sign, dry run `scripts\deploy.ps1`, **ask**, then `-Apply`, then read the build
stamp back off the app's own log. Do not begin it as part of executing this plan.

---

## Self-review notes

- **Spec coverage:** section A → Tasks 2, 3; section B → Tasks 4, 5, 6; section C → Tasks 7, 8, 9, 10; section D → Task 1. "Not in this design" (equity axis) → no task, correctly. Error handling → Tasks 2, 5 (the `_absent` paths, the swallowing poll loop). Testing → every task's own steps plus Task 11.
- **Test paths were verified, after the first draft got all seven wrong.** This repo names test files for the BEHAVIOUR, not the module: there is no `test_dashboard.py`, `test_widgets.py`, `test_runtime.py` or `tests/test_config.py`. Every test file above is a NEW behaviour-named file, and the fixtures (`qtbot`, `tmp_path`, `Runtime.build_demo`, `Settings(_env_file=None, ...)`, PySide6) are copied from `test_risk_console_anomalies.py`, which was read.
- **Residual shape risk, named rather than hidden:** the private attributes `KpiTile._value` / `._label`, `AuditLog._entries` and `AccountPoller._snapshot` are used by the new tests. The first two are unread by me in full and the third is used this way by an existing test. If any does not exist, read the module and use what does — do not add a public accessor purely to satisfy a test.
- **Type consistency:** `fresh()` is the only accessor any reader calls — no reader touches `latest` directly, which is what keeps the staleness bound unbypassable. `_DECISION_FIELDS` is the single tuple both groups iterate.
