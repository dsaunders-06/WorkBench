# Regime Monitor, level-aware — 8 August 2026

Step 4.6 of `docs/UI_UX_APPROACH.md`.

## The screen shows the inputs and not the consequence

It renders `Regime: bull (exposure scalar=1.00)` and seven probability bars —
the label and the distribution. It does not show **which strategies that
permits**, and that is the fact which governs whether anything trades.

**Eligibility is not the label.** Since M27b it is probability *mass*:
`StrategyEngine.is_eligible()` sums the distribution across a strategy's
suitable regimes and compares it to `regime_eligibility_mass` (0.5). Its own
docstring says why — *"the label is one draw from a distribution the model
already computed; collapsing to it and then testing set membership discards the
confidence and turns a near-tie into a certainty."*

So an operator reading `Regime: bull` off this screen and inferring that swing is
trading can be wrong in either direction. The handoff states the cost plainly:

> a strategy silently ineligible for a whole session looks exactly like a
> strategy that found no setup

There is direct precedent for this exact error. **M57c had to fix a regime log
line that "described a mechanism replaced in M27b."** The screen carries the same
defect the log carried, and nothing has corrected it.

Measured on the live configuration: one strategy is deployed (`swing`), suitable
in `recovery`, `bull`, `sideways`, `low_vol`.

## Scope

**Untouched — the transition history.** The brief is explicit: a regime change
can switch a strategy off for a session, and that record is how it gets
reconstructed afterwards. Present at every level.

**Untouched — the screen applies nothing.** It reaches no `RiskEngine` and no
`OMS`, and the module docstring says so. That property survives this change and
is asserted by a test.

**Changed:** the headline area gains an interpretation block, and the existing
panels become level-aware.

## Three facts, each from the component that owns it

### a. The scalar, in plain terms

`event.exposure_scalar` already renders as `0.40`. What it means does not:
*"positions sized at 40% of normal."*

### b. Eligibility per deployed strategy

```
swing: PERMITTED — 0.62 of the distribution sits in
recovery / bull / sideways / low_vol (threshold 0.50)
```

Read from `runtime.strategy_engine.is_eligible(strategy)` — **not recomputed
here.** This is the rule `test_the_reported_figure_is_the_one_that_blocks`
already pins for the adopted panel: reuse, not reimplementation. A screen that
derived the mass from `probs` itself could drift from the rail, and the operator
would be reading an explanation of a decision that was made on different
numbers.

The mass figure comes from the same source. Where `StrategyEngine` exposes no
public accessor for it, one is added there rather than the arithmetic being
duplicated on the screen.

### c. When the regime is not the binding constraint

One line, naming the Risk Console. "Why did nothing happen tonight" usually has a
non-regime answer — the ten-position limit or the 5% risk cap — and §4.7 gives
that question to the Risk Console. This screen answers what the regime does, and
points onward rather than deriving a second refusal picture that could disagree
with the first.

## The three levels

| | Guided | Standard | Professional |
|---|---|---|---|
| Label, probability bars, transition history | shown | shown | shown |
| **Eligibility per strategy** | **shown** | **shown** | **shown** |
| Plain-English scalar sentence | shown | shown | hidden |
| The mass arithmetic (0.62 against 0.50) | hidden | shown | shown |
| Macro panel | hidden | shown | shown |
| Feature-driver table | hidden | hidden | shown |

`explains()` drives the sentence, `shows_advanced()` the mass and the macro
panel, `prefers_density()` the driver table. All three predicates, three
distinct screens.

**Eligibility is not level-gated.** A strategy silently ineligible for a session
is indistinguishable from one that found no setup — that was a defect, not a
detail, and by the M58c rule it stays visible at every level. The exposure
scalar's *number* likewise remains at every level; only the sentence explaining
it moves.

### Departure from the brief, deliberate

The brief places the macro block at Professional only. **Standard is the default
level**, so that would strip an existing feature from the default experience for
no gain. The driver table alone gives Professional its distinction. Recorded
because it is a decision rather than an oversight.

## Error handling

Unchanged. The macro panel is already two-part by design — the deterministic read
computed in code, and the AI synthesis on top, which may fail without taking the
deterministic half down with it. Nothing here alters that.

Before the first `RegimeEvent` the screen reads "waiting for data"; the
interpretation block shows the same, rather than an eligibility answer computed
from an empty distribution. `is_eligible()` already handles that case — with no
distribution it falls back to membership of the default label — but the screen
must not present a fallback as a measurement.

## Testing

Following the `tests/presentation/` convention: `qtbot`, `Runtime.build_demo`,
handlers invoked directly.

**Three levels, three outcomes**, with `Guided != Standard` asserted explicitly.
That defect reached review once already on the Balances panel.

**Reuse, not reimplementation.** A stubbed strategy engine returning `False` must
make the screen read `NOT PERMITTED`, whatever the probabilities say. This is the
test that would fail if someone later "simplified" the screen by computing mass
from `probs`.

**Safety invariants:**

* Eligibility renders at all three levels.
* The transition history is present at all three levels.
* The screen touches no order path — no `RiskEngine`, no `OMS`.

**Before any regime arrives**, the screen states that it is waiting rather than
showing an eligibility verdict.

## Position under the validation freeze

Presentation only. No trading decision, no sizing, no rail. The screen reads
`is_eligible()` and displays the answer; it does not compute, alter, or apply it.
