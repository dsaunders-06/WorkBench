# UI/UX approach plan

**Drafted 4 August 2026, against build M38.**

Goal, in the operator's words: a classic and simple feel, an adjustable
experience that accommodates the user's expertise, room for customisation, and
commercial quality usable by anyone from novice to institutional trader.

This is the plan, not the work. Nothing here changes a trading decision, so it
clears the validation-phase freeze on the letter of it — but see §7 on timing,
because the operator is the measuring instrument during the trial.

---

## 1. What is actually wrong

Measured, not felt:

| | |
|---|---|
| `setStyleSheet` calls | 67, across 13 files |
| Central stylesheet or palette | none |
| Distinct hex colours | 13, expressing about 4 semantic roles |
| Reds meaning "danger" | 5 (`#b71c1c`, `#d9534f`, `#7f1d1d`, `#b91c1c`, `#b3261e`) |
| Greens meaning "good" | 2 (`#1b5e20`, `#5cb85c`) |
| Distinct font sizes | 8, from 11px to 18px, with no ratio between them |
| Largest screen | Settings, 1,001 lines, 2,818px of content |

The application is not badly designed. It is **undesigned**: every screen was
styled locally, each choice defensible on its own, and no two screens agree.
That is what reads as clunky, and it is why styling individual screens first
would make it worse rather than better.

---

## 2. What must not be touched

These are load-bearing. A visual refresh that flattens them makes the product
worse in ways that are hard to see and expensive to discover.

**The mode and execution banners.** `MODE: PAPER` and `EXECUTION: AUTO-TRADE
ACTIVE` are the two facts that change what every other number on screen means.
They are deliberately loud. They stay loud at every expertise level.

**The habit of explaining consequences rather than controls.** The
adopted-positions panel does not say "6 positions adopted"; it says what that
costs in risk budget and how to clear it. The de-lever checkbox does not say
"enable sweep"; it says this is the only rail that sells uninvited. The risk
limits carry a note on why the default is the default. This is the single best
thing about the current interface and it is exactly what a reskin destroys by
accident. It should become a written rule of the design system.

**Sign-off affordances in the Order Blotter.** Nothing reaches the broker
without an explicit, operator-attributed action. Sign-off and reject must stay
visually distinct, deliberate, and impossible to hit by accident. No amount of
"cleaner" is worth eroding that.

**Restart-required messaging in Settings.** Every field there takes effect on
the next launch. If that becomes less obvious, an operator will change a risk
limit and believe it is live.

**Write-only secret fields.** The Alpaca and Anthropic key inputs never
pre-fill and clear themselves after saving. That is correct and must survive.

**Refusal reasons.** Every rejected order carries a reason, and every risk
decision is journalled with its inputs. Reasons may be *rephrased* for
readability; they may not be shortened into a status code.

---

## 3. The expertise model

Three levels. The mistake to avoid is treating this as "hide things from
beginners" — the levels differ in **what is explained** and **what is
foregrounded**, not only in what is present.

| Level | Who | Principle |
|---|---|---|
| **Guided** | New to systematic trading | Every number carries what it means. Destructive and advanced controls are hidden, not disabled. Plain language over jargon. |
| **Standard** | Default. Comfortable with trading, new to this system | Everything present, explanations available on demand rather than always visible. |
| **Professional** | Institutional or long-time user | Maximum density. Explanations off. Keyboard-first. Raw figures beside derived ones. |

Two rules that keep this honest:

* **Safety is not a level.** Warnings, the mode banners, refusal reasons and
  sign-off behave identically at all three. A Professional user does not get a
  quieter kill-switch.
* **Hidden, never disabled.** A greyed-out control invites a fight with the
  interface. A control that is not there yet is a level away, and the level
  selector says so.

Customisation sits on top: the level sets sensible defaults, and any individual
panel can be shown or hidden per user. Level is a starting point, not a cage.

---

## 4. Page by page

### 4.1 Dashboard — "is it working, and what do I hold"

The most-viewed screen and the first thing seen at the open.

*Do not touch:* mode/execution banners, the adopted-positions panel and its
explanatory body, session state and the countdown to the open.

*Enhance:* the Balances panel shows twelve fields in a flat grid, most of them
dashes on an Alpaca paper account — margin, day trades, short market value.
Presenting unavailable data with the same weight as portfolio value is the
clearest single example of the undesigned problem.

| Guided | Standard | Professional |
|---|---|---|
| Four figures: portfolio value, today's P&L, cash, positions held. Each with one line on what it means. Regime shown as plain language ("cautious - positions sized at 40%") | Full balances, unavailable fields collapsed. Regime label plus scalar | Full balances including margin and day-trade count. Regime label, scalar and top three probabilities inline |

### 4.2 Order Blotter — the sign-off gate

The most safety-critical screen in the application.

*Do not touch:* sign-off and reject as distinct, deliberate actions; the order
detail that supports the decision; the reason text on a rejection.

*Enhance:* rejection reasons are written for an engineer reading a log. "sized
at 0.4 shares, below one whole share" is precise and opaque to a novice. Same
fact, layered: plain sentence first, exact figures beneath.

| Guided | Standard | Professional |
|---|---|---|
| One order at a time, plain-language reason, explicit confirm | Table with reason column, bulk sign-off | Dense table, keyboard sign-off, full risk inputs inline |

### 4.3 Settings — the worst offender, the biggest payoff

1,001 lines, nine groups, 2,818px. It scrolls now (M36b) but it is a wall.

*Do not touch:* risk-limit warnings, the percentage/fraction conversion, the
de-lever red callout, restart-required messaging, write-only key fields, the
spin-box bounds that mirror the validators.

*Enhance:* this is where the expertise model earns its keep. A novice should
not be choosing a Kelly fraction or a correlation threshold.

| Guided | Standard | Professional |
|---|---|---|
| Broker connection, market, watchlist. Risk shown **read-only** with plain descriptions | The above plus risk limits editable, advanced tuning collapsed | Everything, plus raw setting names for cross-reference with the config file |

Risk limits being *visible but read-only* at Guided matters: an operator should
always be able to see what is governing their account, even before they are
ready to change it.

#### 4.3a Two behaviours Settings is missing (added 5 August)

Requested by the operator, and both belong to this screen's rework rather than
to a separate milestone. Neither changes a trading decision; both change how
easy it is to make one by accident.

**Restore defaults.** There is no way back. An operator who has edited a Kelly
bound or a correlation threshold to see what it does has no way to return to the
shipped values except by knowing what they were, and the shipped values are only
visible in `config.py`. That is the opposite of the "always be able to see what
is governing their account" rule above.

Requirements, in the spirit of the rest of the screen:

* Confirm before acting, and say what will change — a count and the field names,
  not "are you sure".
* Scope it. Restoring *every* field would clear the broker connection, the
  watchlist and the deployed-strategy list, which are the operator's
  configuration rather than tuning. Defaults belong to the tuning groups.
* Do not write silently. It is a bulk edit to fields that govern the account, so
  it should leave the same restart-required message any other edit does, and the
  same audit trail if one exists.
* It restores the field VALUES, not the file. Nothing is saved until Save is
  pressed, so a restore can itself be abandoned by closing without saving.

**Unsaved-changes prompt on exit.** Every field on this screen is
restart-required, which means an unsaved edit is invisible twice over: it did
not take effect, and there is nothing on screen that says so. An operator can
change a risk limit, close the window, restart, and reasonably believe the new
limit is live.

Requirements:

* Scope is **Market & Watchlist downwards** — the operator's stated boundary.
  Above it sits the broker/API section, whose write-only secret fields must
  never be diffed or echoed back (§2), so they are excluded by construction as
  well as by request.
* Compare against the values as loaded, not against defaults, so re-typing the
  same value is not treated as a change.
* Three answers, not two: Save, Discard, Cancel. A two-button prompt forces a
  decision the operator may not be ready to make and is how unsaved work gets
  thrown away.
* Name what changed. Consistent with the habit of explaining consequences:
  "3 unsaved changes: max position size, ATR multiple, correlation limit."
* The prompt must not fire on a screen the operator only scrolled through. A
  spin box that emits a change signal on focus alone would make this an
  irritation that gets clicked past reflexively, which is worse than not having
  it.

Both are Guided-first features: the expert knows they did not press Save, and
the novice is the one who loses an afternoon to it.

### 4.4 Performance — did any of this work

*Do not touch:* promotion status colour coding, the "gate advises" note, the
gross/costs/net separation, the metrics tab's "what it tells you" column — that
column is the explanatory habit done right and should be the template elsewhere.

*Enhance:* four tabs of similar visual weight, with no indication which to read
first. The promotion table is the answer to the only question that matters and
should lead unambiguously.

| Guided | Standard | Professional |
|---|---|---|
| One verdict per strategy in words, plus what is blocking it | Promotion table, metrics, closed trades | The above plus the M37 diagnostics — regime at entry, exit reason, MAE/MFE, slippage — as sortable columns |

The M37 diagnostic columns are for analysis, not monitoring. Professional only.

### 4.5 Strategy Workbench — research, not operation

*Do not touch:* the deploy gate.

*Enhance:* the walk-forward panel does not state its known limitation — that
slicing manufactures an entry at each window boundary, so for a
continuously-held strategy it measures 60-day chunks of a hold. A results panel
that omits its own caveat invites over-reading.

| Guided | Standard | Professional |
|---|---|---|
| Not shown. Backtesting a strategy is not a beginner task | Backtest, equity curve, Monte Carlo cone, plain-language summary | The above plus walk-forward windows, per-window statistics and the deploy control |

### 4.6 Regime Monitor — why the system is behaving as it is

*Do not touch:* the transition history — a regime change can switch a strategy
off for a session, and that record is how it gets reconstructed afterwards.

*Enhance:* seven regime names and a probability vector with no interpretation.
Guided needs "what does this mean for my trades".

| Guided | Standard | Professional |
|---|---|---|
| One sentence: current regime, what it does to position sizes, which strategies it permits | Label, probabilities, exposure scalar, transitions | The above plus the six feature drivers and the macro block |

### 4.7 Risk Console — why was I refused

*Do not touch:* the audit log's completeness.

*Enhance:* the correlation table is a raw N×N matrix. Since M33 correlation is
also an enforced limit, so the table should show which pairs are actually
binding rather than leaving the operator to find them.

| Guided | Standard | Professional |
|---|---|---|
| Not shown. Refusals surface in the Blotter where the order is | Recent refusals with reasons, correlation clusters that are binding | Full audit log with inputs, full correlation matrix, kill-switch control |

### 4.8 Screener — finding candidates

*Enhance:* the filters are raw factor inputs — minimum EPS growth, maximum PEG,
minimum dividend yield. Meaningless without knowing what a PEG of 1.5 implies.

| Guided | Standard | Professional |
|---|---|---|
| Named presets: "steady dividend payers", "high growth" | Presets plus individual filters with ranges | Raw filters, saved custom screens |

### 4.9 AI Advisor — the simplest screen, and fine

117 lines. Ask a question, get an answer.

*Do not touch:* the advisory-only framing. The user must never be led to think
the AI can act.

*Enhance:* little. Once M40 lands, fundamentals appear in the context and the
answers get better without the screen changing.

---

## 5. Recommended order

**1. Extract the design system.** No visual change intended. Thirteen colours
become about five semantic roles; eight font sizes become a scale; 67 inline
stylesheets become one central sheet. Everything downstream depends on this and
it is invisible to the operator, which makes it the safest possible first step.

**2. Build the expertise-level mechanism.** A setting, a way for any panel to
ask the current level, and a level selector. No screen changes yet — this is
plumbing.

**3. Settings.** Worst clunk, highest payoff, and it is configuration rather
than trading, so the blast radius is smallest. Also the best place to prove the
level model works before betting more screens on it.

**4. Dashboard.** Most-viewed, and the balances grid is the clearest example of
the problem.

**5. Performance.** Where the trial's answer will eventually be read. Worth
being good before there is something to read.

**6. Order Blotter.** Deliberately late. It is the most safety-critical screen,
and it should be touched when the system is stable and the design system is
proven, not while either is in flux.

**7. The research screens** — Workbench, Regime Monitor, Risk Console, Screener.
Lower traffic, mostly Professional, least urgent.

**8. AI Advisor.** Already simple. Leave it alone until the rest sets the
pattern.

---

## 6. Which skill, and its limits

**`ui-ux-pro-max:design-system` for step 1.** Its remit is exactly the problem:
type scale, colour system, spacing, component consistency. Steps 3 onward are
applications of whatever it produces.

**`frontend-design` for aesthetic direction** — the "classic and simple" brief,
and avoiding a templated default look.

**Not `ui-ux-pro-max:ui-styling`.** That is web execution, and the execution
here is not web.

**The limit, stated plainly.** These skills assume CSS. This application is
PySide6/Qt, styled through QSS, `QPalette` and layout managers. QSS is a
restricted subset — no flexbox, no grid, limited pseudo-states, no custom
properties. The design *thinking* transfers: hierarchy, scale, spacing rhythm,
colour semantics, progressive disclosure. The *implementation* does not. Expect
direction from the skills and translation into Qt idiom, not literal
application.

---

## 7. Timing against the trial

Nothing here changes a trading decision, so the freeze permits it. But the
operator is the measuring instrument during the validation phase, and last
night demonstrated how much depends on noticing one line in a log.

Recommended: do steps 1 and 2 now — both are invisible to the running system.
Hold the screen work until the first meaningful batch of closed trades has been
read, so that the interface being read does not change underneath the reading.
