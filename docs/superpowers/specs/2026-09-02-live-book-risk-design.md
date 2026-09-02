# Design — live portfolio risk over the current book

**2 September 2026.** Follows item 6 of
`docs/superpowers/specs/2026-09-02-milestone-scope.md`, which measured *why* the
AI advisory has never seen portfolio risk. This is the fix the operator chose:
option **(c) + (b)** — compute risk over the book actually held, and widen the
audit read.

**Nothing here is built or deployed yet.** Every file is under `src/`, so it is
compiled into the exe and needs a build, deploy and read-back after a close.

---

## The problem, in one paragraph

`risk_metrics()` reads `audit_log.entries()[-1].inputs["portfolio_check"]`. That
dict is written at `engine.py:311`, one rail *after* the governor's position-count
rejection returns at `engine.py:283` — so while the book is at 10 of 10, no
candidate ever reaches the portfolio checker and no number is recorded. Measured:
3,533 of 3,596 audit rows carry the single reason *"already at the 10-position
limit"*, all buys, all stopping at the `governor` key. Worse, `AuditLog._entries`
is **in-memory and never rehydrated** (`audit.py:70`), so `entries()` is empty at
every startup regardless. The model gets `{}`.

The advisory wants **current portfolio risk** and is reading a **decision
artefact**. Those are different things, and only one of them is what the tile
labelled "Portfolio VaR (95%)" claims to show.

---

## A. `book_risk.py` — the computation

New module `src/qat/domain/risk_engine/book_risk.py`.

```python
@dataclass(frozen=True, slots=True)
class BookRisk:
    computed_at: datetime
    symbols: int            # positions with a usable return series
    observations: int       # length of the combined portfolio return series
    var_95: float | None
    var_99: float | None
    es_975: float | None
    single_name_pct: float | None
    sector_pct: float | None
    notes: tuple[str, ...]  # why a field is None, in the operator's words
```

```python
def compute_book_risk(
    *,
    weights: dict[str, float],
    returns: dict[str, pd.Series],
    total_equity: float,
    sector_by_symbol: dict[str, str] | None,
    now: datetime,
    min_observations: int,
) -> BookRisk
```

### ⚠️ The one rail that matters: absent is None, never 0.0

`compute_historical_var` and `compute_expected_shortfall` both `return 0.0` when
`len(returns) < 2` (`portfolio_risk.py:30`, `:39`). A live path that called them
blindly would hand the model **"no tail risk"** for a book it could not measure —
the precise failure `risk_metrics()`'s own docstring was written to prevent:

> *"a metric the last check did not record reached the model as a MEASURED ZERO
> — 'no tail risk' — and a language model has no way to ask which it was."*

So `compute_book_risk` **gates on the observation count before calling**, and
returns `None` plus a note. It never converts an unmeasurable quantity into a
number.

### Same instrument as the decision path

It reuses `PortfolioRiskChecker._combined_portfolio_returns`, already a
`@staticmethod` over `(weights, returns, total_equity)` (`portfolio_risk.py:133`),
and the module-level `compute_historical_var` / `compute_expected_shortfall`.

⚠️ **This is a requirement, not a convenience.** The two numbers are about to be
displayed side by side, so they must be computed the same way or the comparison
is meaningless. Measuring a rail with a different instrument than the rail uses is
how 8 August read 5.02% against a true 5.87%.

### `min_observations`

Settings-backed `book_risk_min_observations`, default **30**. Below it, the VaR
and ES fields are `None` with a note naming the count. Thirty daily bars is
enough that a 95% percentile is more than the single worst day; 99% is thinner
even at 30, and the note says so rather than pretending otherwise.

⚠️ **Known asymmetry, recorded rather than hidden:** the decision path has no such
floor — it reports on whatever it gets. In practice both draw on the same
warm-started 300-bar history so both will sit near 299 observations, and the floor
only bites on a genuinely thin book. When it does bite, the live value reads
absent while the decision value shows a number, and that divergence is *correct*
and explained by the note.

### Field-by-field behaviour

| field | None when |
|---|---|
| `var_95`, `var_99`, `es_975` | `observations < min_observations`, or no positions |
| `single_name_pct` | no positions, or `total_equity <= 0` |
| `sector_pct` | no position's symbol is in `sector_by_symbol` |

An empty book yields every field `None` with the note *"no positions held"* — not
zeros. A book with no equity yields the same, noting the equity read failed.

### ⚠️ The two concentration fields do NOT mean the same thing on both sides

Found while reading `PortfolioRiskChecker.check` to write the plan, and it would
have made the side-by-side display quietly misleading:

* the **decision** `single_name_pct` is the **candidate's** weight over equity
  (`portfolio_risk.py:99`) — a statement about the trade being considered
* the **decision** `sector_pct` is the **candidate's sector** gross over equity
* there is no candidate in a live book, so the live equivalents are the **maximum
  over the book**: the most concentrated single name, and the most concentrated
  sector

VaR and ES have no such asymmetry — both are properties of a combined return
series, and the live series simply omits the candidate.

**Therefore the two concentration figures are labelled differently wherever they
appear together.** The live pair reads *"largest single name"* / *"largest
sector"*; the decision pair reads *"candidate single name"* / *"candidate
sector"*. Putting `12.5%` beside `12.5%` under one shared label would invite the
reader to treat a coincidence as agreement.

### Weights are cost basis, matching the decision path exactly

`existing_weights` is built as `quantity * avg_price` (`signal_bridge.py:1467`),
so the live path uses the same and **not** the broker's mark.

⚠️ Residual, recorded rather than hidden: that is cost basis, not current value,
so a book that has moved a long way from entry is weighted by what it cost rather
than what it is worth. `Position.mark` exists (M66) but is `None` on adapters that
do not report one, which would introduce both a missing-data path and a silent
divergence from the number displayed next to it. Comparability wins here; if the
mark is ever wanted, **both** sides move together or neither does.

---

## B. `BookRiskMonitor` — the sampler

Engine per `domain.orchestrator.Engine` (`name`, `start`, `stop`, and a public
`poll()` that tests and the UI can await directly — the shape `EquityMonitor`
already uses).

* **Cadence:** `book_risk_poll_seconds`, default `60.0`, matching the equity poll.
* ⚠️ **It does NOT poll the broker.** Positions and equity come from the shared
  throttled `account_poller.snapshot()`. `EquityMonitor`'s own comment states the
  principle — *"a separate poller would double the broker traffic to record the
  same number"* — and the dashboard already calls the poller *"one shared,
  throttled read rather than two broker calls per tick"*.
* **Returns** come from the `MultiSymbolAggregator` at `signal_bridge.bars`, warm
  started with 300 daily bars per watchlist symbol, through the same
  `_returns_by_ts` helper the bridge uses to build `existing_returns`. Same source
  as the decision path, for the same reason as above.
* **Sectors** from `SECTOR_BY_SYMBOL`, so this inherits M162's
  `test_watchlist_symbols_all_have_sectors` guard for free.
* **State:** `latest: BookRisk | None`, `None` until the first successful poll.
* **A failed poll logs and leaves the previous value standing.** That is safe only
  because the value carries `computed_at` and readers enforce the bound below.
  The poll loop swallows `Exception` the way `EquityMonitor._run` does — a bad
  poll must not kill the rails.

### Staleness — derived, not chosen

`book_risk_max_age_seconds`, default **180** — three polls. A reader treats an
older snapshot as **absent**, exactly as it treats `None`.

⚠️ This bound is the whole reason the number can be trusted. Item 6 refused a
search-back through the audit CSV because the most recent stored value was two
days old and computed on an eight-position book that no longer existed. A live
value with no age bound would be the same failure with a fresher-looking face.

---

## C. The readers — both values, side by side

The operator chose to show the live figure **and** the last decision's figure
together, so the divergence is visible rather than inferred.

### Risk Console (`risk_console.py:574`)

Each of the four tiles: the **live** value as the headline, and beneath it, in
muted caption type, `at last decision: x`.

⚠️ The two concentration tiles are **relabelled**, per the asymmetry recorded in
section A: `Largest single name` and `Largest sector` for the live headline, with
the caption reading `candidate at last decision: x`. The VaR and ES tiles keep
their existing labels, because those two figures do mean the same thing on both
sides.

⚠️ **When there is no decision-derived value, the second line is omitted
entirely** — not rendered as a dash. That is the common case today, because the
audit log is empty at every startup, and item 4 of the scope doc is precisely
about a screen region that is always occupied becoming furniture an operator
stops seeing. A second line that is present only when it says something is the
version that keeps its meaning.

Tiles read absent as `"-"`, which `KpiTile` already defaults to
(`widgets.py:13`) — a dash, not a zero. That part of the existing behaviour is
already right and is kept.

### Dashboard (`dashboard.py:479`)

`var_tile` shows the **live** value only. It is one summary tile on a crowded
screen; the side-by-side comparison belongs on the Risk Console, which is where
the operator goes to read risk.

### `risk_metrics()` (`advisory_account.py:202`)

Returns both sets, labelled distinctly so the model can tell a measurement of the
current book from a measurement taken during a past decision. Absent fields stay
omitted — the existing `is not None` discipline is preserved exactly.

The return type widens from `dict[str, float]` to `dict[str, Any]` with this
exact shape, **every key omitted entirely when it has nothing to say** rather
than present-and-empty:

```python
{
    "book_now": {"var_95": .., "var_99": .., "es_975": ..,
                 "single_name_pct": .., "sector_pct": ..},
    "book_now_age_seconds": float,          # only when "book_now" is present
    "book_now_notes": [str, ...],           # only when non-empty
    "at_last_decision": {..same five keys..},
}
```

So a run with a fresh live snapshot and no decision yields exactly two keys; a
run with neither yields `{}`, as today. Callers of `risk_metrics()` must be
updated together; the prompt text must name which group is which, the way
`to_prompt_text` already states that *"fields the vendor could not answer are
omitted rather than zeroed"*.

---

## D. Widen the audit read (option b)

`risk_metrics()` filters the decision-derived dict to the hardcoded tuple
`("var_95", "es_975")`. Widen it to `("var_95", "var_99", "es_975",
"single_name_pct", "sector_pct")`.

Measured across all 63 rows that carry a `portfolio_check`:

    var_95           non-null 63/63
    var_99           non-null 63/63    <- currently dropped, always available
    es_975           non-null 63/63
    single_name_pct  non-null 63/63    <- currently dropped, always available
    sector_pct       non-null  3/63    <- self-omits via the existing filter

Safe by construction: the existing `if (value := ...) is not None` comprehension
already omits `sector_pct` on the 60 occasions it is null. Independent of A–C and
strictly smaller.

---

## Not in this design

**The equity-curve Y axis is NOT changed.** It was scoped and the operator
initially chose change-from-day-start with the history filtered to today, then
withdrew it once the cost was stated: M56 deliberately seeds the chart from
`equity_curve.csv` so the axis can show that the market was shut overnight, and
filtering to today reintroduces exactly the blindness M56 removed. The axis stays
as it is. Scope item 3 is **decided, not open** — revisit only if the unreadable
$137-on-$1M line becomes the greater cost.

---

## Error handling

* Absent is absent everywhere. **No metric is ever defaulted to `0.0`.** This is
  the single rule the whole design turns on.
* The monitor's poll loop swallows `Exception` and logs, matching
  `EquityMonitor._run`.
* Every reader is inside the existing *"a dashboard must still open"* discipline:
  a failure logs and leaves the previous rendering.
* A stale snapshot is treated identically to no snapshot. There is no third state
  and no "probably still fine" path.

---

## Testing

⚠️ **The manual-close branch is the standard to beat here.** It was rejected by
whole-branch review three times, every time with 3,000+ tests passing, and every
time because a fake did not model the real thing. The tests below are written
against the states that actually exist **at startup**, because startup is where
this bug lives.

**`compute_book_risk`**
* empty book → every field `None`, note *"no positions held"*, and **not** `0.0`
* exactly 1 observation → `None` + note. ⚠️ This is the test that would have
  caught a naive implementation: the underlying function returns `0.0` here.
* `observations` below `min_observations` → VaR/ES `None`, `single_name_pct`
  still computed (it needs no return history)
* a normal ten-symbol book → all five populated, and **equal to what
  `PortfolioRiskChecker` produces from the same inputs** — the comparability claim
  asserted, not assumed
* no symbol in the sector map → `sector_pct` is `None`, everything else survives
* `total_equity <= 0` → all `None` with a note

**`BookRiskMonitor`**
* `latest` is `None` before the first poll
* an `account_poller` snapshot whose equity is `None` → poll completes, `latest`
  unchanged, nothing raised
* a held symbol with no frame in the aggregator → excluded from `symbols`, the
  rest still measured
* a raising poller → logged, previous `latest` retained, loop alive
* it makes **no** direct broker call (asserted against a broker double that fails
  the test if touched)

**Staleness**
* a snapshot older than `book_risk_max_age_seconds` reads as absent in **all
  three** readers — advisory, console, dashboard
* one second inside the bound still reads as present

**Readers**
* console tile with live present and decision absent → **no second line at all**
* console tile with both → headline live, caption `at last decision: x`
* `risk_metrics()` with both absent → `{}`
* `risk_metrics()` decision-derived dict carrying all five keys → all five
  returned; with `sector_pct: None` → four returned

---

## Sequencing

D is smallest and lands first, alone. A is pure and lands next with its own
tests. B needs A. C needs both, and touches three UI call sites.

⚠️ **D and C edit the same function.** D widens the tuple inside today's
`dict[str, float]`; C then rewrites the return shape around it. That is
deliberate — D is worth having on its own even if C is deferred — but whoever
does C must fold D's widened tuple into the `at_last_decision` group rather than
reintroducing the two-name version from memory.

⚠️ Everything is in `src/`, so **nothing here is visible until a build, deploy and
read-back**, which lands after a close.
