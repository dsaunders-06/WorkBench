# One symbol, one recommendation — design

**Outstanding item 16.** The AI Advisor and the Strategy Workbench both form a
buy/sell/hold recommendation about a symbol, from different and incomplete
inputs, and can therefore reach different views of one company at one moment for
no stated reason. This unifies them and gives the answer a deterministic half.

Agreed with the operator on 21 August 2026: **the verdict leads and the model
explains it**; the work lands on the Advisor with the Workbench brought to
context parity; and **sell and hold are in scope**, not only entry.

---

## What is actually wrong today

Three defects, in ascending order of severity.

**1. The Workbench does not know the regime.** It passes
`regime_label="unknown"` and `regime_probs={}` (`workbench.py:506`), so its
recommendation is formed against no regime at all while the Advisor's is formed
against the live one.

**2. Neither screen fills the context it already has.** The Advisor passes an
empty `candidate_signal` and no `backtest_stats`; the Workbench passes no
`operator_question`, `positions` or `risk_metrics`.

> **CORRECTED while planning, 22 August.** An earlier version of this section
> also claimed both screens should pass `macro_signal` and `macro_series`,
> on the belief that the deterministic macro read was sitting on the runtime
> waiting to be handed over. **It is not.** `compute_macro_signal` needs an
> awaited `get_daily_bars` fetch for the benchmark, and the Regime Monitor
> computes it only when the operator presses *Analyse* — so there is no
> current value to pass, and passing one would mean a vendor call on every
> question.
>
> **Macro is therefore out of scope here**, and deliberately not faked from a
> stale or absent value. Where the macro read should live and when it should
> refresh is its own question, and answering it badly inside an advisory
> change would be the worse outcome. The `macro_signal` and `macro_series`
> fields stay empty, which the prompt already renders as absent rather than as
> zero.

**3. ⚠️ The model cannot see anything about a position it is asked to judge.**
The Advisor passes `positions = {p.symbol: p.quantity ...}` and nothing more. For
a symbol the account actually holds, the model knows the share count and **no
entry price, no P&L, no R multiple, no stop, no minimum-hold state and no time
stop**. It has been forming sell and hold opinions with nothing to form them
from. This is the most serious of the three and it is the reason the design
branches.

## The shape of the fix

`domain/oms/position_view.py` already computes the entire hold-and-sell picture,
purely and injectably, and `dashboard.py:427` already wires it.
`minimum_hold_status` was extracted specifically *"so a second caller can report
the identical decision instead of re-deriving it"*. Nothing new needs computing;
this is the M126 shape once more — material computed, displayed in one place, and
invisible to the advisor.

---

## Component 1 — the verdict

A pure module, `src/qat/presentation/symbol_verdict.py`, beside
`advisory_inputs.py` and for the same stated reason: functions rather than a
mixin and **no Qt**, so the rules can be tested without constructing a screen.

```python
@dataclass(frozen=True, slots=True)
class RuleCheck:
    name: str
    # None means NOT KNOWABLE NOW - never rendered as a pass or a fail.
    passed: bool | None
    detail: str


@dataclass(frozen=True, slots=True)
class StrategyRules:
    """The rails that depend on WHICH strategy is asking."""

    strategy: str
    checks: tuple[RuleCheck, ...]
    # The first rail that would refuse, or "" when none would. NOT a claim that
    # every rail was evaluated - see "What this does not check".
    first_refusal: str


@dataclass(frozen=True, slots=True)
class SymbolVerdict:
    symbol: str
    held: bool
    # Symbol-level and strategy-independent: session, allow lists, quarantine,
    # and - on the held branch - the position's own facts.
    checks: tuple[RuleCheck, ...]
    # One entry per DEPLOYED strategy. Split from `checks` because regime
    # eligibility and promotion are per-strategy while the session and the
    # allow list are not, and flattening them would make a two-strategy account
    # repeat the symbol-level rails once per strategy.
    per_strategy: tuple[StrategyRules, ...]
    headline: str
```

### Every rail is asked of its owner, never reimplemented

The rails are spread across four subsystems and there is no single place that
answers "would this trade be allowed". A verdict that reimplemented any of them
would be a second derivation of a decision that already has one, which is the
failure this codebase has met repeatedly — `trading_date` with one caller of
four (M120), and `minimum_hold_status` before it was extracted.

| Question | Asked of | Purity |
|---|---|---|
| Does the regime permit this strategy? | `StrategyEngine.is_eligible` + `eligible_mass` | pure read |
| Would an order be permitted now? | `AutonomyGate.evaluate` | documented "pure decision function" |
| Is the market open, and in which phase? | `market_calendar.session_for` | pure |
| Is the symbol enterable? | `OMS.entry_permitted` (new, see below) | pure |
| Is it quarantined? | `OMS.anomalies.is_quarantined` | pure read |
| Is a position held, and how is it tracking? | `build_position_views` | pure |
| Does the minimum hold block a sell? | `minimum_hold_status` | pure, already extracted for this |

### How the gate is asked a hypothetical

`AutonomyGate.evaluate` takes an `Order` and an `AccountState`, so the verdict
constructs a **probe order**: `status="pending_signoff"`, `quantity=1`, side
`"buy"` on the unheld branch and `"sell"` on the held one, `strategy` set to the
deployed strategy being asked about, and `reference_price` set to the last
price so the gate's price-drift rail has something real to compare.
`AccountState` comes from the account poller's latest snapshot, which the
Dashboard already reads.

**`quantity=1` is a probe, not a size**, and the distinction is load-bearing.
The gate's own rails - execution mode, kill switch, session phase, promotion
evidence, day P&L, price drift - do not depend on quantity beyond requiring it
to be positive. The rails that DO depend on size live in the OMS and the risk
engine: the per-order notional cap and the sizer. Those are not asked, and
"What this does not check" says so. A probe of one share therefore answers the
gate's question faithfully and answers no question about size at all.

**One targeted change.** `OMS.submit_order` opens with two membership tests —
symbol allow list, then entry allow list — before any side effect. They are
lifted into a pure `entry_permitted(symbol) -> str | None` returning the refusal
reason or None, which `submit_order` then calls. One implementation, two
readers, rather than the verdict growing a copy.

### The branch

Held and unheld share almost no rails, so the verdict computes one set or the
other and says which it computed.

**Not held — could this be entered?** Regime eligibility with its mass figure,
the autonomy gate, session phase, entry and symbol allow lists, corporate-action
quarantine.

**Held — should this be sold or kept?** Entry basis, P&L in percent and in R,
distance to the strategy's own exit condition, whether a stop is resting and how
far away, the minimum hold and whether the 0.5R loss escape applies, time-stop
proximity, and the share of the risk cap the position occupies.

The sell rails genuinely differ: **the autonomy gate does not gate sells on
session phase** — risk-reducing orders are not held to appetite limits — so what
binds a sell is the minimum hold, the time stop, quarantine and protection
state. A sell verdict reporting entry-side rails would answer the wrong question.

**The recommendation space differs with the branch.** Held is sell-or-hold;
unheld is buy-or-stand-aside. The model may say what it likes about an unheld
symbol; the verdict beside it must not imply a sell is available when there is
nothing to sell.

### ⚠️ What this does not check, and says so on screen

* **It never calls the risk engine.** `RiskEngine.evaluate_*` writes
  `risk_decisions.csv` at three sites, so asking it a hypothetical would file
  risk decisions for trades nobody proposed, into the audit trail
  `session_check` reports on and whose row count is a reviewed figure. **A
  defect that corrupts the record is fix-immediately**, and this design will not
  create one. The verdict therefore says what the GATES say and never what the
  sizer would do.
* **It does not judge price staleness**, which is decided at order time against
  a live tick.
* **The earnings blackout is not a permission check.** It is a SIZE scalar. The
  verdict reports the results date and says it affects size, not permission.
* **The autonomy gate short-circuits**, returning the first refusal rather than
  enumerating all of them. The panel says "the first rail that would refuse",
  which is true, rather than implying a complete audit.

A check that cannot be answered yet — regime eligibility before any
`RegimeEvent` has arrived — is `passed=None` and renders as *not yet known*.
**Unknown is not a pass**, the same discipline `preflight` enforces.

## Component 2 — the context merge

Two new `AdvisoryContext` fields, carried as **plain dicts** following the
precedent that module sets for `macro_signal`, `fundamentals` and `news`: it
deliberately imports nothing from the rest of the domain, which is what lets the
safety tests build a context in isolation.

```python
position: dict[str, Any] = field(default_factory=dict)      # empty when not held
rule_checks: list[dict[str, Any]] = field(default_factory=list)
```

One builder in `advisory_inputs.py` — already "the per-symbol material an
advisory answer is entitled to" — assembles the full context, and **both screens
call it**. That closes all three defects above at once.

**The verdict travels as fact, not as fetched text.** `fetched_notes` exists to
quarantine third-party material. The rule checks are the application's own
deterministic output about itself, and filing them there would repeat exactly
the misfiling M117 corrected when the operator's own question was travelling in
the untrusted channel.

`to_prompt_text` renders both new blocks with the established discipline: a
figure the source could not supply is omitted or stated as absent, never zeroed.
M73 exists because `0.0` for an unrecorded VaR reached the model as "no tail
risk".

## Component 3 — display and framing

The Advisor's conversation gains a verdict block above each answer, in the place
and style of the sources block, so each answer keeps its own and scrolling back
shows the state that reply was given under.

**The framing needs one distinction drawn carefully.** M73's label says the
recommendations "reach no part of the trading system". The verdict is the
opposite kind of statement — it IS the trading system's own state — and left
ambiguous, "the rails would permit a buy" under "[BUY, confidence 80%]" reads as
the application endorsing a trade, which is the inference M73 exists to prevent.

So the verdict is worded as a **conditional about what would happen**, never as
a suggestion:

> If an entry in BHP.AX were proposed now, the first rail to refuse would be:
> session phase "Opening Volatility" is not eligible for unattended execution.

and for a held symbol:

> BHP.AX is held. A signal-driven sell is blocked until 3 September (minimum
> hold); the 0.5R loss escape does not apply at −0.21R. A protective stop rests
> at 41.18.

The model's answer stays advisory, the verdict states machine facts, neither is
an instruction. **The M73 label itself is unchanged**, and it is not made
level-aware — safety is not a level.

The Workbench receives the context parity but **not** the verdict panel. Its
question is "is this strategy any good"; a live-rails verdict beside a synthetic
backtest invites reading the two as one answer. Its existing robustness note
stays as it is.

## Testing

Branch and boundary tests for the verdict, plus three that guard the reasoning
rather than the code:

* **The advisory path writes no risk decisions.** `risk_decisions.csv` is
  byte-identical after asking a question. This is the constraint that shaped the
  design, and it must fail loudly if someone later "improves" the verdict by
  asking the sizer.
* **Parity.** Both screens' contexts carry the same per-symbol material for the
  same symbol at the same moment — the M126 test shape, which is what stops them
  drifting apart again.
* **Unknown is not a pass.** Regime eligibility before any `RegimeEvent` renders
  as not-yet-known in the panel AND in the prompt text, never as a pass or fail.

Plus: the held branch reports sell rails and the unheld branch reports entry
rails, and neither reports the other's; `entry_permitted` has one implementation
with `submit_order` and the verdict both calling it; and the existing
`tests/safety/test_prompt_injection_in_context_is_ignored.py` still passes with
the two new fields present.

Every test that builds an OMS passes its own `data_dir`, per the standing
constraint.

## Deliberately not in scope

* **Sizing, and anything that would call the risk engine.** See above.
* **The verdict panel on the Workbench.**
* **The macro read.** See the correction above: it is not a cheap attribute
  read, and wiring it here would put a vendor fetch on every question. Its
  fields stay empty and the prompt states them as absent.
* **Any change to what the strategy engine, autonomy gate or OMS DECIDE.** This
  reads the rails; it does not alter one. The only production change outside the
  advisory path is extracting `entry_permitted`, which moves two membership
  tests without changing their meaning.
* **Acting on the recommendation.** The Advisor touches no OMS and no broker,
  and this does not change that.
* **Strategy selection on the Advisor.** The verdict is computed against the
  DEPLOYED strategies (`QAT_DEPLOYED_STRATEGIES`, currently `swing` alone), not
  against a new picker — one `StrategyRules` entry each, so the panel grows a
  row rather than needing a control. Deployed rather than *available*, because
  the question is what the rules governing this account say, and `swing` is
  both the deployed and the autonomous list today.
* **The per-order notional cap and the sizer.** Both are size questions, and
  size is exactly what the probe cannot ask. Stated here rather than left to be
  discovered from the absence of a row.
