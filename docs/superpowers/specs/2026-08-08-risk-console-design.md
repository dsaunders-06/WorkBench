# Risk Console — "why was I refused", 8 August 2026

Step 4.7 of `docs/UI_UX_APPROACH.md`.

## Part A — the screen does not answer its own question

The console shows four VaR/ES tiles, a correlation matrix, the kill-switch and,
since M60, quarantined positions. It shows **nothing about refusals.**

That matters more than it did this morning, because **M64 made the Regime
Monitor point here**: when the regime permits a strategy and nothing still
trades, that screen now says *"the reason is a risk rail — see the Risk
Console."* A forward reference to a screen that cannot answer is the M58a
pattern — a promise the application does not keep.

Everything needed already exists and already feeds the daily report:
`load_risk_decisions` and `summarise_refusals` in
`domain/evaluation/refusals.py`, which classify a refusal by **what it means**
rather than by its text — capacity against candidate quality. The console reuses
them, so the screen and the report cannot disagree about the same night.

The figures those functions produce on the real record: 1,418 candidates
considered, 42 approved, 1,107 refused for capacity (1,001 position limit,
106 aggregate risk cap) and 269 for cost-to-risk.

## Part B — the correlation table measures the wrong quantity

Two problems, and the second is the substantive one.

**It does not mark what binds.** Cells are coloured by magnitude on a red/blue
gradient that conveys nothing about the 0.70 cluster threshold. §4.7 asks for
the binding pairs to be identified rather than left for the operator to find.

**It is not measuring the rail's number.** `RiskConsoleScreen` correlates
`_price_history` — up to `_CORRELATION_WINDOW = 60` **intraday tick samples**,
which at a 60-second poll is about the last hour. `PortfolioGovernor` correlates
**60 daily bars**, roughly three months, a window M58b set deliberately after
finding that a 300-bar window hid a genuinely correlated pair.

So the table an operator reads to understand the correlation limit is not
showing the correlation that enforces it. M58b measured AMAT/AMD at **0.79** on
the rail's basis against a 0.70 threshold — a binding pair in the live book that
this table cannot display, because it is looking at a different quantity.

Same class as everything else found on 8 August: a screen showing something
*adjacent to* the number that decides.

### The fix follows the rule that has held all day

**Ask the component that decides.** A new
`PortfolioGovernor.binding_pairs(returns)` returns held pairs at or above
`correlation_cluster_threshold`, using the same pairwise alignment and the same
minimum-overlap guard as `_correlated_holdings` — so one place decides what
"correlated" means. The console supplies `signal_bridge.bars.frame(symbol)`,
which is the identical series the rail receives.

This exposes what the rail already computes. It adds no behaviour, changes no
decision, and therefore sits inside the validation freeze.

## The level, and where the brief is overruled

§4.7's table says the Risk Console is *"not shown"* at Guided and lists
*"kill-switch control"* under Professional. **Both are overruled**, because
`ui_level.py` states:

> **Safety is not a level.** Warnings, the mode and execution banners, **refusal
> reasons** and the sign-off gate are identical at every level. Nothing here may
> be used to quieten a rail.

The kill-switch is the most safety-critical control in the application, and
refusal reasons are named explicitly. Following the brief literally would leave
a Guided operator unable to reach the halt control, and would gate the very
content the doctrine protects. This is the third time the brief has been wrong
in detail — see M63 on the Balances premise and M64 on the macro panel — and it
is recorded rather than silently worked around.

**The screen and the kill-switch are identical at every level. Only the DEPTH of
the answer varies.**

| | Guided | Standard | Professional |
|---|---|---|---|
| Kill-switch | shown | shown | shown |
| Quarantined positions | shown | shown | shown |
| Why nothing traded | one plain sentence | families and counts | families, counts and the full audit log with inputs |
| Correlation | binding pairs only | binding pairs, matrix | binding pairs, full matrix |

`explains()` drives the plain sentence, `shows_advanced()` the families and the
matrix, `prefers_density()` the audit log. Three predicates, three distinct
screens — and **Guided and Standard must differ**, the defect the Balances
design reached review with.

## Ordering

**Part A lands first and independently.** It is the screen's namesake question,
it closes the forward reference M64 created, and it needs no domain change.
Part B follows.

## Error handling

`load_risk_decisions` reads `risk_decisions.csv`, whose `inputs` column is a
**Python repr, not JSON** — single quotes, `True`, `None`. It is parsed with
`ast.literal_eval` after trying JSON, and that behaviour is inherited rather
than reimplemented here.

A missing or unreadable file means "no refusals to report", not "no refusals
happened" — the two are worded differently on screen, for the same reason a
figure the broker did not report renders as a dash rather than a zero.

`binding_pairs` on a symbol with too little overlapping history returns nothing
for that pair rather than a correlation computed on three observations, matching
the rail: *"correlation on three shared observations is noise, and treating
noise as 'these move together' would trim real positions for no reason."*

## Testing

* The kill-switch is present and identical at all three levels — including
  Guided, which the brief would have hidden.
* A refusal reason is available at every level; only its detail varies.
* **Guided and Standard differ.**
* The console's refusal counts equal `summarise_refusals` over the same rows —
  reuse pinned, so a later "simplification" that counts rows on the screen
  fails.
* Binding pairs come from the governor: a stubbed governor returning a pair the
  raw numbers would not produce must still be what the screen displays.
* A pair below the threshold is not reported as binding.
* An unreadable `risk_decisions.csv` says "no data", not "no refusals".

## Position under the validation freeze

Presentation, plus one read-only accessor on the governor that exposes a
calculation it already performs. No trading decision, no sizing, no rail.
