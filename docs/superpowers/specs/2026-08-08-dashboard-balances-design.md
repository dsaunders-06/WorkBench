# Dashboard balances, level-aware — 8 August 2026

Step 4 of `docs/UI_UX_APPROACH.md`. Changes the Balances panel on the Dashboard
and nothing else.

## The brief's premise was wrong, and the real problem is different

`UI_UX_APPROACH.md` §4.1 says the Balances panel shows twelve fields *"most of
them dashes on an Alpaca paper account — margin, day trades, short market
value"*, and prescribes collapsing the unavailable ones.

Measured against the live account on 8 August:

| Cell | Live value |
|---|---|
| Portfolio value | $101,244.97 |
| Today's P/L | $545.58 |
| Cash | $44,772.43 |
| **Spendable here** | **$44,771.43** |
| **Broker buying power** | **$336,485.98** (4.0x multiplier) |
| Long market value | $56,472.54 |
| Short market value | $0.00 |
| Initial margin | $28,599.70 |
| Maintenance margin | $16,941.76 |
| Account | ACTIVE |
| Day trades (5d) | **—** |

**Ten of eleven cells carry a figure.** Only the day-trade count is a dash.
Margin is reported and substantial; short market value is a real zero rather
than a blank. So the prescribed fix — collapse the unavailable fields — would
collapse exactly one cell and address nothing.

**The actual problem is inapplicable data at equal weight, not unavailable
data.** Margin and buying power are real, prominent, and describe broker
capabilities this application structurally refuses to use: a buy's notional can
never exceed available cash, and that is not configurable. Short market value is
permanently zero because the system is long-only.

The sharpest instance is already named in the panel's own docstring —

> Seeing $365,162 of buying power next to an order rejected for insufficient
> cash is the single most confusing thing about running the two side by side.

— and today that gap ($336,486 against $44,771, a factor of 7.5) is explained
only by a tooltip, while both figures sit in the same grid at the same size.

## Scope

**Untouched:** mode and execution banners, the adopted-positions panel, session
state and the countdown to the open. All safety surface, and all named
do-not-touch in the brief.

**Not added:** "positions held", listed in the brief's Guided tier. It lives
elsewhere on the Dashboard; adding it here widens the job for no gain.

**Changed:** `BalancesPanel` only, plus one predicate on `UiLevel`.

## Two groups instead of one flat grid

**Primary — what this system acts on**

Portfolio value · Today's P/L · Cash · Spendable here · Long market value ·
Account status

**Demoted — "At the broker — not used by this system"**

Broker buying power · Initial margin · Maintenance margin · Short market value ·
Day trades (5d)

Short market value is demoted because it is structurally always zero on a
long-only system, not because it is missing. Day trades sits there because it is
a regulatory concept this application never acts on — and it is the one genuine
dash.

**Account status stays primary at every level.** `BLOCKED` is the only cell here
that is genuinely safety-relevant, and it is never level-gated.

The grouping itself is identical at every level. The heading is what makes the
buying-power gap explicable rather than merely visible: it states *why* the two
figures differ, where today only a tooltip does.

## The three levels

The first draft of this design produced two outcomes from three settings —
`explains()` is true for both Guided and Standard, so those two rendered
identically. That is the M58a failure in miniature: an operator picks Guided
over Standard and nothing changes. Caught in review, before implementation.

| | Guided | Standard | Professional |
|---|---|---|---|
| Primary figures | shown | shown | shown |
| Captions beneath them | **on** | **on** | **off** |
| "At the broker" group | **absent** | **present, collapsed** | **present, expanded** |

Mapping onto predicates:

```
Guided        explains()=True   shows_advanced()=False   captions, group absent
Standard      explains()=True   shows_advanced()=True    captions, group folded
                                prefers_density()=False
Professional  explains()=False  shows_advanced()=True    no captions, group open
                                prefers_density()=True
```

This matches `ui_level.py`'s own descriptions exactly — Guided is *"fewer
figures, each explained"*, Standard is *"everything present, with
explanations"*, Professional is *"maximum density, explanations off"*.

Two things the table leaves implicit, stated so they cannot be read either way:

* **At Guided the group's heading goes too**, not just its cells. A heading
  reading "At the broker — not used by this system" above nothing would be
  worse than its absence.
* **At Standard and Professional the operator can toggle it either way.** The
  level sets the *starting* state only; it never locks the control. That is the
  difference between folding detail away and hiding it, and it is what makes
  "collapsed" acceptable where "removed" would not be.

**`shows_advanced()` gains its first consumer.** It has been called by zero
screens since M45, which is the complaint recorded in the handoff, and it fits
this distinction without anything being invented for it.

### On hiding figures at Guided

M58c established that safety is not a level and that a professional operator
gets a denser screen, never a lower level a quieter one. That rule governs
**safety** content — warnings, banners, refusal reasons — and balance figures
are not that. `ui_level.py`'s own doctrine settles the rest:

> **Hidden, never disabled.** A greyed-out control invites a fight with the
> interface and tells the operator nothing. A control that is absent is one
> level away, and the level selector says so.

Absence at a lower level is sanctioned, because the level selector is the route
back.

### What covers the gap at Guided

Hiding the demoted group at Guided removes the buying-power figure — the very
thing an operator most needs reconciled against Alpaca's own web page. That is
covered by the caption rather than the cell: at Guided, the line beneath
**Spendable here** states that the broker will offer several times more and that
this system will not use it. The explanation does the work at Guided; the
figures do it at Professional; Standard has both.

## One addition to `ui_level.py`

```python
def prefers_density(self) -> bool:
    """Whether detail should be open rather than folded away."""
    return self >= UiLevel.PROFESSIONAL
```

The third genuine question a screen asks, parallel to the two that exist.
`shows_advanced()` cannot serve — it is true at Standard, and Standard wants the
group folded rather than open.

## Captions

One line per primary figure, present only when `explains()`. Following M58c, the
text is **set on the widget regardless of level and merely hidden**, so anything
reading the panel programmatically still sees the whole story.

| Cell | Caption |
|---|---|
| Portfolio value | Everything the account is worth: cash plus what the positions are currently worth. |
| Today's P/L | Change since the previous close, as the broker reports it. |
| Cash | Settled cash at the broker, not yet committed to a position. |
| Spendable here | What a buy may actually use. The broker will offer several times this on margin; this system never uses margin. |
| Long market value | What the held positions are currently worth. |
| Account | The broker's own status for the account. Anything but ACTIVE stops trading. |

## Error handling

Unchanged. `money()`, `count()` and `flag()` already render an unreported figure
as a dash rather than a zero, and that distinction is load-bearing — "0 day
trades" is a different claim from "not reported". The staleness line and its
colour are unchanged, and remain visible at every level: a stale figure is a
safety concern, not a detail.

## Testing

Following the `tests/presentation/` convention — `qtbot`, `Runtime.build_demo`,
handlers invoked directly.

**The three levels are distinguishable.** One test per level asserting the
combination above, and explicitly that **Guided and Standard differ** — the
defect this design already had once.

**Safety invariants:**

* Account `BLOCKED` renders identically at all three levels.
* The staleness line is present at all three levels.
* Caption text is populated even when hidden.

**Regression:**

* Every existing balances test passes unchanged. The figures and their
  formatting do not change, only their arrangement — a cell that showed
  `$28,599.70` still shows exactly that, in a different group.
* A cell the broker did not report still renders as a dash, not a zero.

## Position under the validation freeze

Presentation only. No trading decision, no sizing, no rail. The freeze's
*"recording MORE about decisions already being made"* allowance covers reporting
and interface work explicitly, and nothing here reads or writes an order path.
