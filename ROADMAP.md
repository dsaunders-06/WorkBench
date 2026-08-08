# Development stack after M27

## Standing rule during the validation phase

**From 3 August 2026, nothing lands that changes a trading decision.**

Development is finished. M27a through M37 built the machinery; the question
now is empirical, not architectural - does swing possess an edge that survives
costs. Every change to decision logic during the trial makes the result harder
to interpret, because a result then belongs to no single version of the system.

Two independent reviews on 1 August reached the same conclusion independently
and it is adopted here.

### Frozen - do not change

Strategy parameters, moving-average lengths, ATR multiple, every risk cap,
Kelly bounds, regime thresholds and fusion weights, correlation limits, churn
rails, promotion thresholds, cost model.

The test: *would this change which trades happen, or how large they are?* If
yes, it waits for the trial to end - however obviously right it looks.

### Fix immediately - anything that stops evidence existing

* the feed dying, or symbols silently dropped
* the app crashing, hanging, or failing to survive a session
* orders rejected by a bug rather than by a rule
* the kill-switch tripping on something that is not a real discrepancy
* protective orders not resting, or not being repaired
* `trades.csv`, `decision_journal.csv` or `risk_decisions.csv` not being written
* the daily or weekly report failing

A defect that corrupts the record is worse than one that stops the session,
because a stopped session is obvious and a corrupted record is not.

### Allowed without ending the freeze

Recording MORE about decisions already being made. M37 is the model: it added
regime-at-entry, exit reason, excursion and slippage to every closed trade and
changed no decision anywhere. Reporting, logging and analysis are not the
trading logic.

## Where this is ultimately going — stated 6 August

**The long-term intent is to trade the ASX only.** US equities on Alpaca paper
are the vehicle for the validation phase, not the destination.

Recorded because it changes how several things should be judged, and because a
reader finding a US-only broker in an ASX-bound system should know it was a
staging decision rather than an oversight:

* **Alpaca cannot reach the ASX at all.** It is US equities only, and the app
  already warns when market and broker disagree. Reaching the destination means
  a different adapter - `ibkr` exists in the broker list and is unimplemented
  beyond the seam.
* **The trial's evidence may not transfer.** The promotion gate is accumulating
  30 closed trades on US megacaps, through Alpaca paper, on US session hours,
  with a US commission model. An ASX system shares none of those. What the
  trial genuinely validates is the MACHINERY - that protection rests, fills are
  absorbed, trades are recorded, rails bind - which is market-agnostic. The
  EDGE numbers are not, and should not be carried across without being
  re-earned.
* **An ASX/Alpaca mismatch is therefore not a hazard to guard against.** It was
  considered as a refuse-to-start after the 6 August incident and deliberately
  declined: the mismatch is the direction of travel, and a guard would fight it.

## The conservative baseline — decided 6 August

**The configuration is frozen as it stands, and runs for two weeks. Review
around 20 August.**

Taken deliberately, with the alternative costed. Overnight on 5–6 August the
book refused 503 orders: **479 for the 10-position limit and 24 for the 5%
aggregate risk cap.** The two rails are co-binding by construction — measured
per-position risk averages 0.49% of equity, so ten positions fill a 5% budget
almost exactly, and raising either one alone changes nothing.

Widening was considered and declined. The case for it was that the freeze's cost
is proportional to evidence already collected, and that stood at one closed
trade — so 6 August was the cheapest moment the change would ever have. The case
against, which won: the build had been stable for hours rather than weeks, and a
baseline nobody has observed is not a baseline. Widening remains available at
the review, and will cost only the trades banked by then.

Recorded because it is a decision, not a derivation: a later reader finding a
10-position limit and a nearly-idle book should know it was chosen and left
alone, not overlooked.

**What this baseline is expected to produce.** Roughly ten closed trades a month
at the observed turnover, dominated by stops and time stops rather than by the
strategy's own exit signal — 29 entries produced zero signal exits over 1.19
years. Two weeks is therefore a test of whether the machinery holds, not of
whether the edge exists.

## Operating cadence

Sessions run overnight AEST. The US market opens 13:30 UTC, which is 23:30
AEST in August. Review the following morning.

### At the open - the first four minutes

1. `Trading session started - US is open` at 13:30 UTC, then ticks arriving
2. `REGIME ... -> <label> (exposure scalar ...)` within seconds of the bell.
   Absent means every strategy is gated on the sideways DEFAULT rather than on
   a measurement - the single most consequential thing that can silently go
   wrong.
3. Any `MARKET DATA DOWN` or repeated macro fetch failures
4. `N carries a stop resting at the broker` - N must equal the position count

### The morning review

1. Counts: signals generated, orders proposed, refused, filled
2. Any `BROKER-SIDE FILL absorbed` - a protective order fired, and that is a
   closed trade
3. Any `Broker reconciliation mismatch` or kill-switch trip. This halts the
   session until restarted and is the one failure that costs a whole night.
4. Any `POSITION UNPROTECTED` that was NOT followed by a repair within a sweep
   interval
5. Refusal reasons in the audit log - which rail is binding, and whether it
   should be
6. The daily report's Metrics block

Looking for *does the pipeline move and does the record hold*, not *did it
make money*. At these sample sizes P&L is noise.

### What the trial is collecting

The promotion gate needs 30 closed trades per strategy. At the observed rate -
swing takes roughly one closed trade per position per 30 trading days, and its
own exit signal effectively never fires - that is three to four months.

Every closed trade now records the regime it was opened in and that regime's
probability, the exposure scalar applied, how it ended, the holding period,
realised entry slippage against the price it was sized on, and maximum adverse
and favourable excursion in R. That is what makes the end of the trial able to
answer *why*, and none of it can be reconstructed afterwards.

### Questions for the end of the trial, not before

* Which exit type carries the expectancy - target, stop, time stop, signal?
* Does the regime distribution stay plausible, or is `high_vol` an artefact of
  one dominant feature?
* How often does each refusal gate fire, and do its refusals improve outcomes?
* Is realised slippage consistent with the cost model's assumption?
* Would trades closed by the time stop have done better held longer?
* Distribution of R multiples, not the average.

An external review suggested raising the live-trading bar from 30 closed
trades to 75-100. Worth deciding after the first 30, when the variance is
visible rather than assumed.

## How Alpaca actually represents orders - measured, not assumed

Three sessions in a row were disrupted by the same class of mistake: assuming
how the broker models something rather than asking it. This section records
what was measured against the live account on 4 August, so the next change does
not have to rediscover it.

**A protective leg is only returned when its PARENT order is returned.**

Queried against a book holding ten protected positions - six carrying
standalone OCOs, four carrying brackets attached to entries that had filled:

| Query | Rows | Symbols with a live sell-stop |
|---|---|---|
| `status=open, nested=false` | 11 | **0** - legs are not returned as top-level rows at all |
| `status=open, nested=true` | 11 | 6 - only those whose parent is still `new` |
| `status=all, nested=true` | 220 | **10** - the four missing ones all have `parent=filled` |

So:

* `nested=false` does not flatten legs into the result. It omits them.
* `status=open` excludes a filled parent, and takes its still-live `held` legs
  with it. A bracket's protection becomes invisible the moment the entry fills.
* Every live protective leg carries status `held`, whatever its parent's state.

**Consequences already paid.** M31d read `resting_stops` as authoritative and
proposed replacements for six protected positions. M33d taught it to read
`held` and nested legs, which fixed the OCO case and left the bracket case
untouched because no bracketed entry had filled yet. On 4 August four did, the
app declared them unprotected, and proposed four duplicate OCOs - which Alpaca
refused for insufficient shares, the broker catching what the app could not
see.

**The shape of the fix.** Ask for `status=all` with `nested=true` and filter
legs on their OWN status rather than trusting the query. The cost is real:
11 rows becomes 220, because it returns every order ever placed. Bounding that
is M47, and the answer turned out not to be a date - dates age, symbols do not.

Two further behaviours measured on 5 August, both of which contradict what the
parameter names suggest:

* **`limit` counts RAW orders, not the nested parents returned.** `limit=100`
  yielded 49 parents; `limit=50` yielded 23. A truncated page does not
  necessarily look short.
* **`after=` filters on `submitted_at`, not on fill time.** A protective leg
  submitted weeks ago and filling today is NOT returned by a query bounded on
  recent activity. `recent_fills` is bounded exactly that way - see M48.

**The pattern worth naming.** M34 and M46 were the same mistake about
identifiers - assuming an id means the same thing on both sides of a boundary.
M31d, M33d and this are the same mistake about queries - assuming a filter
returns what its name suggests. The corporate-actions work (M39) is the same
shape again, and should start by measuring what the broker reports through a
split rather than by reasoning about it.

**That measurement was taken on 8 August - see M60.** The announcement side is
now known rather than assumed. What Alpaca does to a held QUANTITY and to a
resting OCO through a split is still unmeasured, and M39's adjustment waits on
it.

## M77 - The Blotter could not say why an order was refused

8 August. Step 4.2, the last screen in Group 4 and the most safety-critical.

**§4.2 protects a reason text the screen never displayed.** *"Do not touch: …
the reason text on a rejection"* and *"Enhance: rejection reasons are written for
an engineer reading a log"* both presume a reason is on this screen. It was not:
eleven columns and no reason field, `Order` carries no reason attribute, and
`OMS._record` writes it to the decision journal instead. So the Blotter listed
rejected orders - `_new_rejected_order` creates real ones - and **could not say
why any of them was rejected.** Sixth time §4.x has been wrong in detail, and
the same shape as M73: the brief guarding something that was never built.

**The plain-language layer already existed and this screen did not read it.**
`refusals.rail_of` turns §4.2's own example - *"sized at 0.4 shares, below one
whole share …"* - into *"Sized below one whole share"*, and has since M51. Its
consumers were the reporter and the Risk Console; never the screen where an
operator meets a refused order. **Sixth instance of the `shows_advanced()`
pattern.** Layered exactly as the brief asks: label in the cell, the rail's own
words with every figure on hover, so the layering hides nothing.

Guided also gets what the FAMILY means, because "Position limit" still assumes
you know the book has one - and `classify().means` is a sentence written for
that. It now reads *"Position limit - the book was full - says nothing about the
trade."*

**What the level may not touch.** M45 puts the sign-off gate and the mode banner
outside the level model, and tests assert both identical at all three levels,
including that declining the confirm dialog reaches `oms.sign_off` zero times.
Guided is allowed to be STRICTER - one order at a time, enforced in the
selection model so a batch cannot be formed at all - and nothing is allowed to
be looser.

**Keyboard sign-off, listed for Professional, was decided against.** §4.2's own
"do not touch" line protects sign-off and reject as *distinct, deliberate*
actions, and an accelerator on the transmit action makes it less deliberate on
the one screen where a mis-key reaches the broker. The confirm dialog would
still gate it, so the invariant would hold - but the upside is a second saved
and the downside is a transmission nobody meant. Recorded as decided rather than
skipped.

**Rendering found three things the suite passed through** - the fourth screen
running:

* At Guided a pending order read *"proposed by swing - not recognised - see the
  note below"*. `classify` returns UNCLASSIFIED for anything that is not a
  refusal, and that sentence belongs to the refusal REPORT where a note does
  follow. The refusal vocabulary now applies only to refusals.
* The Reason column was a 120px stub - *"Sized below on…"* - truncated hardest
  at Guided where the text is longest, while the table left a third of the
  window empty to its right.
* The `_rendered_signature` did not include the reason, so a row kept the dash
  it was first drawn with until something else about it changed.

**The journal is not re-read on every tick.** `entries()` re-parses the whole
CSV - 464KB live - and this screen refreshes every two seconds. Reasons are
cached by order id, which is safe because a reason is written once and never
changes, and misses are throttled.

Two of M75's 25 raw-hex sites are gone: the mode banner now uses
`theme.banner`, whose docstring names this exact use.

26 tests. The M58a collapse detector caught the change that added it: keying the
family sentence on `explains()` rendered Guided and Standard identically,
because `explains()` is true for both.

## M76 - Ticker dropdowns are alphabetical

8 August. Small, and a standing rule rather than a one-off: **every dropdown
listing tickers sorts alphabetically, on whichever screen it appears.**

`universe.resolve_watchlist` returns the universe's own order - roughly by market
capitalisation, and the demo watchlist opens `SPY, AAPL, MSFT, GOOGL`. That order
means something to the universe and nothing to somebody hunting for WFC in a list
of a hundred. Both symbol pickers used it.

**Sorted at the dropdown, never in `runtime.watchlist`.** The Risk Console builds
its correlation matrix by indexing that tuple positionally - `index_by_symbol`
enumerated against headers set from the same order - so sorting the watchlist
itself would move a rail's data rather than a control's labels. A test asserts
that building either screen leaves the tuple untouched.

Two screens carry one today (Workbench, AI Advisor). One test each rather than a
loop over a registry, so a screen added later that forgets is caught by the
absence of its own test rather than by a passing loop that never knew about it.

## M74 - The Workbench had no level, and no summary to give one

8 August. Step 4.5, the half M69 did not cover.

**It consumed no level at all** - absent from the `UiLevel` consumers entirely -
so every operator saw the walk-forward panel and the **deploy control**,
including the level §4.5 says should not see the screen. Deploy is the one
control here that changes what the account does, and it is now Professional
only. The deploy GATE is untouched, as the brief asks: the button's
`setEnabled` state says "this strategy is already live", which is state rather
than level, and a test pins it.

Guided is *"not shown. Backtesting a strategy is not a beginner task"*, and an
emptied screen is not that - M45's rule is that an absent control is one level
away **and the level selector says so**. The Risk Console met the identical
instruction at M67 by keeping its tab and hiding its contents, so the tab stays
and a notice takes the place of the tools. Following the precedent rather than
the literal wording, because `main_window` has no level awareness at all and
giving it some would change navigation for every screen at once.

**The plain-language summary §4.5 lists for Standard was never written.** What
Standard got was `result.metrics` as KPI tiles in **alphabetical order** - alpha,
beta, cagr, calmar, information_ratio - with nothing to say which of them decides
anything. Rendering it makes the point better than describing it does: `alpha`
leads twelve tiles.

It leads with the trade count, for the reason M69 gave the cone and the windows
their caveats - **and the caveat existed on both tools derived from the backtest
and not on the backtest itself.** The demo backtest produces exactly one trade,
so it fires on the first render rather than in theory.

**Rendering found two things the suite passed through**, which is now the third
time running. "Grew -0.0% a year" and "gave up 0.0% a year" - a template reading
as broken rather than as a small number, and a direction asserted from a figure
that does not support one; both now say "was flat" and stay silent. And the
Guided notice floated vertically centred in an empty screen, because a QLabel
left alone in a layout stretches and centres its text.

19 tests. Verified by keying walk-forward and deploy on `shows_advanced()` - the
M58a mistake - and confirming three tests fail, the deploy one among them.

## M75 - The design system was declared done and is half-done

8 August, found while doing M74 and deliberately not finished.

§5 step 1 - *"67 inline stylesheets become one central sheet"* - is recorded as
done. **25 raw-hex colour sites survive across seven of the eight presentation
files**, and they are `theme.py`'s own primitives written out longhand:

| Literal | What it already is |
|---|---|
| `#b71c1c` | `DANGER` |
| `#1b5e20` | `SUCCESS` |
| `#b45309` | `WARNING` |
| `#7f1d1d` | `DANGER_STRONG` |
| `#1e3a5f` | `ACCENT` |

`settings.py` lines 672 and 721 hand-write the exact string
`theme.callout("warning")` returns, character for character.

**That explains M73's puzzle.** `theme.callout` had zero consumers not because
nothing needed it, but because the call sites that need it still contain the
literal it was extracted from. The module was created and eleven files import
it; the old values were never removed from most of them. A restyle would
therefore change some screens and not others, which is worse than not having
extracted it.

Left for its own pass because finishing it means editing the **Order Blotter**,
which §5 sequences deliberately last - most safety-critical, and to be touched
when the design system is proven. M74 migrated the one site in `workbench.py`
(`#d9534f`, which theme's own migration note claims to have consolidated).

Mechanical, and there is no rush: it changes a handful of sites by a shade and
nothing else. Do it when the Blotter's turn comes, in one pass, with the screens
rendered before and after.

## M73 - The AI Advisor's "do not touch" framing did not exist

8 August. Step 4.9, audited rather than accepted - the brief calls this "the
simplest screen, and fine", and it was wrong on both of its claims. That is the
FIFTH time §4.x has been wrong in detail.

**"Do not touch: the advisory-only framing. The user must never be led to think
the AI can act."** The framing lived in the module docstring - *"an analyst,
never a trader"* - which the operator never sees. On screen it printed
`[BUY, confidence=80%]` in bold and said nothing about what happened next. The
brief was protecting something that was never built.

It matters more here than it would in most applications, because **this one also
trades unattended** - `QAT_EXECUTION_MODE=auto` on the live install. A
recommendation displayed inside an application that places its own orders
invites exactly the inference §4.9 wants prevented, and nothing on screen
prevented it. The advisor genuinely never touches the OMS; that fact simply had
no representation in the interface.

Not level-aware, deliberately. M45: safety is not a level, and a Professional
operator is not less entitled to know which half of the application is speaking.

**"Enhance: little."** It fed the model a zero it never measured:

    "var_95": portfolio_check.get("var_95", 0.0)

so "no risk check has run this session" reached the model as "VaR is zero" - no
tail risk - and a language model cannot ask which was meant. **The same prompt,
eleven lines further down, promises the opposite in as many words:** *"fields the
vendor could not answer are omitted rather than zeroed"*. The Screener's em dash
and `available_figures()` state the same rule again. The one consumer that
cannot ask got the version the rest of the codebase refuses to produce.

Absent keys are now omitted, and `to_prompt_text` says "UNKNOWN, not zero risk"
rather than rendering an empty dict. Each answer also states what it was
reasoning without - synthetic fundamentals, or no risk figures - because
`to_prompt_text` already told the MODEL both and told the operator neither,
leaving the two working from different information about the same reply.

**`theme.callout` had zero consumers.** Extracted in the design-system step and
adopted by nothing, while its own docstring calls the pattern "the best thing
about this interface and the easiest to lose in a restyle". It was already most
of the way lost. M72's synthetic-fundamentals warning is its first caller.
Same shape as `shows_advanced()` sitting unread from M45 until M63, and the
fourth instance of that pattern this document records.

15 tests.

## M72 - The Screener never said whether its figures were real

8 August. Step 4.8 of `UI_UX_APPROACH.md`. The brief's premise held this time -
the filters really are raw factor inputs - but checking it against the code
found something the brief does not mention, and it is the larger of the two.

**`is_synthetic` has ridden on every `FundamentalSnapshot` since M18.** Its own
docstring says why: *"Carried on the snapshot rather than inferred from the
source's type, so anything downstream that displays or reasons about a number
can say where it came from."* `available_figures()` duly passes it to the LLM,
so **the AI Advisor has known the provenance of these figures all along and the
operator reading the table has not.** The Screener renders nine fundamental
columns and never asked.

Not hypothetical. `fundamentals_source` defaults to `"mock"`, and
`resolve_fundamentals_source` degrades to the same seeded source when the real
one cannot be built - logging that *"every fundamental figure shown or traded on
will be INVENTED"* and then rendering a table indistinguishable from a real one.
Checked against the live install before claiming it: `QAT_FUNDAMENTALS_SOURCE=yfinance`,
no fallback warnings in the log, and a 135KB `fundamentals_cache.json`. So the
deployed build shows real figures and the hazard is **latent, not active** - it
bites a fresh install and a lost vendor.

The caption is loud when invented, quiet when real, and counts unanswerable
figures separately - an ETF with no earnings growth is a different failure from
an invented one, and was already visible per cell as an em dash. Same shape as
M69: state what this run produced rather than printing a standing disclaimer.

**The presets.** §4.8's complaint is that a PEG spinbox says nothing about what
a PEG of 1.5 implies, so each preset carries the sentence explaining its
threshold rather than only a name for it. Guided gets named screens alone,
Standard gets both, Professional gets the raw filters alone - three levels,
three outcomes, asserted as one test that the three do not collapse.

**Deferred deliberately: "saved custom screens"** from §4.8's Professional
column. That is new persisted configuration, and configuration that persists and
changes nothing is this project's most repeated defect - `shows_advanced()` had
zero consumers from M45 until 8 August, and the minimum hold and the M37
diagnostics were the same pattern. It waits until something reads it.

**Rendering found what the suite could not, again.** The Market/Category/Sector
row was spreading three combo boxes across the full window with each label
stranded from the control it names. Pre-existing, and invisible until the new
threshold row sat compact beside it. Every test passed through it, exactly as
they did through M63's orphaned grid row and off-scale font.

18 tests. Verified by reintroducing the M58a mistake - keying the threshold row
on `explains()` - and confirming the collapse detector catches it.

## M70 - A lot opened live never learned what it paid

8 August. The residual half of M65, and the half that could not be healed at
startup.

`_announce_fill` publishes when an order reaches "filled" OR "transmitted",
taking `order.filled_price or order.reference_price`. Alpaca returns "filled"
only on a same-second fill; anything queued, slow or partial acknowledges as
"transmitted", where there is no fill price - so what went out was the price the
order was SIZED against. Two subscribers then built on it: the bridge stored it
with `setdefault`, and the ledger opened the lot at it and derived `entry_cost`
and both excursion seeds from it.

**`reconcile_entry_prices` heals that at the next startup. A position opened and
closed inside one session never reaches a next startup** - its ClosedTrade is
already written, against a basis the account never paid, wrong in both the P&L
and the R-multiple denominator. That is the case the M65 fix structurally cannot
reach, and it is the case that writes the record.

**The price was already in the building.** `recent_fills` returns every filled
order for a tracked symbol carrying `filled_avg_price`, and
`_symbols_to_watch_for_fills` includes anything with an order in flight - so the
app's own entry comes back on the very next poll and was discarded at
`_is_foreign_unrecorded`, because it is ours. The authoritative number was
fetched every poll and thrown away. The fix stops throwing it away.

`EntryPriceCorrectedEvent` carries it, and is deliberately **not** a second
`OrderFilledEvent`: that one is a fact about a quantity as much as a price, and
both its subscribers act on the quantity - the ledger opens a lot per buy, and
sign_off has already counted the fill. Re-announcing would double the position
on the Performance tab and re-create the M46 discrepancy that halted 4 August.

**A second consequence, which nothing looked broken about.** `entry_slippage` is
`entry_price - reference_price`, and for a live-opened lot both were set from the
same transmit-time announcement - so it read **zero by construction** on every
entry this app has ever opened. M44 is scheduled to ask in September whether the
flat 5bps cost assumption holds, and `entry_slippage` is its instrument. It would
have answered "no slippage, ever": a fabricated measurement rather than a
measured one, and indistinguishable from a real result.

**Found while building it, and it is not cosmetic.** `_fill_query_floor` already
reaches back past every remembered fill, precisely because an order still filling
keeps the `filled_at` of its FIRST execution - that is what let 17 CVS shares
vanish on 5 August. But it reaches back past `_absorbed_fills` only, and an order
this app sent is never absorbed. So a partial entry was covered by neither term:
its price would be corrected to the average of the first piece and then never
again, because the row carrying the final average still carries the first piece's
stamp and falls outside the window. `_own_partial_fill_stamps` closes that, and
is dropped as soon as the order completes.

The freeze: fix-immediately, as anything that corrupts the record is. Noted
because it is not free - `entry.price` feeds the minimum-hold loss escape at
`signal_bridge.py`, so a corrected price can change one exit decision. That is
the same exposure the deployed startup heal already carries, and the direction is
towards the truth rather than away from it.

16 tests. Verified by disabling the fix and confirming 9 of them fail, and by
disabling the floor reach-back alone and confirming the partial-fill case fails
on its own.

## M71 - The same root cause on the way OUT - found, not fixed

8 August, found while building M70 and deliberately left.

`_announce_fill` does not distinguish sides. A sell this app transmits - a signal
exit, a time stop, a delever trim - announces at the reference price for exactly
the same reason, and `_close_against_lots` takes the ClosedTrade's **exit** price
from it. So realised P&L is wrong on the way out too, and directly rather than
through a basis.

Two things make it a separate item rather than part of M70:

* **Most exits here are broker-side.** A resting stop or target fills at the
  broker and arrives through `absorb_broker_fills` carrying the real price, which
  is already right. The app-transmitted sell is the minority path.
* **Correcting it means rewriting a record already on disk.** M70 corrects an
  open lot in memory, before anything is written. By the time an exit price is
  known to be wrong the ClosedTrade is in `closed_trades.csv`, and rewriting a
  written trade is a different class of change - the same class as the CVS
  correction, which was done by hand and backed up first.

Not yet verified against a live transmitted sell; the above is read from the
code. Do that before designing the fix, and check whether a market sell inside
market hours comes back "filled" often enough that the path is rare in practice.

## M69 - The walk-forward panel did not state its own limitation

8 August. Step 4.5 of `UI_UX_APPROACH.md`, and the brief was right this time -
checked before building, after being wrong in detail three times running.

**Walk-forward slicing MANUFACTURES an entry at each window boundary.** For a
continuously-held strategy the windows are therefore 60-day chunks of one hold
rather than N independent tests - and every figure the panel prints is computed
from them. This document already measured it:

> Swing barely trades. Exposure changes 7 times in 300 bars and never returns to
> zero after bar 52 - one trade per symbol in 14 months. So the Monte Carlo cone
> resamples near-buy-and-holds, and walk-forward manufactures exactly one entry
> per window at the slice boundary: 12 symbols, 1 full-run trade each, 3
> walk-forward trades each. **Neither tool says much about swing until it
> exits.**

**The deploy gate is on this screen.** An operator reading a Sharpe spread
computed from one trade per window is the over-reading that matters, and the
`Trades` column was already there - the number was on screen with nothing to say
what it implied.

### Stated as a measurement, not a warning

The caveat names **the count this run produced**:

```
... Reasonably consistent across periods. But 3 trade(s) across 3 window(s) -
1.0 per window. Slicing manufactures the entry at each boundary, so for a
strategy that holds continuously these are chunks of one hold rather than
independent tests, and the figures above describe the slicing as much as the
strategy.
```

A standing disclaimer is scrolled past; a number computed from the run in front
of you is not. It therefore **self-suppresses** when the strategy trades enough,
which is what stops it becoming the boilerplate it replaced - and a test pins
that.

**Appended rather than substituted**, because both facts can be true at once:
the windows may be perfectly consistent AND built on too few trades to mean
anything. The existing headline chain already worked this way, so this is one
more branch rather than a new mechanism.

### The cone beside it, closed the same day

The sentence above covers **both** tools, and the first pass gave only the
walk-forward panel its caveat. The cone is built by **resampling** the
backtest's trade sequence, so resampling a sequence of one trade produces
something that looks like a distribution and is one observation repeated - the
spread between p5 and p95 is then an artefact of the resampling rather than a
range of plausible outcomes.

It now carries a caption naming what it was built from:

```
Resampled from 1 trade(s) in the backtest above. That is too few to resample
into a distribution - the spread between p5 and p95 is one observation
repeated, not a range of plausible outcomes.
```

Same self-suppressing rule: above ten trades it states the count and stops.
**Zero trades is worded separately** - "the cone above is empty, not a forecast
of zero" - because an empty cone and a cone predicting no growth look identical
and mean opposite things.

## M68 - The correlation table measured a different quantity from the rail

8 August. Step 4.7 of `UI_UX_APPROACH.md`, second half.

The Risk Console's matrix correlated **~60 intraday TICK samples** — about the
last hour at a 60-second poll. The cluster cap correlates **60 DAILY bars**,
about three months, a window M58b chose deliberately after finding that 300 bars
averaged away a genuinely correlated pair.

So the table an operator read to understand the correlation limit was not
showing the correlation that enforces it. **AMAT/AMD at 0.79 against a 0.70
threshold — a binding pair in the live book — could not appear on it at all**,
because it was not that quantity.

`PortfolioGovernor.binding_pairs()` publishes the rail's own answer. The
pairwise computation is extracted into `_pair_correlation` and **shared** with
`_correlated_holdings`, so alignment, the twenty-observation minimum and the
sixty-bar window are one implementation rather than two that resemble each
other. The existing governor tests passing unchanged is what says the refactor
altered no behaviour.

Read-only, adding no judgement — it publishes a calculation the rail already
performs — so it changes no decision and sits inside the freeze.

**The screen asks and never recomputes.** A test replaces the governor's method
with one returning a pair the raw numbers would not produce and asserts that is
still what renders. That is the test which fails if someone later "simplifies"
the panel by correlating `_price_history` again.

Binding pairs show at **every** level: a constraint on what may be traded is the
fact, and the matrix is the detail. "Nothing held" and "held things that do not
correlate" are worded differently, because only one of them is reassuring.

## M67 - The screen called "why was I refused" did not answer that

8 August. Step 4.7, first half.

It showed four VaR/ES tiles, a correlation matrix, the kill-switch and (since
M60) quarantined positions — and **nothing about refusals**.

That mattered more than it had that morning, because **M64 made the Regime
Monitor point here**: when the regime permits a strategy and nothing still
trades, that screen now says *"the reason is a risk rail — see the Risk
Console."* A forward reference to a screen that cannot answer is the M58a
pattern, and it was created and closed on the same day.

The numbers come from `summarise_refusals` over `load_risk_decisions` — the same
functions the daily report uses — so the screen and the report cannot describe
one night differently. A test asserts the headline is identical to what the
report would print, which is what fails if someone counts rows on the screen
instead.

### The brief was overruled, and it is the third time

§4.7 puts *"kill-switch control"* at Professional and hides the screen entirely
at Guided. `ui_level.py` says warnings, **refusal reasons** and the sign-off gate
are identical at every level, and that safety is not a level. A Guided operator
unable to reach the halt control is the worst thing that document could have
produced.

**Depth varies; presence does not.** Guided gets the plain sentence, Standard
adds the families and their counts, Professional adds the audit log. Tests pin
the kill-switch at all three levels.

Third time the brief has been wrong in detail — M63 on the Balances premise,
M64 on the macro panel, this on the level. Recorded rather than worked around
silently.

### Caught by rendering it against the real record

The first draft loaded the whole file, so it read **"2,629 candidates
considered"** while meaning *since the file was created*. That is **M56b
exactly** — lifetime totals under a heading implying a session, the defect where
the 6 August report claimed a kill-switch that had fired on the 4th —
reintroduced on a screen one day after being fixed in the report.

The synthetic ten-row fixture could never have shown it. Now bounded to today,
the heading says so, and a test writes a row dated yesterday and asserts it is
excluded.

## M64 - The Regime Monitor says what the regime DOES

8 August. Step 4.6 of `UI_UX_APPROACH.md`.

The screen rendered the label and seven probability bars - the **inputs** - and
never which strategies that permits, which is the fact governing whether
anything trades.

**Eligibility is not the label.** Since M27b it is probability *mass*, summed
across a strategy's suitable regimes against a 0.5 threshold, because the label
is one draw from a distribution and collapsing to it turns a near-tie into a
certainty. So an operator reading `Regime: bear` had to *infer* that swing had
stopped. Now the screen says `swing: NOT PERMITTED`, and at Standard shows the
arithmetic - `0.20 of the distribution sits in bull / low_vol / recovery /
sideways (threshold 0.50)` - which is self-checking against the bars beside it.

Direct precedent for the error: **M57c had to fix a regime LOG line that
described a mechanism replaced in M27b.** The screen carried the same defect and
nothing had corrected it.

Eligibility is **asked** of `StrategyEngine`, never recomputed from `probs`.
`eligible_mass()` became public for that rather than the arithmetic being
duplicated in a view - the same reuse rule the adopted-positions panel follows.

### The race, which is why this was not just a label change

`EventBus.publish` dispatches with **`asyncio.gather`**, so every handler for a
`RegimeEvent` runs concurrently. Subscription order buys nothing. A screen that
asked `is_eligible()` from its own handler could therefore render the
**previous** regime's verdict - at exactly the moment a regime changes, which is
the one moment anybody is looking at this screen.

So `StrategyEngine` now notifies listeners after it has read the distribution,
matching `KillSwitch.add_listener`, which exists for precisely this reason:
views of the switch silently disagreed with it.

**It surfaced as one failing test out of eighteen** - a bear regime reporting
swing as PERMITTED - and was easy to dismiss as a fixture problem. It was not. A
test now gives the screen a bear event the engine has not seen and asserts the
verdict does *not* move.

### Scope

Kept to the regime. When the regime permits a strategy and nothing still trades,
the screen **names the Risk Console** rather than deriving a second refusal
picture that could disagree with the first - §4.7 owns that question.

Departs from the brief on the macro panel, which it places at Professional only.
Standard is the default level and already has it, so that would strip a feature
from the default experience; the driver table alone distinguishes Professional.
Recorded as a decision, not an oversight.

## M63 - The Dashboard says which figures this system will act on

8 August. Step 4 of `UI_UX_APPROACH.md`, and the first Dashboard work.

**The brief's diagnosis was wrong, and checking took two minutes.** §4.1 says the
Balances panel shows twelve fields *"most of them dashes on an Alpaca paper
account - margin, day trades, short market value"*, and prescribes collapsing
the unavailable ones. Measured against the live account: **ten of eleven cells
carry a figure**, and only the day-trade count is a dash. Margin is reported and
substantial. The prescribed fix would have collapsed one cell and addressed
nothing.

**The real problem is inapplicable data at equal weight.** Margin and buying
power are real, prominent, and describe broker capabilities this application
structurally refuses to use - a buy's notional can never exceed available cash,
and that is not configurable. Buying power reads **$336,486 against $44,771
spendable**. The panel's own docstring already called that gap *"the single most
confusing thing about running the two side by side"*, and only a tooltip said so.

So the panel is two groups: what the system acts on, and *"At the broker - not
used by this system"*. Short market value is demoted for being structurally zero
on a long-only system rather than for being missing. **Account status stays
primary at every level** - `BLOCKED` is the one genuinely safety-relevant cell
here.

### Three settings must give three outcomes

The first draft gave Guided and Standard **identical screens**, because
`explains()` is true for both. That is M58a in miniature - an operator picks a
level and nothing changes. Caught by the operator in review, before
implementation.

| | Guided | Standard | Professional |
|---|---|---|---|
| Captions | on | on | off |
| "At the broker" group | absent | folded | open |

`prefers_density()` is the new predicate; `shows_advanced()` gains **its first
consumer since M45**, which is the exact gap the handoff records, and it fitted
without anything being invented for it.

Hiding figures at Guided is sanctioned by `ui_level`'s own doctrine - *"a control
that is absent is one level away, and the level selector says so"* - and M58c's
"never quieter" rule governs safety content, which balances are not. At Guided
the buying-power cell is gone, so the caption beneath **Spendable here** is what
stops an operator seeing $336k at Alpaca and finding nothing here to explain it.

### Rendered, not trusted to a green suite

The panel was screenshotted at all three levels before the commit. Two defects
that every test passed through:

* the demoted row orphaned its fifth cell onto a row of its own, reading as a
  new section rather than the tail of this one;
* the caption font was off the closed type scale - caught by the design
  system's own test, which is step 1 of this work doing its job.

## M62 - A broker payload fragmented one cause into many

8 August. A guard on a rail that had already failed once for this reason.

The daily report's narrative died on its 8,000-char context cap **every day from
31 July to 6 August**. M56b fixed it on 7 August, by bounding the report to the
day it covers and stripping quoted amounts out of the aggregation key. Verified
rather than assumed: today's code over 6 August's journal rows yields **3 keys
and 118 characters**, where the report actually written that day had **113 keys
and 9,020**.

So this is not that fix. It closes the one route out of it that remains.

`OMS.sign_off` records `f"broker refused: {exc}"`, and an Alpaca exception is a
JSON blob carrying the quantities of that specific order:

```
312x broker refused: {"available":"0","code":40310000,"existing_qty":"7", ...
104x broker refused: {"available":"0","code":40310000,"existing_qty":"82", ...
```

Every distinct `existing_qty` mints a new key - exactly the fragmentation the
amount-stripping exists to stop, arriving by a route it cannot see, because the
varying parts are bare integers inside JSON rather than `$` or `%` amounts.
Nothing bounds how many there could be; they have simply not yet landed inside a
bounded reported day. On 4 August's real rows this takes 10 keys to 9.

**The journal keeps the whole payload. Only the grouping key drops it.**

The row cap is the guard that does not depend on predicting the next
pathological reason string: twelve causes are named, then the remainder is
counted rather than listed. Nothing is silently dropped - what is omitted is
named and counted - and 113 near-identical rows were unreadable anyway.

## M61 - Testing the machinery deliberately, instead of waiting for luck

8 August. A reframing more than a feature, and it resolves a tension this
document has carried without naming.

**The trial is doing two jobs that conflict.** Collecting edge evidence wants a
frozen configuration and naturally occurring trades. Validating the machinery
wants edge cases *provoked*, because they will not occur naturally in a book of
ten megacaps. M39, M43, M44 and M54 are all blocked on "wait for an event that
may never come".

*"Where this is ultimately going"* already settles which of those matters. The
edge numbers will not transfer to the ASX and should not be carried across
without being re-earned; **what transfers is the machinery.** Protecting the
edge baseline at the cost of not testing the machinery optimises the output that
will be discarded, at the expense of the one that will not - and on a paper
account, at no financial risk whatever.

So rules may be varied to make a test possible, and the variation is then
evaluated on its merits. What still constrains us is not money but **the
record**: the ability of a later reader to tell a real defect from a test
artifact.

### M54, exercised against a real broker failure at last

Deployed 6 August, and until today it had **never once run** - it fires only
when Alpaca actually errors, and Alpaca had not. Its tests use fakes that raise
on command, which proves the handler catches an exception and not that the real
SDK's real failure is the shape the handler expects.

Driven through a real `TradingClient` with deliberately invalid credentials
against the real endpoint. All three promises hold:

```
broker.account() raised APIError: {"message": "unauthorized."}
  no exception escaped
  1 rejected order: MNST buy qty=0
  journal on disk: outcome='rejected' reason='account unavailable: APIError'
```

**Caveat, recorded rather than glossed.** The 6 August outage was an HTTP 500
and this produced a 401. Both surface as `APIError` and the guard catches
`Exception`, so the structure holds for either - but this proves the SDK's error
shape is handled, not that a 500 is identical. It needs no market, no capital
and no rule change, and it should be re-run whenever the adapter changes.

### `entry_allow_list` - and why the existing one could not be used

Observing a corporate action means holding the affected name, which means
widening the position and risk caps - at which point the strategy is free to
open anything else in the same session. This narrows that to the symbol under
test, changing nothing about how anything is sized.

**`symbol_allow_list` already existed and is the wrong tool.** It gates
`submit_order` *and* `submit_exit_order`, so pointing it at one symbol would
have made every other held position unsellable through the app - a gate
silently suppressing the only route to selling, which is exactly what M56c was.
Found by reading the two call sites before wiring it, not by a failing test.
The new list gates entries only, and a test asserts that an exit and a de-lever
trim on an unlisted held symbol both still pass.

Empty by default, and `entry_allow_list_set()` returns **None rather than an
empty set** - the two mean opposite things downstream, and a default that
refused every entry in the book would be the worst possible failure.

A test asserts the Runtime actually reads it. That question - *when something is
added, what reads it?* - has now had to be asked of the minimum hold, the
expertise level and the whole M37 diagnostic set, and in each case the answer
was "nothing".

### The caps themselves need no code

`max_concurrent_positions` and `max_aggregate_risk_at_stop_pct` are already
settings. The two rails are co-binding by construction, which works in our
favour: at 5.02% against a 5.00% cap the risk rail refuses everything regardless
of free slots, so raising positions to 11 and the cap to roughly 5.5% admits
about one small position and then binds again on its own. A self-limiting lever
rather than an open door.

## M59 - A protective stop that moved was invisible

8 August, found while measuring for M39 and independent of it. No corporate
action is needed for this to bite.

`verify_position_stops` compared PRESENCE - `symbol not in resting` - so a stop
that was still resting, at a different price, passed the check. Only
disappearance was ever watched. The 31 July incident that created this rail was
six stops vanishing at once, and the rail was built to the shape of that
incident rather than to the question it was asked.

**Why this is not bookkeeping.** `_position_stops` is the denominator of every
risk-at-stop figure `PortfolioGovernor` gates new entries on: a position with a
known stop risks the distance to that stop, one without risks its whole value.
The book sits at **5.02% against a 5.00% cap**, so a belief wrong by a factor
mis-states the aggregate - and the aggregate is shared. A wrong denominator on
one symbol refuses entries in every other.

**A drifted stop is replaced, not dropped.** The position IS protected, just not
where this app thought, and the broker is the authority on what rests. Dropping
it would count a protected position at full value and overstate the very
aggregate the fix exists to correct.

**The tolerance is relative, not absolute.** A book holding WFC at 87 and GS at
1,040 cannot share an absolute epsilon: one loose enough to absorb rounding on
GS is blind to a real move on WFC. At 1e-4 it absorbs cent-level rounding on
every price in the book.

The only production caller discards the return value, so widening its meaning
from "lost its stop" to "protection no longer trustworthy" breaks nothing.

## M60 - Something outside this application changed a held position

8 August. The part M39 (corporate actions) and M43 (halts) share, built once so
the second costs a producer rather than a mechanism: **reconciliation being able
to be told a difference is explained, and a position being in a state the
ordinary path must not treat as ordinary.**

### What Alpaca actually reports, measured

Three read-only probes against the paper account, per the instruction in *"How
Alpaca actually represents orders"* above.

A forward split is `old_rate=1.0, new_rate=4.0` - the ratio is `new/old`. A
reverse split inverts it. Each record carries `ex_date`, `record_date`,
`payable_date`, `target_symbol`, `target_original_cusip` and a stable
`corporate_action_id`. `GetCorporateAnnouncementsRequest` accepts a `symbol`
filter server-side, so a detector queries one symbol rather than sifting the
~1,600 records a year the market produces.

Two traps in that data:

* **`target_symbol` is absent on roughly 10% of records** - 32 of 291 reverse
  and 8 of 63 forward splits in an 88-day sample. A market-wide scan is
  unreliable; the per-symbol query is the right shape.
* **`payable_date` can precede `ex_date`.** CRWD's are 1 and 2 July. `ex_date`
  is the one to key on.

`TradingClient` wraps no account-activities method in alpaca-py 0.43.5 -
activities are Broker-API-only there. The REST endpoint answers directly, and
says this account has processed **zero corporate actions, ever**.

### The near-miss that shaped it

**CRWD split 4-for-1 with ex_date 2 July.** We hold 16, bought on 31 July -
after the split - and the resting OCO is correctly sized for 16 post-split
shares. Nothing is wrong with the position.

That is exactly why it matters. **A detector matching on symbol and ratio over a
recent window would flag our CRWD holding as split-explained today, and be
wrong.** The false positive is in the book, not in a thought experiment. Any
future detector must gate on `ex_date` falling after the position was opened.

It is also why automatic detection is **deliberately not in this milestone**.
The piece that can be wrong in the dangerous direction - declining to halt on a
divergence that is not a split - is the piece deferred until there is evidence
to build it against.

### The binding rule, which is the design

An explanation is tied to the quantity the **broker** reported when it was
declared. Without that binding, declaring a symbol explained once grants
permanent immunity and the next genuine divergence passes in silence - the
failure `adopt_broker_positions` already warns about, where an operator is
trained to ignore the one signal meaning *"my view of the account cannot be
trusted"*. A difference declared at 16-to-64 does not explain a later 64-to-128.

Quarantine and explanation are deliberately separate questions: a position that
moves again stops being explained and stays quarantined, because it is no less
suspect for having moved.

### Block writes, allow exits

New entries and de-lever trims are refused; an ordinary exit is allowed and
**re-sized from the broker**, because the tracked quantity is the one known to
be wrong - selling 16 of 64 leaves three quarters of a position nobody intended
to keep. Refusing exits would be the shape M56c was a defect for, where a gate
quietly suppressed the only route to selling. The single exception is a broker
read that fails: exiting a known-wrong quantity on a symbol already flagged as
untrustworthy is worse than not exiting, and the refusal is a rejected order
carrying a reason rather than a silent gate.

Two further sites, both previously silent:

* **`rearm_protective_stops` is the liquidation guard.** The recorded entry stop
  predates whatever quarantined the position, so re-arming from it after a
  4-for-1 split rests a sell-stop at roughly four times the new price - which
  triggers immediately and liquidates at the next open.
* **`restore_open_lots` was corrupting the ledger silently.** It takes QUANTITY
  from the broker and BASIS from `_entries`, so after an external quantity
  change it builds a lot at the post-event size on the pre-event basis - and no
  warning fires, because the entry record exists. P&L is then wrong by the
  event's factor and R wrong in its denominator, feeding the promotion gate and
  the September evidence. **`_Entry` carries no quantity**, so there is nothing
  to compare against and no cheaper guard than the quarantine.

### The restart that laundered it

`adopt_broker_positions` reseeds `_filled_quantities` wholesale from the broker,
so a divergence **vanishes** across a restart: tracked matches broker,
reconciliation is content, and the entry record and ledger stay wrong. With an
overnight session and a restart between each one, that is the normal path and
not an edge case. The store therefore persists, is loaded before adoption, and a
quarantined position whose quantity has changed *again* is reported before the
evidence is overwritten. The adoption banner names quarantined positions,
because the operator is told to read the startup lines.

### What this does not do

**It contains damage; it does not repair it.** A declared anomaly stays
quarantined until the underlying records are corrected by hand, as the CVS
ledger was on 6 August. The Risk Console carries a permanent line saying so, and
a test asserts that wording - *"declared"* reading as *"fixed"* is the one
failure this could introduce, and a reviewer sees the text once where an
operator sees it every session.

Nothing is quarantined today, so the only behaviour that changes on the next
session is M59's.

### Under the freeze

Both milestones are fix-immediately and neither changes which trades the
strategy chooses or how it sizes them. M59 is *"protective orders not resting,
or not being repaired"*; M60 is *"the kill-switch tripping on something that is
not a real discrepancy"*. M60 adds no automatic judgement: the application halts
less **only** where a human has explicitly said why, and otherwise refuses
strictly more than before.

## M49 - The ledger could not record the trades the trial exists to collect

Found on 5 August by asking whether M48's missed fill actually cost anything.
It does, but the far larger problem was that **a fill which IS caught recorded
nothing either**. Demonstrated before it was fixed:

```
absorbed fills     : 1
open lots in ledger: []
CLOSED TRADES      : 0
```

Two independent halves, each fatal on its own.

**Entry lots lived in memory alone.** A closed trade is only produced by
matching a sell against an entry lot, and `TradeLedger._open_lots` starts empty
on every run. A position opened in an earlier session therefore had no lot - and
with a ten-day minimum hold, a thirty-day time stop and a session per night,
that is every position this system holds. Its stop would fire, be absorbed
correctly by M48, log *"this is now a closed trade"*, and record nothing. The
log line was false.

**Closed trades did not survive a restart either.** `_closed` was in-memory
while `closed_trades.csv` beside it was append-only and never read back. Every
consumer - `EdgeEstimator`, the promotion gate, the scorecard, the reports -
goes through `closed_trades()`. So the count reset to zero every night, and a
gate needing 30 per strategy could never have reached them.

Together: **the validation phase could not produce its own evidence.** Not
"would have been noisy" - could not produce it at all, for months, while every
screen showed the system working.

The sizing consequence runs opposite to intuition. The only recordable trades
were those opened AND closed inside one session, which for a ten-day-minimum
swing strategy means fast losses. So whatever accumulated was biased toward
losers, and `EdgeEstimator` would have sized DOWN on it. Less dangerous than
the reverse, and just as wrong.

**The fix.** Reconstruct the lots at startup from the broker's positions plus
`open_position_entries.json`, which already carries the open date, the entry
price and the stop - and the stop is not decoration, it is the denominator of
every R-multiple the gate reads. Read `closed_trades.csv` back at construction.
Three raw columns (`reference_price`, `worst_price`, `best_price`) join the
file so a reloaded trade can still recompute the M37 excursion diagnostics; the
file did not exist yet, so there was nothing to migrate.

Restoration lives in `SignalToOrderBridge` for the same reason re-arming does:
it is the only component holding both halves. It refuses to touch a symbol that
already has lots, because a startup step must never outrank a live fill.

**Two things deliberately not invented.** A position with no entry record is
skipped and named in a WARNING - the broker knows what it paid but not when it
was bought, and a fabricated open date would put invented holding periods into
the evidence. And excursion on a restored lot measures from the restart
forward, understating MAE and MFE, which is acceptable where fabricating them
is not.

Strategy attribution is now recorded on each entry. Entries predating this fix
name none, so it resolves to the sole deployed strategy when exactly one is
deployed - `swing`, confirmed by the operator as the only strategy ever
tested - and to nothing when two are running, where guessing would fabricate an
attribution inside a per-strategy promotion decision.

## M50 - The absorb watermark did not survive a restart

`OMS._last_fill_scan` started at construction, so a protective fill that landed
while the app was down was never asked for. Reconciliation did not trip -
adoption re-baselines quantities from the broker - but the closed trade was
lost, which after M49 is the only part that still matters.

Narrower than M49: it needs the app to be down, or restarting, at the moment of
the fill. Not negligible - the app restarted three times during the 4 August
session alone, and each restart opened a window of up to the poll interval.

**The trap, as predicted.** Simply persisting the watermark reintroduces M46:
`adopt_broker_positions` has already set `_filled_quantities` from the CURRENT
broker positions, so re-absorbing a pre-restart sell subtracts the same shares
twice and trips the kill-switch on arithmetic. Absorption has to be split into
**recording the fill** and **applying it to the quantity arithmetic**.

**The trap's obvious solution was also wrong.** The first attempt decided
whether a fill was already in the baseline by comparing `filled_at` against the
moment adoption ran. That is the right *concept* and an unusable *mechanism*:
the two stamps can land in the same clock tick, and each way of breaking the tie
trips the kill-switch from one side or the other. It failed three separate tests
before the design changed rather than the boundary.

The mechanism that works asks nobody's clock. A replay records the fills and
then **re-reads the positions from the broker**, which is the only thing that
actually knows what is held. Adoption already uses that principle; this extends
it. `_adopted_at` was deleted.

**What makes a replay safe to repeat** is `absorbed_fills.json`, holding the
watermark plus the ids of fills already recorded, pruned to 30 days. A watermark
alone cannot say whether a fill on its boundary was recorded, and recording a
closed trade twice would inflate the very count the promotion gate reads. The
watermark advances only after a pass completes, so a crash replays rather than
skips - which is safe precisely because the ids make it idempotent.

**A third instance of the same lesson.** The replay found nothing at first,
because both symbol sets the OMS can build are empty for exactly the symbol it
needs: the broker has dropped the closed position, and a fresh process adopted a
book that never mentioned it. Bound by what the app BELIEVED it held - the entry
records - via `OMS.watch_symbols_for_fills`. M47 bounded by held symbols, M48 by
tracked symbols, M50 by remembered ones; each time the wrong set was the one
that looked natural from where the query lived.

Also fixed here: the absorbed fill's `OrderFilledEvent` now carries
`ts=fill.filled_at` rather than the time it was noticed. A replayed exit can be
days older than the pass that finds it, and the ledger stamps `closed_at` from
that field - so without it the evidence would carry holding periods nobody held.

## M48 - `recent_fills` could not see the fill it exists to catch

Found while measuring for M47, on 5 August, and fixed the same day.

`recent_fills` asks Alpaca for `status=CLOSED, after=self._last_fill_scan`,
where that cursor advances to now on every reconciliation poll - so the window
is about five minutes wide. **`after=` filters on `submitted_at`, not on fill
time**; this was measured, not assumed. A protective order submitted days or
weeks ago and filling today therefore falls outside the window and is never
returned.

That is every protective order the system has. A bracket leg's parent was
submitted when the position opened; a standalone OCO was submitted when it was
re-armed. Neither was submitted in the last five minutes.

The consequence lands on the first stop-out this system ever has, and it lands
twice:

* `absorb_broker_fills` never sees the fill, so no `OrderFilledEvent` is
  published and **the trade ledger records no closed trade** - the promotion
  gate accumulates nothing from the only exits swing actually has.
* Reconciliation then compares tracked 16 against broker 0 and **trips the
  kill-switch**, halting the session on a stop doing precisely its job.

Losing the record is the worse half. M34 exists to prevent exactly this pair of
failures and has never been exercised against a real protective fill, because
there have been no closed trades. The five absorptions on 4 August all worked
only because those were the app's own entries, filling minutes after they were
submitted and so inside the window by accident.

**Why it is not simply M47's fix again.** The relevant symbol set is different.
`resting_stops` asks about currently-held positions; a stop that fills makes
its position disappear from `positions()`, so "currently held" is the one set
guaranteed to exclude it. The query needs the OMS's own tracked quantities,
which the adapter does not have, so the symbol set is passed in -
`OMS._symbols_to_watch_for_fills`, built from `_filled_quantities` rather than
from the broker.

**The fix.** Drop `after=` entirely, bound the query by those symbols the way
M47 bounds its own, and apply the window to `filled_at` locally - the axis that
was meant all along. Every order for a tracked symbol now returns, so that
local check is what stops one poll re-absorbing the account's whole history.

**Measured, because history could not show it.** No protective leg has ever
filled on this account, and every entry is a market order whose `submitted_at`
and `filled_at` are the same instant - which is exactly why nothing had ever
exposed this. The demonstration is therefore structural: take the legs resting
now and ask whether each query shape can return their order at all, using the
five-minute cursor the app really runs with. A query that cannot return the
order can never report its fill.

| | Reachable |
|---|---|
| Old shape (`status=closed, after=now-5min`) | **0 of 10** |
| New shape (`status=all, symbols=<tracked>`) | **10 of 10** |

Ten of ten. Every position in the book would have had its stop-out missed.

**The pattern, for the third time.** M31d, M33d and M47 were all "assume a
filter returns what its name suggests". `after` is the same mistake in the same
month - it reads as "activity since" and means "submitted since". The lesson
already written at the top of this section is now paid for twice: ask the
broker what its parameters mean, do not read them.

Behind no freeze: this is recording an execution that already happened.

## M53 - A partial fill halted the first session that ever recorded a trade

5 August, eight minutes after the open, and caused by M50's own dedupe.

A CVS stop gapped through at the open and filled **47 shares in pieces**. The
app read the order mid-fill, absorbed **30**, recorded the order id in
`absorbed_fills.json` as done, and never counted the remaining 17. Tracked 17
against a broker holding 0 is a discrepancy, and reconciliation answered it with
the kill-switch.

**Three separate mistakes, each of which alone was enough.**

*The dedupe asked the wrong question.* M50 keyed on order id: "have I seen
this?" A partially filling order reports the SAME id with a growing
`filled_qty`, so the question had to be "has anything new executed?". Fixed by
remembering how much of each order has been counted and absorbing only the
delta.

*The increment's price is not the latest average.* `BrokerFill.quantity` and
`.price` are both cumulative, so the second piece's own price has to be
recovered as `(avg_new x qty_new - avg_old x qty_old) / delta`. Taking the
blended average instead would misstate realised P&L on every multi-piece exit.

*The query floor excluded the very order it needed.* An order still filling
keeps the `filled_at` of its first execution, which is already behind the
watermark by the time the rest completes - so the adapter dropped it before the
OMS could see it, and the delta arithmetic never ran. The floor now reaches back
past every fill still remembered. Re-reading a completed one is free: its
cumulative quantity is unchanged, the delta is zero, it is skipped.

**And a fourth, in the bridge.** `_on_fill` dropped the whole entry record on
any sell. A partial exit therefore left the remainder with no stop to re-arm to,
no minimum hold, no time stop, and no way for a later exit to become a closed
trade - the entry it would have been measured from was gone. It is now asked of
the broker whether the position is actually flat, and a failed query keeps the
record, because a stale record is cleaned up by the time stop within a sweep
where a deleted one cannot be recovered at all.

**This is M42, which the roadmap called "unlikely on liquid large-caps with
market orders, and not unlikely forever".** Forever turned out to be eleven
hours. It was made certain, and permanent, by M50's id-only dedupe - a fix that
introduced the failure it was written to prevent, in a narrower case.

The trade itself survived: CVS 30 shares at 95.36 against a 105.475 entry, -1.73R
after costs, the first closed trade this system has ever recorded. The remaining
17 shares are missing from that record and want correcting by hand.

## M57 - Earnings are a scheduled event, not a draw from the distribution

7 August, from an independent review, and the one recommendation in it that was
both correct and unbuilt. Ships with M56c as a single deliberate break in the
freeze.

Every other rail here reasons about how prices usually move. An earnings
announcement does not obey that: it is a known date carrying a binary outcome,
and the gap it produces can open straight through a resting stop - the one
hazard a stop cannot cover, because the price never trades there. This ledger
has already paid for it once, when the CVS stop gapped at an open and filled 47
shares in pieces.

**Halve, not refuse.** Refusing loses the setup outright, and at a ten-position
limit this book already turns away hundreds of candidates a night for capacity
it cannot use. The direction of an earnings move is unknown; that it can be
large is not, so the response is to take the same trade at half weight. The
scalar sits beside the regime scalar because it is the same kind of thing - a
market-condition multiplier on size - and the two compound deliberately.

**Unknown means abstain, never safe.** A vendor genuinely cannot answer for
every listing and an ETF has no earnings at all. Every failure - no network, a
corrupt cache, an unparseable date, a calendar object of an unexpected shape -
returns None and the rail sizes normally, because that is the pre-M57 behaviour
and this rail can only ever make a position smaller. The guarantee is enforced
at the public boundary rather than inside the private fetch, after a test
demonstrated that a guard in the helper alone does not hold the contract.

**Distances are trading days**, matching the minimum hold and the time stop.
Five calendar days across a weekend is three sessions, and a rail specified in
sessions should count them against the real exchange calendar rather than
dividing by seven.

Verified against the live vendor rather than only in tests - it answered for
all ten held symbols, and two sit inside the window today: AMAT reports on
14 August (5 sessions) and CSCO on 13 August (4). Both would be halved.

**Known limitation, recorded rather than quietly widened.** This sizes ENTRIES.
AMAT reports while we already hold it and the rail does nothing for an open
position. Trimming into a print for something already held is a different
decision - it sells - and belongs with the exit work, not here.

## Booked for the September review

Measured on 7 August, deliberately not acted on. Each waits for the mid-September
time-stop burst to supply closed trades, because every figure below comes from a
replay over the ten symbols currently held - a selected set, good enough to rank
options against each other and not good enough to size a book on.

| | What | Evidence |
|---|---|---|
| 1 | **DONE 8 August (M58b).** Correlation window 300 -> 60 bars. On 60 days AMAT/AMD scores 0.79 and on 300 it scores 0.58, so a genuinely correlated pair we hold was invisible to the rail. Applied to the correlation only, never to the shared return series - VaR and ES read the same dict and want the depth | Measured, 500 overlapping returns |
| 2 | **The correlated-cluster cap is unreachable, and remains so.** At ten positions averaging 5.5% of equity, a 30% cluster needs 5.5 names moving together; the responsive window finds two pairs, not five names. This answers M51's open question - the book is genuinely diversified, and the cap is redundant against the position limit and the single-name cap that bind first. Item 1 was therefore correct and changed no decision on the current book | Measured |
| 3 | **Time stop 30 -> 45 days. DECLINED 8 August, and the number is the reason.** It defers the first time-stop wave from Monday 14 September to Monday 5 October - **21 days** - and that burst is the only evidence event on the calendar, roughly ten closed trades in three days. It buys +14% net R per slot-year from a 75-trade replay over ten currently-held symbols with no regime gate: the weakest evidence base examined this week, spent on delaying the strongest. Revisit in October, when the September trades can answer it properly | Replay, 75 trades |
| 4 | **The minimum hold is inert - and stays. DECLINED 8 August.** Sweeping 0, 3, 5, 10 and 15 trading days produces identical results: same trades, same expectancy, same signal exits, because the stop or target resolves the position before a trend break occurs. Inert is an argument for leaving it alone, not for removing it. It costs nothing measurable, and it would bind if exits ever became frequent - which M56c just made more likely by letting an ineligible strategy close what it holds. Removing a free rail during a validation phase buys tidiness and nothing else | Replay |
| 5 | **Trim an open position into its earnings print.** M57 sizes entries only. This one sells, so it belongs with the exit work | Not measured |
| 6 | **DONE 8 August (M57c).** Nothing was logged when the application stopped. Found 7 August when the process disappeared between two screenshots; the operator confirmed they had closed it, which is what made the point - a deliberate, orderly shutdown wrote **nothing at all**, indistinguishable from the silent death that let M56a masquerade as a quiet session. A run marker is now claimed at startup and released at shutdown, so a marker still present at the next start means the last run never reached its shutdown path, and says so. Verified end to end: clean close, killed run, and the warning on the following start | Confirmed |

**Not booked, and why.** Position sizing was modelled and rejected: cost on the
positions actually held is 3.8% of risk against a 10% limit, and the entire
prize from escaping the commission floor is 1.54 percentage points, worth about
0.015R a trade. The two ways to collect it - fewer positions, or a higher
aggregate cap - cost evidence rate and drawdown respectively, both worth more
than the saving. An earlier note in this session claiming 13.2% read the
report's refusal rows, which are candidates the cost rail rejected for being
too small, and mistook the rejected population for the accepted one.

## Where the 30-day hold came from, and what the exits actually do

Recorded 7 August, after the operator asked why the hold is 30 days when swing
was designed around a shorter cycle. The answer is that **the strategy's own
timeframe never entered the decision.**

Both rails come from M31, a portfolio churn-and-cost milestone. The commit says
so plainly: the time stop is 30 trading days because *"markets do not know what
two weeks means: one rail stops the system churning, the other stops it holding
forever on a thesis that never resolved."* The minimum hold is 10 trading days
on a commission argument - *"ten concurrent positions turned over weekly costs
$6,240 a year... at ten trading days it is 3.1%."* Neither number was derived
from, or checked against, how long a swing setup is supposed to last.

**Swing's intended holding period is not recorded anywhere in this repository.**
`swing.py` cites "paper §4.10" and the paper is not in the tree. That is why
nothing objected when M31 chose 30.

### What the exits do, measured

Replaying the real entry rule, the 2.5-ATR stop, the 2R target and both rails
over two years of daily bars for the ten held symbols - 75 trades:

| Ends the trade | Share | Median days | Mean R |
|---|---|---|---|
| Stop | 37% | 6.5 | -1.00 |
| Target | 35% | 19 | +2.00 |
| Time stop | 21% | 30 | +0.85 |
| Signal | 7% | 7 | -0.63 |

Three things follow, and the operator's instinct was right about the first two:

1. **The give-back is real and large.** Mean peak reached is 1.30R; mean
   realised is 0.46R. **59% of trades are still open after their best price**,
   for a median five further days. The best price arrives around day 11.
2. **The minimum hold is inert.** Sweeping it across 0, 3, 5, 10 and 15 trading
   days changes nothing at all - same 75 trades, same 0.46R, same 5 signal
   exits. By the time a trend break occurs, the stop or the target has almost
   always resolved the position already, so the rail never binds. It has been
   costing nothing and buying nothing.
3. **Strengthening the sell decision makes it worse, decisively.** Charging the
   measured round trip of 0.132R (from `risk_decisions.csv`: $18.24 against
   $138.38 at risk):

| | Trades | Gross R | Net R | Turns/yr | **Net R/yr/slot** |
|---|---|---|---|---|---|
| Today | 75 | 0.46 | 0.33 | 15.3 | **5.00** |
| Trail 2 ATR | 123 | 0.20 | 0.06 | 29.9 | 1.92 |
| Trail 1 ATR | 155 | 0.13 | 0.00 | 65.7 | 0.14 |

And on the time stop itself, holding *longer* is better, not shorter:

| Time stop | Net R | **Net R/yr/slot** |
|---|---|---|
| 10 days | 0.09 | 2.59 |
| 20 days | 0.17 | 3.19 |
| 30 days (today) | 0.33 | **5.00** |
| 45 days | 0.44 | **6.07** |

**So the 30 was arrived at for the wrong reason and is roughly right anyway.** A
10-day cycle would approximately halve net return per slot-year. Every attempt
to bank the give-back earlier multiplies trade count into a cost structure that
eats the entire edge - which is M51's finding arriving from a second direction:
**cost, not exit timing, is the binding constraint.** At 13.2% of risk per round
trip the strategy cannot afford to trade more often, and the lever that would
change that is position SIZE, not holding period.

Caveat on all of the above: this replay applies no regime gate, so it counts
trades the live system would not have taken. It is the right comparison for
ranking the exit rails against each other and the wrong one for predicting
live return.

## M56c - The regime gate switched off exits, not just entries

7 August. The first change since 3 August that alters a trading decision, made
with the freeze explicitly lifted for it by the operator.

`StrategyEngine` gated on eligibility with `continue`, above `on_features` -
and `on_features` is the only route to an exit signal. An ineligible strategy
was therefore not declining to sell. **It was never asked anything.** Swing
orders its exit check first inside `on_features` precisely because "does the
reason I am holding still hold" is a different question from "is this a good
entry"; the gate defeated that one layer up. Same shape as M47, M50 and M56a -
the layer being reasoned about was right, the layer above it was not.

What made it costly rather than untidy is the correlation. **Swing's exit
condition IS a broken trend, and a broken trend is what the excluded regimes
are.** The strategy was reliably switched off in exactly the conditions that
would have made it sell. That is the mechanism behind a limitation
`PRODUCT_DESCRIPTION.md` had already recorded without explaining: 29 entries,
zero signal exits, 1.19 years.

Measured on two years of daily bars for the ten held symbols, the condition was
true on **29% of days**, with 31 distinct trend breaks and at least one in every
symbol. The rule was never rare - it was never consulted.

**The fix is narrower than "allow sells".** Several strategies here are
symmetric signal generators: mean reversion emits a sell on overbought RSI
whether or not anything is held. Permitting sells outright would have let an
excluded strategy OPEN short exposure, which is the reverse of the gate's
purpose. The condition is therefore *closes an open position* - a sell whose
symbol is actually held. A strategy that may not open a position may still
manage one it already has.

**What it is worth, measured rather than assumed.** Replaying the strategy over
the same bars, signal exits are about 7% of exits and average -0.63R against a
stop at -1.00R. So this is not an edge improvement - it is the system cutting a
broken thesis roughly 0.37R earlier than the stop would have. The value is
correctness: holding positions the system has decided it is not qualified to
manage was wrong independently of what it earns.

## M56a - The build shipped for the session could not start at all

6 August, found nine and a half hours before the open by launching the deployed
build rather than waiting to launch it at 23:15.

M56 seeded the equity chart from `equity_curve.csv` so it opens showing history.
The seed both fills two lists and DRAWS, and it was called from the top of
`DashboardScreen.__init__` - beside the lists, forty lines above the plot it
draws onto. Every launch against a recorded curve died on
`AttributeError: 'DashboardScreen' object has no attribute 'equity_curve'`
before the window opened.

**All 1,341 tests passed throughout.** `Runtime.build_demo` points at an empty
data directory, so `points()` returned nothing, `_equity_history` came back
empty, and the draw sat behind a falsy `if` that was never entered. The M56 test
written to guard exactly this asserted `len(times) == len(history)` - which is
`0 == 0`. Every assertion held while the application could not start on any
machine with a curve on disk. This one had 7,193 samples.

**The failure mode was the dangerous one: the traceback never reached
`qat.log`.** The log stopped after `DEPLOYED swing - now live: swing` and said
nothing further. The session controller had not yet stood down, no engine had
started, and nothing recorded that anything was wrong. Watched live, this build
prints its stamp, two restore lines, and then goes quiet - which is
indistinguishable from the quiet session a full book at the position limit is
supposed to produce. The operator was primed to expect silence and would have
read a dead terminal as the rails working.

The fix is the call moved below the plot construction. The position is
load-bearing and now says so in a comment, because the original placement is the
one that reads naturally.

**The test that matters writes a real `equity_curve.csv` first** and reads back
what the curve is plotting through `getData()`, rather than what the lists
contain. Seeding that populates the lists and never reaches the plot is the
failure; a test that only inspects the lists cannot see it.

**The pattern, for the fourth time in two days.** M53a, M50's dedupe, M54's
swallowed error and this are all the same shape: the test exercised the logic
being thought about, and the defect was in the layer that was not. Here the
unexamined layer was the fixture - an empty data directory made the dangerous
branch unreachable, so the guard tested the guard's absence. **A test whose
fixture cannot reach the failure is not evidence.** Where a defect depends on
recorded state existing, the test has to write that state.

Also: `watch_session.py` did not match `Build:`, so the one line carrying the
stamp was filtered out of the live view the operator is told to check it in.
Added.

## M55 - The interface says what it is showing, and stops losing settings

Three requests from the operator on 6 August, done together because they are
one problem seen from three angles: a screen that knows something and does not
say it.

**Every chart names both axes, with units.** Measured before: ONE axis-label
call in the whole presentation layer. The labels are not decoration - writing
them forced three findings that were invisible while the axes were bare:

* The Dashboard equity chart plots `_equity_history` as a bare list, so its
  x-axis is **account polls since launch**, not time. Roughly one a minute, with
  a gap wherever a poll failed. "Time" would have been wrong in exactly the way
  that matters after an outage.
* The Workbench equity chart's data **is** indexed by timestamp, and
  `.to_numpy()` at the render site throws that index away. It is labelled for
  what is actually drawn - daily bars - because mislabelling it as dates in
  anticipation of a future fix would be worse than the honest label.
* The Monte Carlo cone advances one step per **trade**, not per day. That is why
  it widens with trade count, and why two strategies' cones are not comparable
  unless they took the same number of trades.

`theme.label_axes` requires both labels as keyword arguments, deliberately: a
chart whose axes cannot be named is a finding about the chart. A test walks
every `PlotWidget` in the app and fails on a bare axis, so the next chart cannot
ship unlabelled.

**The expertise level is finally real.** `ui_level.py` had existed since M45 and
nothing imported it - one reference in the entire source tree, in `config.py`.
There was no way for a panel to ask the level and no way for an operator to set
one. Settings now carries the selector and is its first consumer. An earlier
handoff described this step as done and deployed; only the design system was.

**Restore Defaults.** There was no way back. An operator who moved a Kelly bound
or a correlation threshold to see what it did could only return by knowing the
original, and the originals are visible only in `config.py` - the opposite of
this screen's own rule that you should always be able to see what governs your
account. It confirms first, naming the count and the fields; it restores VALUES
rather than the file, so it can itself be abandoned by closing without saving;
and it does not touch broker, watchlist, data source, execution mode or
strategies, because those are configuration the operator entered rather than
tuning they experimented with.

**An unsaved-changes prompt on close.** Every field here is restart-required,
which makes an unsaved edit invisible twice over: it did not take effect, and
nothing on screen says so. Three answers, not two - Save/Discard alone forces a
decision the operator may not be ready to make, and is how work gets thrown away
by someone who only meant to stop the prompt.

**One correction the work itself produced.** The plan claimed the operator's
"Market & Watchlist downwards" boundary excluded the write-only secret fields
"by construction". It does not: the Alpaca key and secret live in Broker & Cash,
*below* the line. They are handled explicitly instead - the prompt reports that
a key was entered and never what, and a test asserts the value cannot appear in
the dialog.

## M54 - A broker blip threw a signal away instead of refusing it

6 August, 03:56. Alpaca returned HTTP 500 from an nginx layer for ninety
seconds. One line records the cost:

```
03:56:18 [ERROR] EventBus handler failed
  signal_bridge._on_signal -> _submit_entry -> _submit_sized -> adapter.account()
```

`_submit_sized` fetched the account outside every guard, so the exception
escaped through the event bus and **the signal vanished** - no order, no
refusal, no journal entry, nothing on any screen but a stack trace.

M38 made precisely this argument about the risk evaluation inside
`OMS.submit_order` and wrapped it there. This fetch sits upstream of that guard
and was missed. What makes it clear-cut rather than arguable is that the
neighbouring paths already got it right during the same outage:
`_current_positions` fell back to its cache and logged, and the equity poll
logged and continued. The rail that threw was the odd one out.

A failure now produces a rejected order carrying the reason, through
`OMS.record_unsized_signal`, so the audit trail answers *"why did nothing
happen"* with a reason rather than a gap. Deliberately a refusal and not a
retry: the next tick re-emits the signal if the condition still holds, and a
retry loop here would hide an outage rather than record it.

**The wider point.** The trial is built on the record, not on the fill. A missed
order costs one opportunity; a missed RECORD costs the ability to know that
anything was missed at all.

## M52 - A forced session start announced "US is open"

6 August, 03:21. Two lines, logged in the same second:

```
Trading session force-started by operator (dashboard) while US is closed
Trading session started - US is open
```

The second contradicted the first. It was the generic started message,
asserting a fact about the market that the line above had just denied - and the
watcher surfaced only the second, so the operator was told the market was open
eight minutes before it was.

The started message now says HOW the session started. A forced start logs at
WARNING, states that the market is NOT open, and names what the override turns
on - because it also disarms something the stood-down message explicitly
promises, *"the staleness rail cannot trip on a market that is simply shut"*.
On 6 August that produced 94 staleness exclusions in six seconds against a
market closed for seventeen hours. Harmless there; not harmless in general, and
the operator forcing it deserves to know.

Found live on 5 August, seconds apart in the log:

```
13:21:37Z  Trading session force-started by operator (dashboard) while US is closed
13:21:37Z  Trading session started - US is open
```

The second line contradicts the first. It is the generic session-started
message and it asserts a fact about the market that the line above has just
denied. An operator reading the second line - or a watcher surfacing it, which
is how this was found - is told the market is open eight minutes before it is.

Small, and squarely against this project's own standard: a log line that says
something false is worse than one that says nothing. The started message should
state how the session started, not assume.

**Worth fixing at the same time: what a forced start actually turns off.** The
stood-down message promises that "the staleness rail cannot trip on a market
that is simply shut". Forcing the session open removes exactly that protection,
and on 5 August it produced 94 staleness exclusions in six seconds against a
market that had been closed for seventeen hours. They were harmless - they
self-cleared at the real open, and nothing was proposed - but an operator who
forces a start deserves to be told what they have just disarmed.

No trade or record was affected, so this is not behind the freeze and not
urgent. It belongs with the Settings/UX work, being the same class of problem:
the application knowing something and not saying it.

## M51 - Evaluation: does the information this system captures earn its place  **[OPEN, details deliberately deferred]**

Raised by the operator on 5 August. Partly built already, and immature - which
is the point of naming it now rather than later.

**The question it exists to answer is one nothing else asks.** Every rail,
journal and ledger in this application answers *is the information being
captured*. M37 added excursion and exit reason, M20 journals every decision, M49
made the closed-trade record survive a restart. All of that is capture. None of
it asks the next question: **is the captured information used, does its use add
value, and does anything here reduce effectiveness?**

Those are different questions and the second is harder. A field that is
faithfully recorded, correctly displayed and never acted on is pure cost. A
signal that is acted on but degrades outcomes is worse than cost. Neither shows
up as a defect, a failed test or a red line in a log - the system reports
perfect health while carrying both.

**What is already built and counts toward this:**

* `decision_journal.csv` - every proposal, refusal and its reason
* `risk_decisions.csv` - which rail bound, with its inputs
* `closed_trades.csv` - M37's diagnostics: regime at entry, exposure scalar,
  exit reason, MAE, MFE, entry slippage
* The promotion gate and scorecard - the only piece that currently closes a loop
* `entry_slippage` specifically, which was designed to answer whether the cost
  model's assumption holds (M44)

**What is missing is the analysis layer over them**, and the discipline of
deciding what to do when the answer is unflattering.

**Sequencing: after the app is stable, and after the trial has data.** Deliberately
not now, for two reasons. This milestone is *about* the evidence, so building it
before there is any evidence would mean designing measures against imagined
data - the mistake the walk-forward numbers already made. And the app has been
stable for less than a day; four defects that silently prevented any closed
trade from being recorded were fixed on 5 August, so nothing in
`closed_trades.csv` predates that.

Concretely it sits behind: a session running clean on M50+M40, and the first
meaningful batch of closed trades. It sits ahead of the UI/UX screen work, which
also waits on closed trades, because what evaluation concludes should shape what
the Performance screens are built to show.

**Details to be worked out with the operator when it starts.** Candidate
questions it should be able to answer, recorded so the intent is not lost:

* Which recorded fields have ever changed a decision, and which never have?
* Which rail binds most often, and does binding it improve or degrade the
  outcome distribution?
* Does the AI advisory layer change any outcome, in either direction? It cannot
  place an order, so its value is entirely in whether the operator's decisions
  are better with it than without.
* Is the regime classification adding value, or is the exposure scalar merely
  adding variance?
* What does the trial cost in fields nobody reads?

## Not yet addressed - integral to share trading

Found by asking what an equity trading system must handle that this one does
not, 4 August, excluding data validation. Sequenced by significance. All of what
remains is post-trial: every item changes which trades happen or how they are
sized, so it sits behind the validation-phase freeze. **M40 was the one
exception and is now done** - see its entry below.

### M39 - Corporate actions

**Nothing in the order, position or protection path knows they exist.**
`data/validation.py` mentions splits; the trading path has no concept of them.

A 2-for-1 split on a held position produces four independent failures from one
ordinary event, none of which requires a bug:

* the broker's share count doubles, reconciliation compares tracked 16 against
  broker 32 and **trips the kill-switch**, halting the session;
* the resting OCO stop sits at roughly twice the new price - it fills at the
  open or is nonsense;
* `open_position_entries.json` still holds the pre-split level, so the re-arm
  faithfully replaces protection at a price that liquidates the position;
* the trade ledger's entry price is unadjusted, so P&L and R-multiple on that
  trade are wrong by the split factor.

Reverse splits, spin-offs, mergers and ticker changes each do some version of
the same. Historical bars are already split-adjusted (`Adjustment.ALL`, M27a) -
it is only live positions that are exposed.

The shape of a fix: detect a quantity change the app did not cause and whose
ratio matches a known corporate action, adjust the tracked quantity, the entry
record and the resting protection together, and record the adjustment on the
closed trade so the P&L stays honest. Reconciliation must treat an explained
ratio change as explained rather than as a discrepancy.

**Half of that is now built - see M60, 8 August.** Reconciliation can be told a
difference is explained, the position is quarantined from the write path, and
neither the re-arm nor the ledger restore will act on it. What remains is the
DETECTION and the ADJUSTMENT, and both wait on one measurement: what Alpaca does
to a held quantity and to a resting OCO through a split. The announcement side
is measured; this side has zero observations, because the account has never
processed a corporate action.

**The adjustment is where the four-way atomicity risk lives** - tracked
quantity, entry record, resting protection, ledger basis. A partial adjustment
is worse than none: correcting the quantity but not the stop leaves protection
at four times the price, which liquidates at the next open. M60's quarantine is
what gives that adjustment somewhere safe to fail partway.

### M40 - Fundamentals were absent from the AI advisory context  **[DONE]**

`AdvisoryContext` carried symbol, regime, positions, risk metrics, candidate
signal, backtest stats, macro signal and macro series - and **no fundamentals at
all**. The deep-dive reasoned about price, regime and macro while knowing
nothing whatever about the company, a regression from the original application
where earnings informed the recommendation.

`FundamentalsSource` already existed, was already cached, and already fed the
screener and several strategies. Nothing routed it to the advisory layer, so the
fix needed no new plumbing: both symbol-level call sites reach it through
`runtime.strategy_engine.fundamentals_source`, and the Workbench had already
fetched the snapshot to build the signal series it was asking the AI to comment
on.

**Two things carried deliberately.**

*Absent figures are omitted, not nulled.* A reader given `"roe": null` has to
know that means "the vendor does not publish it" rather than "it is zero"; a
reader given nothing at all cannot make that mistake. It is the reasoning behind
`missing()`, applied to a consumer that is a language model rather than a
strategy. Measured against the live vendor: JNJ answers 16 fields, CRWD 11 -
the unprofitable, non-dividend-paying one simply has less to say, and nothing
invents the difference.

*Synthetic figures announce themselves.* The app falls back to a seeded
synthetic source when no vendor is configured, and every number it produces is
invented but entirely plausible - exactly the input a model will reason
confidently from unless told otherwise. The prompt leads with the warning rather
than appending it, and `is_synthetic` is stripped from the figures themselves so
a provenance flag cannot read as a fundamental.

**Not behind the freeze**, and the reason is worth restating: the AI cannot
place, size or approve an order, so nothing it is told changes a trading
decision. Nothing here alters what the strategies see - they already had this
data.

### M41 - Earnings event risk  **[DONE, 7-8 August]**

Delivered in two halves. **M57** sizes an entry down to 50% within five trading
days of a scheduled print - "size down into an announcement", the middle of the
three options below. **M41 proper**, 8 August, is the first: the announcement
date known at entry now rides from the order through the fill onto the closed
trade, so the trial can measure what holding through one actually costs.

The date rather than the distance, deliberately. A distance measured at entry
against a holding period measured at exit only approximates the question; the
date answers it exactly. And it has to be captured as it happens for the same
reason the rest of M37 does - by the time a position closes, the calendar has
rolled to the following quarter, so the fact stops being recoverable the moment
the trade is opened.

Three states, kept as three across every boundary including the CSV: held
through, avoided, and unknown. An ETF has no earnings and an adopted position
was never sized against a calendar, and writing those as "avoided" would merge
them permanently with trades that genuinely dodged an event.

**The third option - flatten before the announcement - remains undone**, and is
a decision change rather than a diagnostic.

### M41 - Earnings event risk, as originally recorded

Fundamentals carry earnings data for screening, but nothing in the trading path
knows when a held position is about to report. With a 10-day minimum hold and a
30-day time stop, holding through an announcement is arithmetically
unavoidable - roughly once a quarter per position.

The gap budget does not cover it. That 6% shock was measured across 28,987
overnight holds, blending ordinary nights with earnings nights; earnings gaps of
15-20% are common and a stop does not help, because the price never trades
there.

Options, in increasing order of intervention: record the earnings date on each
trade so the trial can measure what holding through one actually costs; size
down into an announcement; flatten before it. The first is a diagnostic and
could arguably be done during the trial; the other two change decisions and
cannot.

### M42 - Partial fills are miscounted  **[DONE, 8 August]**

Fixed exactly as described below, and the description understated it: this is
the same failure that halted the 5 August session, on the one path M53 never
touched. M53 fixed fills replayed FROM the broker; this is orders the
application places itself. `place_order` wrote back the id, the status and the
fill price and left `quantity` at the requested size, so a buy for 100 that
filled 60 was tracked as 100 - a 40-share discrepancy, which reconciliation
answers with the kill-switch.

Guarded on being positive: an accepted-but-unfilled order reports `filled_qty`
of 0, and writing that back would read as "this position was closed" rather
than "it has not started".

**Nearly missed, and worth recording why.** The first tests were written at the
OMS, against a mock that already wrote the filled quantity back - so they passed
before the fix as well as after, proving the mock behaved while the real
adapter did not. That is the M56a mistake again: testing the layer being
reasoned about rather than the layer holding the defect. The test that mattered
sits at the adapter and failed with `assert 100 == 60.0`.

### M42 - Partial fills, as originally recorded

The Alpaca adapter builds requests from `order.quantity` and never writes the
broker's `filled_qty` back onto the order. `OMS.sign_off` then counts
`signed_qty = filled.quantity`, so a partially filled buy is recorded at its
full size while the broker holds less - which reconciliation reads as a
discrepancy and answers with the kill-switch.

Unlikely on liquid large-caps with market orders, and not unlikely forever. The
fix is small: read `filled_qty` in the adapter and let the OMS count what the
broker actually filled.

### M43 - Trading halts

No handling anywhere in the order path. The staleness rail stops a NEW trade
being sized against a stale quote, which covers entry. It says nothing about the
case that hurts: the position is held, the symbol is halted, the resting stop
cannot fill, and it reopens materially lower. Nothing detects the halt and
nothing flags that a position is currently unexitable.

**The flagging half is now built - see M60, 8 August.** A halted position needs
exactly what a split-affected one needs: to be in a state the ordinary path
refuses to treat as ordinary. What M43 still needs is its own producer - a halt
has no ratio to match, so detection is a different question from M39's - and
that is the whole remaining cost, which was the point of building the concept
once.

### M66 - Aggregate risk-at-stop is measured against ENTRY prices  **[FOUND 8 AUGUST, NOT YET FIXED]**

Found by independently recomputing the one number that is currently refusing
every new entry in the book.

**The application reports 5.02%. Measured against current prices it is 5.87%.**

```
basis                                 risk $     pct
current price (what is at risk NOW)  5,947.28   5.87%
avg entry price (the fallback)       5,078.77   5.02%   <- matches the app exactly
```

**The mechanism.** `PortfolioGovernor.snapshot` does
`price = prices.get(pos.symbol) or pos.avg_price`, and `avg_price` maps to the
broker's `avg_entry_price`. The `prices` argument is threaded all the way
through `snapshot`, `evaluate` and `delever_fraction` — and **nothing in the
trading path ever passes it.** `RiskEngine` calls `governor.evaluate(...)`
without it, and `DeleverSweep` calls `governor.snapshot(...)` without it. The
only caller that supplies prices is `adopted.py`, which is a display path.

So this is not a stood-down-session artefact. **Every entry decision and every
de-lever check has always been made against the prices the positions were
opened at.**

**Why the direction matters.** Risk per share is `price − stop`. A position that
has gained has further to fall to its stop, so **a winning book understates its
risk** and believes it has headroom it does not have; a losing book overstates
it and refuses trades it could take. The bias is backwards from prudent, and it
grows with profit.

Right now the book is at **5.87% against a 5.00% cap** while reporting 5.02% —
already 17% over the cap in reality, and only marginally over on paper.

**Same pattern as `shows_advanced()` before M63**: a parameter that exists, is
plumbed through every layer, and is supplied by nothing. *When something is
added, ask what reads it* — here, what *writes* it.

**Not fixed, and not to be deployed before Tuesday.** It changes which trades
are permitted and how large they are, so it is squarely inside the validation
freeze and needs a deliberate, recorded lift.

**Correction, same day.** This entry first said the fix was coupled to the
market-data decision and should wait for it. **That was wrong.** Alpaca's
`Position.current_price` is the CONSOLIDATED tape — measured against both feeds
for all ten held positions, 10 matched SIP and 0 matched IEX. So the price the
fix needs is already in every `positions()` response the app makes, is free on
this tier, and carries none of the IEX range bias. The fix is one extra fallback
tier in `snapshot`, plus an optional `current_price` on `Position`, and needs no
caller changes at all. Designed in
`docs/superpowers/specs/2026-08-08-risk-at-stop-current-prices-design.md`.

Checked rather than assumed: `QAT_DELEVER_SWEEP_ENABLED=false`, so the stricter
figure cannot force a sale. With the sweep enabled, a jump from 5.02% to 5.87%
would have trimmed all ten positions the moment it deployed.

### M65 - The entry record held the price we ASKED, not the price we PAID  **[FIXED 8 AUGUST]**

**Fixed by `SignalToOrderBridge.reconcile_entry_prices()`**, which runs at
startup *before* `restore_open_lots` - ordering is the whole point, since that
method passes `entry.price` as the lot's cost basis and a correction applied
afterwards would leave the ledger holding the number this removes.

It asks the **broker**, because the broker is the authority on what was paid
exactly as it is the authority on what is held. That heals the records already
on disk rather than only preventing new ones, which matters because eight wrong
ones are sitting there now.

Only the price moves. The stop is the level the risk budget was spent on and
re-arming reads it; the open date drives the churn rails.

**A quarantined position is never corrected.** A corporate action changes
`avg_entry_price` legitimately - a 2-for-1 split halves it - so "correcting" to
the post-event figure would silently rewrite the basis of exactly the position
M60 exists to stop anything touching.

A broker that cannot be read changes nothing: a wrong price is bad, and a price
overwritten from a failed read is worse.

**What this does NOT fix.** `_announce_fill` still publishes the reference price
at `transmitted`, so a lot created live inside a session still carries it until
the next startup reconciles. Closing the root cause means either not announcing
at `transmitted` - which risks losing the event entirely, since it is unproven
that an order reaches `filled` in-process - or re-announcing on the true fill.
Recorded rather than quietly left.

**Operational note: the first launch of a build containing this rewrites
`open_position_entries.json` for eight positions.** Back that file up first, as
`closed_trades.csv` was before the CVS correction.

### The finding, as originally recorded

Found while measuring realised slippage against the flat 5bps assumption, and
it is a bigger finding than the thing that was being measured.

**8 of the 10 open positions have a recorded entry price that differs from what
the broker actually charged.**

```
sym       recorded  broker paid   diff bps      stop    R err
AMD         503.16       510.27      141.3    405.55    +7.3%
GS         1049.25      1054.75       52.4    954.84    +5.8%
VRTX        487.20       487.99       16.2    456.27    +2.6%
AMAT        541.55       540.55      -18.5    445.04    -1.0%
```

**The mechanism.** `OMS._announce_fill` publishes when
`order.status in ("filled", "transmitted")` — *including transmitted* — and
takes `price = order.filled_price or order.reference_price`. At transmit there
is no fill price, so it publishes the REFERENCE. `SignalToOrderBridge._on_fill`
then records the entry with **`setdefault`**, so when the genuine fill arrives
the true price cannot replace it. Nothing else corrects it: an entry this app
transmitted is in `_broker_order_ids`, so `absorb_broker_fills` skips it by
design.

**What it corrupts.** `restore_open_lots` passes `entry.price` as the lot's cost
basis, so:

* realised P&L will be wrong by the drift on every one of these trades;
* the **R-multiple denominator** is wrong, because R is
  `(exit − entry) / (entry − stop)` — AMD's true risk per share is 7.3% larger
  than recorded;
* both feed the **promotion gate** and the September evidence burst.

The freeze's own list says *"a defect that corrupts the record is worse than one
that stops the session"*, and this is squarely that. It changes no trading
decision — sizing already happened on the reference price — so fixing it is
inside the freeze rather than against it.

**Why it was invisible.** CVS, the only closed trade, drifted 1.4 bps. Its P&L
is right by luck, so the one record that could have exposed this does not.

**The shape of a fix, not yet built.** Publish the entry record from the
*filled* price, which means either not announcing at `transmitted` or correcting
the record when the fill lands. `setdefault` is load-bearing for a different
reason — M53's partial exits — so it cannot simply become an assignment.
Existing records need correcting by hand, as the CVS ledger was.

**Adjacent, and separate: there is no drift check on a manually signed order.**
`autonomy/gate.py` refuses an autonomous order that has drifted past
`autonomous_price_drift_limit_pct` from what it was sized against. Nothing
applies that to a hand-signed one. AMD was signed off in a batch 31 minutes
after the open, by which time it had moved 1.4% from the price the risk engine
sized it on.

### M44 - Execution quality

Every order is a market order - `Order.order_type` is only `market` or `stop`,
and there is no limit-order path. Slippage is modelled at a flat 5bps
regardless of size, time of day or spread, and market orders in the opening
minutes are exactly where that assumption is weakest.

M37's `entry_slippage` column measures the gap between assumed and realised on
every closed trade, so the trial itself will say how wrong the assumption is
before anything is changed. That measurement should come first.

## M31b - What the first trading session found  **[COMPLETE]**

The session of 31 July filled **six positions** - CSCO 44, UNP 17, WFC 58,
CRWD 16, JNJ 19, CVS 47 - all whole shares, no broker refusals, through every
rail. The first real trades this system has ever made. It also exposed six
defects, listed here in the order they must be fixed.

**1. Bracket legs expired at the close. [DONE]** Orders were submitted
`TimeInForce.DAY`, so at 20:00 the take-profit legs EXPIRED and Alpaca
cancelled the paired stops with them, as OCO does. Six positions worth about
$36,000 sat through a three-day weekend with no protection at the broker at
all. A stop whose purpose is to outlive the application must outlive the
session: bracketed entries are now GTC. Plain orders stay DAY, so an unfilled
market order does not linger into the next session at a price nobody chose.

**2. Nothing reconciles stops against the broker. [DONE]** `OMS._position_stops` still
holds stops the app believes are resting at Alpaca, and the governor computes
risk-at-stop from them - so after the expiry above it thinks the book is safer
than it is. Reconciliation compares FILLED QUANTITIES only, which is why it
caught nothing. This is the same failure as the phantom `transmitted` status on
30 July: app-side belief and broker reality diverged with nothing watching.

**3. A transiently-blocked order is never re-examined. [DONE]** The autonomous
executor evaluates each order once, on `OrderPendingSignoffEvent`. An order
refused for `Opening Volatility` or `Midday Lull` - reasons that expire in
minutes - is treated exactly like one refused for a permanent reason, and the
symbol stays suppressed because the bridge skips anything in
`pending_signoff_symbols()`. It cost three manual reject cycles on 30 July and
one position (PANW, 10 shares, blocked 15:39 in the Midday Lull) on the 31st.

**4. Entry times are not persisted. [DONE]** `SignalToOrderBridge._entries` is built
only from live fill events, so a restart leaves open positions with no known
entry date - and the minimum hold and time stop both treat an unknown entry as
"never applies". A restart silently disarms the churn rails on everything
already held.

**5. The blotter shows no prices. [DONE]** Columns are Order ID, Symbol, Side,
Quantity, Status, Created At. No reference price, stop, target or strategy - on
the screen whose entire purpose is informed human sign-off. Deciding whether to
approve a stale order on 30 July required reconstructing all of it from the
decision journal plus a live quote.

**6. Repeated identical refusals flood the journal. [DONE]** SPY was refused by the
cost rail 249 times in one session, once a minute, every minute - 249 of 262
journal rows. The refusal is correct; logging it 249 times buries every real
event. Suppressed per symbol: an identical outcome-and-reason pair is written once,
and any change either way is always written, so the journal still shows when a
refusal started and when it stopped.

**All six landed 1 August.** `OMS.verify_position_stops` now asks the broker
which stops are actually working and drops any it cannot find, so an
unprotected position falls back to counting its full value at risk rather than
looking safe. Entry dates are written to `open_position_entries.json` on every
fill, so a restart no longer disarms the churn rails.

A broker that cannot answer `resting_stops` changes nothing: an adapter without
the capability must not be read as "no stops rest anywhere", which would drop
every stop the app holds.

## M31d - A restart forgot what was protecting the book

`OMS._position_stops` is in-memory and starts empty, so every launch
re-adopted its own positions as unprotected. The governor counts a position
with no known stop at its full value, which is the conservative rule and the
right one - but applied to six holdings worth $27.9k on $100.8k equity it
reads as 27.7% risk-at-stop against a 5% cap, and rejects every new buy before
sizing runs.

It also blinded `verify_position_stops`, the M31b rail that catches a stop
that has quietly stopped existing: it iterates `_position_stops`, so after a
restart it had nothing to check - precisely when an overnight bracket expiry
is most likely to have happened.

Adoption now asks the broker. `resting_stops()` already existed and was used
only to verify; it is the account, and the account is the only thing that
actually knows. A position with no resting stop is still absent from the
record, so the conservative rule is unchanged - it is now reached by evidence
rather than by assumption, and the naked ones get named at ERROR instead of
being averaged into one warning about all of them.

**What it found on 1 August.** All six. Every entry from 31 July shows the
same three rows at Alpaca: market buy filled, limit sell expired, stop sell
canceled. The brackets were submitted DAY, and the take-profit leg expiring at
the close took the paired stop with it - the exact failure M31b diagnosed,
now caught in the act. The GTC fix shipped in M31a protects new entries and
cannot resurrect these.

**Re-arming. [DONE]** Every stop this system ever placed rode in as a bracket
leg on an entry, so a position whose legs died had no way to get another one.
`OMS.submit_protective_stop` places a standalone GTC stop on a position
already held, and `SignalToOrderBridge.rearm_protective_stops` proposes one at
startup for each held position the broker is not protecting.

The level comes from the recorded entry stop, not from an ATR recomputed now:
the risk budget was spent on the distance the position was SIZED against, so
protecting it at any other distance protects an amount nobody approved. A
position with no recorded entry stop gets nothing and is logged - an invented
level would look identical to a real one on every screen in the app.

Two ways this order could have made things worse than the exposure it repairs,
both guarded: submitted as a market sell it liquidates the position, and
counted as a fill it halves the tracked quantity against a broker still
holding all of it - which reconciliation reads as a discrepancy and answers by
tripping the kill-switch, on the very order sent to make the book safer.

They are proposed, not transmitted. Reducing risk is an argument for letting
an order through unattended and not an argument for bypassing the gate: a stop
still sells shares when it is reached.

## M33b - Re-arming restored half the protection

The M31d re-arm put the stops back and not the targets, because the entry
record was the one place a target was never written down. Six positions came
back with downside protection and no way to bank a gain: the only exits left
were a stop-out or the 30-day time stop.

`_Entry` now keeps `target_price`, `OrderFilledEvent` carries it, and the
re-arm proposes both levels. Files written before this lack the key and are
read with `.get` - a restart that discarded its entry dates over a missing
target would disarm the churn rails in order to add one.

**Sent as ONE OCO, never two orders.** A resting stop and a resting limit for
the same shares are not independent: if the price runs to the target and later
gaps back through the stop, both fill, and the account sells twice what it
holds - turning a protected long into an accidental short. OCO is what makes
the pair mutually exclusive at the broker, which is exactly the property the
bracket had before its legs expired.

**The six already held cannot be repaired from the app's own records.** Their
targets were never persisted. The levels are still visible in Alpaca's order
history as the expired limit sells; restoring them means writing those numbers
into `open_position_entries.json` by hand.

## M33c - The self-healing rail could not heal anything after hours

Found by running M33b rather than by reading it. On 1 August the app detected
CRWD unprotected, proposed the OCO repair, and then **blocked itself from
applying it** because the US market was closed - while a manual sign-off of
that same order was accepted by Alpaca without complaint, because GTC orders
rest fine outside hours.

The rail was dormant in precisely the window it exists for. Brackets die AT
the close; that is how all six positions lost their stops on 31 July.
Unattended, the repair would have sat in the blotter until Monday with the
positions bare across the whole weekend.

`AutonomyGate` now lets a resting protective order past the session check.
Deliberately narrower than "any sell": a market sell transmitted into a closed
market is an unpriced fill at the open and stays blocked, where a stop or OCO
placed GTC executes nothing until its level trades, so placing it early costs
nothing and is the entire point. The kill-switch, recommend mode and the live
account rule all still outrank it - the exemption is about the session, not
about the hard stops.

**The OCO shape was confirmed against the real API**, first attempt, no
refusal. That was the one piece of M33b that had only ever been tested against
a fake client.

Also: the "protective stop resting" log line printed only the stop, so it
could not distinguish an OCO whose target leg rested from one the broker
accepted and flattened. It now names both levels - it is the audit trail for
exactly that question.

## M33d - The detection query did not understand its own new order shape

M33b taught the app to place an OCO. Nothing taught `resting_stops` to read
one. An OCO's stop leg sits at status `held` while its partner is live, and is
returned as a CHILD of the parent order rather than as a top-level row, so a
flat scan of open stop orders saw nothing.

On 1 August the app read a CRWD position carrying a perfectly good OCO as
unprotected and proposed a second one. Signed, that is 32 shares of resting
sell orders against a 16-share position - the double-sell hazard the OCO
itself was introduced to prevent, arriving instead as two orders a restart
apart.

**Only the autonomy gate stopped it.** `Autonomy blocked order (sell CRWD): US
market is closed` was the sole reason it did not self-sign. M33c had just
removed exactly that block for protective orders, on the correct reasoning
that a GTC order rests fine outside hours. The rail being removed was the one
catching the other bug, and M33c was never deployed because of it.

The five plain stops all read back correctly throughout, which is why every
check before this passed. It took the new order shape to expose that the query
had never understood it.

Two fixes, because one of them is about the specific miss and the other is
about the class:

* `resting_stops` asks for nested orders and walks the legs, and tests on the
  presence of a stop PRICE rather than an order-type string - an OCO leg
  reports its type inconsistently, where "carries a stop level and would sell"
  is the property that makes it protection.
* `submit_protective_stop` refuses to propose a second protective order for a
  symbol that already has one pending, and returns the existing one. "The
  broker says nothing is resting" was never safe to act on unilaterally, so
  the count is enforced where the order is created as well as measured where
  it is detected.

## M47 - The detection query was bounded on the wrong axis

M33d taught `resting_stops` to read nested legs and to accept `held`. That
fixed the standalone OCO and left the bracket case untouched, because no
bracketed entry had filled yet. On 4 August four did. `status=open` excludes a
filled parent and takes its still-`held` stop legs out of the result with it,
so four protected positions read as unprotected, and the app proposed four
duplicate OCOs at levels identical to the stops already resting - GS 954.84,
MS 196.93. Alpaca refused them for insufficient shares, once every five
minutes, 412 times before the operator's morning.

**The bug and the obvious cure were the same mistake.** `status=open` bounds on
LIFECYCLE and is wrong because a live leg can hang off a dead parent. Bounding
by DATE instead is the same error in new clothes: a leg belonging to a February
entry is still live today, and an adopted position has no recorded age at all,
so every constant is a bet on holding period that the app cannot honour.

The axis that decides relevance is which symbols are actually held, because
that is the only question the method exists to answer. Symbol membership does
not age. Measured against the live account on 5 August:

| Query | Rows | Positions resolved |
|---|---|---|
| `status=open, nested=true` | 11 | 6 of 10 |
| `status=all, nested=true` | 220 | 10 of 10 |
| `status=all, nested=true, symbols=<held>` | **49** | **10 of 10** |

Three things fell out of the measurement that reasoning would not have given:

* Every held position's live leg was the MOST RECENT order for its symbol, and
  no held symbol had more than ten orders in its entire history.
* `limit` counts RAW orders, not the nested parents returned - `limit=100`
  yielded 49 parents and `limit=50` yielded 23. A page can therefore truncate
  without the row count looking short.
* `after=` filters on `submitted_at`, not on fill time. That belongs to M48.

So the scan is bounded by symbol, ordered newest-first, and a symbol the broad
scan cannot resolve is looked up on its own - paged backwards, capped - before
it is allowed to read as unprotected. "No protection found" now always means we
went and looked, rather than that the page ran out. The healthy case costs one
order query; the deep scan never runs.

**The second half matters as much as the first.** Under `status=all` the
overwhelming majority of what returns is dead - 207 filled and 23 cancelled or
expired against 22 live - so each leg is now filtered on its OWN status against
an allowlist of live states. Without that the fix would trade a false
"unprotected" for a false "protected", and that is the strictly worse
direction: a duplicate order is caught by the M33d guard and by the broker,
where a position believed protected is simply never repaired.

**What the defect cost beyond noise.** The four positions counted their full
value against the aggregate risk-at-stop cap, holding it at 33.66% against a 5%
limit for the entire session. No new entry could have been sized or approved
for eight and a half hours. A detection bug had become a trading halt.

## M31c - The Performance tab showed the launch, not the present

Three observations on 1 August - the Closed Trades table empty, no daily report
for Friday, the weekly report apparently never run - turned out to be one
display bug and two correct behaviours.

`PerformanceScreen.refresh()` was called at construction and by the Refresh
button, and nowhere else. A session started at 00:18 still displayed 00:18's
figures at 06:04: Friday's daily report was on disk and absent from the screen,
and the promotion table, metrics and closed-trades list were all equally stale.
During a live session that means watching a promotion table frozen at launch.

It now re-reads on `showEvent` and polls once a minute while it is the visible
tab, stopping in `hideEvent`.

**The other two were not bugs.** Closed Trades is empty because nothing has
closed - six positions opened 31 July against a ten-trading-day minimum hold.
And the weekly report *did* run: `last_weekly` records the week's MONDAY, so
`2026-07-27` is Friday 31 July's week, and `weekly_reports.md` contains "Week
of 27 Jul 2026 to 31 Jul 2026". Reading that field as a week-end date is what
made a working scheduler look broken.

**Open-position activity in reports. [DONE]** A daily report on a day with six
entries and no exits read identically to a day when nothing happened, because
every metric is built from closed trades. Reports now carry `opened` and `held`
from the ledger's open lots, so Friday reads "Opened 6 position(s), $27,783.86
committed" with each entry listed, and "Still held 6 position(s)". A genuinely
quiet day still reads as quiet.

## M38 - The first live session traded nothing, and said nothing

3 August, the first session of the validation phase. 1,438 signals, 1,413
exceptions, zero orders, zero refusals, zero journal entries. The Dashboard was
indistinguishable from a day on which no strategy found a setup.

Every signal died at the same place:

    signal_bridge._on_signal -> _submit_entry -> _submit_sized
      -> oms.submit_order -> risk_engine.evaluate_order
      -> portfolio_risk.check -> _combined_portfolio_returns
    ValueError: cannot reindex on an axis with duplicate labels

That is the M33 path. `_combined_portfolio_returns` builds a DataFrame from the
per-symbol return series, which pandas does by reindexing each onto the union
of their indexes - and reindexing FROM an index with duplicate labels raises.
Before M33 `existing_returns` was an empty dict, so the function only ever
received one series and the condition could not arise. Handing it real history
made it reachable.

**Root cause of the duplicate is still unidentified.** Four reproductions
against live Alpaca data - seeding alone, seeding plus a session of live ticks,
all six held symbols, and the exact PortfolioRiskChecker call - all pass with
unique indexes. Whatever produces the duplicate happens in a live session and
has not been reconstructed offline. The fixes are therefore defensive at both
ends rather than corrective at the source, and the warning now names the symbol
so the next occurrence identifies itself.

**The second defect is the one that cost the day.** An exception inside the
risk pipeline propagated out through the event bus, which logged "EventBus
handler failed" and continued. A rail that REFUSES is visible, auditable and
appears in the blotter with a reason; a rail that THROWS is none of those.
`submit_order` now converts any unexpected failure into a rejected order
carrying the exception type and message, which is what it already did for every
other failure mode.

Three fixes: refuse rather than raise at the OMS boundary; drop duplicate
timestamps in `_combined_portfolio_returns` and name the symbol; drop them at
the source in `_returns_by_ts`. Six tests, five confirmed failing against the
previous code.

Worth stating plainly: this was introduced by M33 on 1 August, shipped through
five subsequent builds, and was caught by neither 1,219 tests nor two external
reviews. Only a live session found it.

## M35 - Sizing on what happened, not on two invented numbers

`SignalToOrderBridge` passed `win_rate=0.55` and `win_loss_ratio=1.5` into
Kelly sizing as fixed constants, described in its own docstring as "clearly
documented placeholders, not real edge estimates". Every position size this
system has ever taken traced back to those two figures.

`EdgeEstimator` measures each strategy on its own closed trades and feeds that
into the sizer. This is the learning loop: what a strategy achieved decides
what its next trade risks.

**The care is all in when NOT to switch.** Kelly is violently sensitive to win
rate - at a 1.5 win/loss ratio, moving from 0.55 to 0.75 roughly triples the
fraction - so a strategy that opened with four winners would size up hard on
noise. It stays on the defaults until `edge_min_trades` (20, against the 5
that `MIN_TRADES_FOR_STATS` allows for *display* - showing a statistic early
is harmless, risking money on it is not), and even then:

* win rate is clamped to 0.25-0.75, outside which a small sample is far
  likelier than a real edge;
* win/loss ratio is clamped to 0.5-4.0, because 50:1 over twenty trades is one
  outsized winner rather than a payoff profile;
* a book with no losing trade falls back rather than dividing by zero - that
  is a sample too kind to learn from, not a ratio.

The switch is logged once per strategy, at WARNING, because it changes every
position size from that point on.

Ordering matters: `TradeLedger` is now constructed before the bridge, since
sizing reads from it.

**Blocked behind M34.** The ledger records a closed trade only when
`OrderFilledEvent` fires, and every exit this system has comes from a stop, a
target or the time stop - two of which execute at the broker. Until M34
absorbed those, no closed trade existed to learn from, so this would have
measured an empty book forever.

## M34 - A protective order firing looked like a discrepancy

Every closed trade this system will ever produce comes from a stop, a target,
or the time stop, and two of those three execute entirely at the broker. No
order leaves this process, so nothing publishes `OrderFilledEvent` - it is
raised in exactly one place, `OMS.sign_off`, which only ever runs for orders
this app transmitted.

Two consequences, and both would have bitten on the first day a stop fired:

* `check_reconciliation` compares tracked quantity against the broker's and
  trips the kill-switch on any divergence. A stop doing exactly its job read
  as `tracked=58 broker=0` and would have halted the session.
* The trade ledger subscribes to that same event, so the closed trade was
  never recorded. The Performance tab stays empty and the promotion gate
  accumulates nothing from the only exits this system has - which is Stage 3,
  the three months of evidence the whole plan rests on, never starting.

Newly urgent because M33b-e armed twelve protective legs across six positions.
Before this weekend there was nothing resting to fire.

`OMS.absorb_broker_fills` runs BEFORE anything is judged: it asks the broker
for executions since the last scan, applies any this app did not originate,
and publishes `OrderFilledEvent` so the ledger records a genuine closed trade.
Reconciliation then compares a book that already knows what happened.

The real fill price is fetched rather than assumed. A stop fills at or below
its trigger and a target at or above its limit, so using the level as a proxy
would put a wrong number into every realised P&L the promotion gate reads.

A genuine discrepancy still trips - a position appearing with no fill to
explain it is exactly what the rail is for - and a broker that cannot report
fills behaves precisely as before.

Never observed, unlike the M33 series: this is a code path read rather than a
failure watched. Six tests, all confirmed failing against the old
reconciliation.

## M33e - Both known gaps closed

**Repair now runs on a timer.** `SignalToOrderBridge` sweeps every
`protection_sweep_seconds` (default 300) and re-arms anything the broker is no
longer protecting. Detection was already continuous; repair only ever ran at
startup, so every fix watched on 1 August needed a human to close and reopen
the app. A stop that vanishes at 14:00 is not less urgent than one found at
launch - it is more so, because nobody is about to restart anything. The M33d
duplicate guard is what makes a repeating sweep safe: a symbol with a proposal
already pending gets that one back rather than another.

**The banner distinguishes a restart from a surprise.** "Adopted" had meant two
different things in the same words - a holding someone else put in the account,
and this app's own position seen again after a restart - and the second is the
normal case now. `Runtime.opened_position_symbols()` reads the persisted entry
record, so six positions swing opened yesterday read as "resumed after restart
- opened by this app" rather than "this application did not choose them". A
genuinely foreign holding still reads exactly as before, which is the whole
point: the warning has to stay meaningful for the case it was built for.

## Superseded - the gaps as originally recorded

**Repair is startup-only.** `rearm_protective_stops()` is called from
`SignalToOrderBridge.start()` and nowhere else. Detection is continuous -
`verify_position_stops()` runs on the reconciliation poll and will notice a
stop that has vanished mid-session - but nothing re-arms until the next
launch. For a session left running across days, a bracket that dies at a close
stays dead until someone restarts the app. The obvious shape is a periodic
sweep on the same poll that already detects it, with the same market-closed
reasoning M33c established.

**The adopted-positions banner misdescribes a restart.** It reads "6 positions
not opened by this app ... this application did not choose them", which is
false: swing opened all six on 31 July. What is true is that it did not open
them *in this session*. The banner is styled as a warning, so firing it on
every restart for the app's own positions trains the operator to ignore the
case it exists for - a genuinely foreign holding.

The data to tell them apart is already loaded on both sides:
`open_position_entries.json` records exactly which positions this app opened
and when. Adoption should say "re-adopted after restart - opened by this app
on <date>" for those, and keep the current wording only for symbols absent
from that file.

## The stack

Ordered on one principle: **make the measurement honest before making the
strategy better.** Everything downstream inherits a measurement error.

### M27a - Run the live path on daily bars  **[DECIDED]**

The largest finding so far, and it outranks the cost work: **no strategy in this
system has yet been evaluated on the data it was designed for.** Every session to
date has tested plumbing, not strategy.

**Evidence, 28 July.** The infrastructure ran perfectly - 13:37:59 to 20:03:09,
one process, no restarts, no kill-switch trips, no feed failures - and produced
zero signals. The regime engine crashed twice while trying to fit:

```
ValueError: startprob_ must sum to 1 (got nan)
ValueError: transmat_ rows must sum to 1 (got row sums of [1. 1. 1. 0.])
```

with 84 warnings that states were never visited. No `RegimeEvent` was ever
published all session.

**Mechanical cause.** `RegimeFeatureBuilder` has six columns: log returns,
realised vol, VIX, yield-curve slope, credit spread. The last three come from
FRED and update *daily*. Fitting on 60 one-minute bars leaves them **constant
across every row**, which makes the covariance matrix singular - hence the NaN.

**Real cause, and the fourth instance of one pattern.** `min_fit_bars = 60` is a
sensible window in *daily* bars (~3 months, over which VIX and credit spreads
genuinely move). It is being fed 60 one-minute bars - **one hour of market**. A
correct mechanism wired to the wrong input, exactly as with `BRK-B`, the
staleness rail, and the trade-timestamp clock.

The same mismatch applies to the strategies themselves. `bar_interval_seconds =
60`, so swing's EMA20/EMA50 are **20 and 50 minutes**, not days. A strategy
intended to hold for two weeks is deciding on a one-hour lookback. Its silence
may be the correct response to a timeframe it was never designed for.

**Two sessions, two different causes, same outcome - corrected 30 July.** My
first reading of 29 July was wrong and is worth recording so the next session
does not inherit it. The regime engine did **not** fail silently that night; it
fitted cleanly and published `low_vol`.

| | 28 July | 29 July |
|---|---|---|
| Regime engine | crashed (NaN), published nothing | fitted, published `low_vol (scalar=1.00)` |
| StrategyEngine regime | fell back to the `SIDEWAYS` default | took `LOW_VOL` |
| Swing | **eligible**, found no setup | **gated off entirely** |

`SwingStrategy.suitable_regimes()` returns `{Regime.SIDEWAYS}`, and
`strategies/engine.py:174` skips any strategy whose set excludes the current
regime. So on the 29th swing could not have produced a signal whatever prices
did. The zero-trade result was the gate, not the timeframe.

**Which makes the macro finding the urgent half, not the secondary one.** The
regime gate works, and works with real teeth - which is good design and exactly
why feeding it noise matters. On 29 July a random number generator switched the
only promoted strategy off for a full session, and the system reported that as
normal operation. `scalar=1.00`, so it did not even reduce exposure; it just
made swing quietly ineligible. This is the scenario recorded below as the
dangerous one, now observed. The 28th's crash was the lucky version.

**Revised order of work inside M27a.** Daily bars govern how well swing sees the
market; real macro data governs whether swing is allowed to look at all. Items 1
and 2 are small and can land before the rest - swing may start trading without
the whole milestone:

1. ~~`resolve_macro_source()` - real FRED when the key is present, mock otherwise
   **with a loud warning**, matching `resolve_broker`.~~ **Done, 30 July.**
   Two things had to come with it: `MacroFeed` published one `MacroEvent` per
   *observation*, which the mock's single-observation response hid and which
   against real FRED would have put 57,878 events on the bus every hour; and
   its poll loop had no error handling, so one network failure would have
   killed the task silently and frozen every macro feature for the session.
2. ~~**Give `regime_engine/engine.py` a logger.**~~ **Done, 30 July.**
   Classifications, transitions, warm-up progress, refits, and fit failures
   with the per-feature numbers that explain them.
3. ~~Daily-bar warm-start seeding (below).~~ **Done, 30 July**, together with
   the daily cadence, which could not be split from it: seeded daily bars with
   a 60s interval would be replaced by minute bars through the session, warm at
   the open and wrong by lunch. Three things the plan below did not anticipate:
   per-symbol fetching would have blocked startup for over two minutes (one
   bulk request does it in 3.2s); the regime engine appended a feature row per
   *tick*, which would have swamped 300 seeded rows within one session; and
   gap filling would have invented flat bars for weekends.
4. ~~Persistence and dead-classifier visibility.~~ **Done, 30 July.**
   `RegimeHealthEvent` and a REGIME ENGINE DOWN banner, ranked below the halt
   and the feed outage; `StrategyEngine` names every strategy and its
   eligibility the first time it gates on the default instead of a classified
   regime. **Persistence was deliberately not built** - the warm start already
   re-seeds every symbol from the authoritative source in seconds, and a local
   copy that can disagree with the vendor is maintenance cost for no benefit.
   The one real gap it would have closed, a mid-session restart losing the
   day's open/high/low, is fixed by loading the vendor's partial bar for today
   as the *forming* bar rather than discarding it.

**M27a is complete.** Verified against the live account: 101 symbols and 300
daily bars seeded in 7-17s, every macro column varying across the matrix, the
HMM classifying on the first live bar, and swing eligible.

**Swing's regime gate, widened 30 July by operator decision.** Measured over
the 300 real sessions to 29 July: bull 32.0%, bear 26.6%, high-vol 24.9%,
low-vol 10.4%, **sideways 6.2%**. The paper names Sideways alone for Swing, so
the only promoted strategy was eligible about one session in sixteen and the
zero-signal sessions were the ordinary case, not an anomaly. Now Sideways,
Bull, Low-Vol and Recovery; Bear, High-Vol and Recession stay excluded.

### Session of 30 July - M27a ran perfectly and still did not trade

The machinery did everything it was built to do. 101 symbols and 300 daily
bars seeded in **3 seconds**; the regime classified at **23:30:04**, four
seconds after the open, against three months cold; session control opened and
closed on the minute; **zero errors** all night; REGIME ENGINE DOWN never
fired. The M27b flapping fear did not materialise - one classification, stable
all session. Note that with daily bars `refit_interval_bars = 20` now means
every 20 *days*, so the model refits roughly monthly.

And the account did not trade, for the third session running and a third
distinct reason. Two candidates, which **the record could not distinguish** -
which is itself the defect:

1. The regime came out `high_vol`, one of the three deliberately excluded from
   Swing. At the measured frequencies that is ~25% of days; with bear, Swing is
   gated off about half the time even after the widening.
2. **The deployed strategy set is not persisted and was never logged.** It
   starts empty at every launch (spec §K) and only a manual Workbench click
   fills it. If nothing was deployed, no strategy was evaluated at all and the
   regime is irrelevant.

**Fixed 31 July:** the engine names its deployed set at startup and warns when
it is empty, deployment and undeployment are logged through `deploy()` /
`undeploy()` rather than a bare `.append()`, and the banner reads **NO STRATEGY
DEPLOYED** instead of AUTO-TRADE ACTIVE - which is what it claimed all night
while nothing could trade.

**Still open: should the deployed set survive a restart?** It changes
behaviour, so it is a decision rather than a fix. Today an unattended session
inherits nothing from the last one.

### M27b - Gate on probability mass, not the argmax label  **[DONE, 31 July]**

The gate read the single winning label. On 30 July that label was `high_vol` at
0.31 against `bull` at 0.29, so a **0.02 difference decided whether the only
promoted strategy traded at all**, while 0.49 of the distribution sat in
regimes where it was eligible. Collapsing a distribution to its argmax and then
testing set membership throws away the confidence the model already computed.

A strategy now trades when at least `regime_eligibility_mass` (default 0.5) of
the distribution lies inside its suitable regimes.

**Measured over the same 300 sessions, this changes very little in aggregate,
and that is the honest headline:**

| | argmax | mass >= 50% | net |
|---|---|---|---|
| swing | 57.3% | 58.1% | +2 days |
| trend-following | 42.7% | 41.9% | -2 days |

The top-two margin is under 5 points on only **6.2%** of sessions - the
hysteresis-smoothed label is usually a confident call. So this is a correctness
fix for the coin-flip case, not a way to trade more, and it moves in both
directions: swing gains days, trend-following loses them. 30 July happened to
land in that 6%.

A property worth naming: with seven regimes and a *flat* distribution, a
four-regime strategy sits at 0.57 and trades while a one-regime strategy sits
at 0.14 and does not. When the model knows nothing, breadth of mandate decides
rather than an arbitrary argmax. That is the intended direction.

**Still open from the original M27b:** the label remains unstable across
refits - three replays of the same 300 days produced three different current
labels, differing only in refit timing. Mass gating reduces the blast radius
(a near-tie no longer flips a gate) but does not address the cause. Candidates
remain: fix the HMM's random state across refits, refit on a calendar schedule
rather than a bar count, or hold the fitted model and re-estimate only the
posterior. With daily bars a refit now happens roughly monthly, so this is a
slow-burning problem rather than an intraday one.

### M28a - The staleness rail  **[DONE, 31 July]**

Not a tuning problem. The rail had never once fired correctly - every trip it
produced was a false positive, and it was only ever masked by the feed being
broken in other ways:

| Trip | Symbol | Reported age | Reality |
|---|---|---|---|
| 27 Jul | (feed dead) | - | never fired; per-symbol staleness skips symbols that have not ticked |
| 28 Jul 13:30 | BRK.B | 63,017s | thin on IEX, last print was the previous close |
| 28 Jul 13:35 | HON | 97s | liquid; the poll interval itself |

It read `_last_seen`, the TRADE's timestamp, so it measured how old the last
print was rather than whether the feed was delivering. With a 60s poll against
a 60s threshold the measured age lands between 60 and 120 seconds through
entirely normal operation, on any symbol. A trip was arithmetic, not risk.

The two ideas it conflated are now separate:

* **Feed liveness** - measured on *receive* time, reported by
  `MarketDataFeedEvent`, shown as MARKET DATA DOWN. Still deliberately not a
  kill-switch trip: no ticks means no signals, so the danger is that nobody
  notices, not that it trades wrongly.
* **Quote freshness** - measured on the *trade's own* timestamp, reported by
  `DataStaleEvent`, and it now excludes that ONE symbol from signal generation.
  It cannot halt the account. `KillSwitch.check_staleness` is gone and
  `KillSwitchEngine` no longer subscribes to the event.

`DataStaleEvent` gained a `stale` flag so a symbol that prints again is let back
in rather than lost for the session, and it publishes on the *transitions* only.
A stale symbol still has its bars recorded, so its buffer is continuous when it
returns.

Default 60s -> **900s**, which is what the measurement now means: a megacap
prints continuously, a thin or halted one legitimately does not, and sizing
against an hour-old print is the hazard worth naming.

**Operator action:** `QAT_DATA_STALENESS_SECONDS=250000` can come out of the
`.env`. It suppressed a rail that halted sessions; the rail no longer halts
anything, and leaving the override disables the per-symbol exclusion that
replaced it.

### M28 - Cost-truthful measurement  **[DONE, 31 July]**

Fees on `ClosedTrade`, gross and net both retained; cost drag in the Metrics tab
and reports. Expectancy, average R, profit factor and the promotion gate are all
net.

`pnl` was removed rather than redefined, so every call site had to say which it
meant. Costs are apportioned from the *fill*, because the commission floor is
charged once per order - a position closed in three pieces pays one entry
commission, not three.

Two things the plan did not anticipate. A trade stopped at exactly its stop
loses **more than 1R**, since the 1R of price movement is joined by the cost of
having been in the trade; anything sized on "a stop costs 1R" understates every
loss. And the backtester had the same defect in reverse - costs deducted from
equity but gross P&L recorded per trade, so one backtest reported a net CAGR
beside a gross profit factor. Both sides now agree.

Measured at the shipped defaults on a 2% gain: a $20,000 position keeps 0.36R
of a 0.40R gross move, a $2,000 position keeps 0.25R. Against a 0.2R promotion
floor that gap decides whether a strategy qualifies.

**This unblocks M29**, which reads exactly these numbers.

### M29 - Governance consistency  **[DONE, 31 July]**

The policy said "earn autonomy" and the code granted it anyway. Resolved by
binding enforcement to what is actually at stake instead of to a flag someone
has to remember: `promotion_evidence_enforced` is true on **any live account**,
whatever `enforce_promotion_evidence` says.

The external review recommended turning the flag on immediately. That would
have been circular: the bar is 30 closed trades, paper is where those trades
come from, and enforcing it there means nothing trades, so no evidence is
produced, so the bar is never met. Paper collects the evidence; live requires
it. An operator can opt in early on paper; nobody can opt out on live.

This depended on M28 - before it the gate would have enforced a bar computed on
gross figures already known to be optimistic.

**Sequencing note.** An external review recommended enabling this immediately.
Doing so during the paper phase would halt data collection - swing has zero
closed trades against a 30-trade bar, so nothing would trade unattended. Correct
before live money, self-defeating during a paper test. And it must follow M28:
the gate reads expectancy and average R, which are gross today, so enforcing it
first would gate on numbers already known to be wrong.

### M30 - Gap risk as its own concept  **[DONE, 31 July]**

Every risk figure meant *"if the stop fills"*. Measured across 28,987
overnight holds on this universe, **45 (0.16%) gapped through a 2.5x ATR
stop** - the worst costing 2.0R instead of 1R on a -22.1% gap. Real, but
milder than the 6R this section originally assumed.

**Gap risk has its own budget in the governor.** A modelled 6% overnight shock
(just above the 99th percentile of measured moves) applied to *notional*, must
cost no more than 5% of equity across everything held. That implies a
gross-exposure ceiling of about 83%, and it is a different hazard from the
risk-at-stop cap rather than a variant of it.

**Single-name concentration 25% -> 15%, and it now TRIMS rather than refuses.**
That order matters. `PortfolioRiskChecker` returns pass/fail, and 1% risk over
a ~5% stop already sizes swing at about 20% of equity - so lowering the cap
under reject semantics would have refused every swing trade outright rather
than making it smaller. The mechanism had to change before the number could.
Trimming is the established pattern here; the aggregate risk cap has always
worked that way.

**Two defects this exposed:**

* The governor ran only when a caller supplied `positions`, so with an empty
  book the concentration cap fell through to the reject-style checker - the
  first trade of the day was refused instead of sized down. It now runs for
  every buy.
* `PortfolioRiskChecker` could **block a sell**. Lowering the cap to 15% meant
  a 20% position could no longer be exited, because the check ran on the
  resulting concentration and refused it. A rail whose effect is "the account
  may not de-risk" is a broken rail, and this one had been able to do that
  since it was written.

**Sector 40% -> 30%. [DONE]** Held back at first, deliberately: sector was
enforced only in `PortfolioRiskChecker`, which holds the sector map and has no
way to trim, so lowering the number before it could trim would have
reintroduced exactly the refuse-everything failure single-name just had.

`PortfolioGovernor.evaluate` now takes `candidate_sector` and
`sector_by_symbol` and trims against the sector the same way it trims a single
name, counting held positions **and** pending buys - an unfilled order is
committed exposure, and a cap that only sees fills approves a third name while
the second sits in the blotter. It runs before the checker, so the checker
sees the already-trimmed exposure and remains a backstop with no cause to
fire. A candidate with no sector in the instrument map is not gated.

Only then does 30% mean anything: at a 15% single-name cap, 40% never bound
until the third position in a sector was already on. 30% bites at
two-and-a-bit, which is the point - sector is the correlation that survives
having picked different tickers, and it is the one that shows up precisely
when the names stop looking different.

### M31 - Churn control  **[DONE, 31 July]**

`enforce_min_holding_period` and `min_holding_trading_days` had been settings
since M27 and were **read by nothing at all** - the same dead-configuration
pattern as the M13 equity rails and M6 reconciliation before them.

Three rails, all in `SignalToOrderBridge`, which now tracks entry time and
entry stop from `OrderFilledEvent` because a broker `Position` carries neither:

* **Minimum hold** (10 trading days) on signal-driven exits.
* **Loss escape** (0.5R), which is what makes the minimum hold defensible. The
  open tension recorded here was real: a minimum hold blocks a
  signal-*deterioration* exit, which is not protective, so on its own it would
  sit through a broken thesis to save $12 of commission. Above 0.5R down, half
  the risk budgeted for the whole trade is already spent and the hold stops
  applying.
* **Time stop** (30 trading days), the counterweight - the reviewer's framing
  was right that markets do not know what "two weeks" means. One rail stops the
  system churning, the other stops it holding forever on a thesis that never
  resolved. Checked on the tick, so the broker is only asked for positions on
  the rare occasion it fires.
* **Turnover budget** (10 entries per rolling seven days), on entries only. A
  budget that blocked exits would be a rail against de-risking.

None of this can delay a protective exit: the resting broker stop, the delever
sweep and the kill-switch do not come through the signal path. A position whose
entry this application did not record - an adopted one - is never trapped.

### M32 - ASX readiness

**The blocker nobody flagged: there is no ASX market data source.** Alpaca is US
equities only, and the entire live data path hardened through M17/M25/M26 serves
US symbols. Needs a feed decision (yfinance, delayed and unofficial, vs IBKR's
own), currency handling, and the IBKR live path actually exercised.

Also: slippage is modelled at a flat 5bps, optimistic for ASX small and mid caps
where a $20,000 position can be a meaningful share of daily volume.

### M33 - Validation using what already exists  **[DONE, 1 August]**

`scripts/validate_strategy.py` runs Monte Carlo and walk-forward across the
watchlist with the cost model the live system uses. Three findings, all in the
measuring instrument rather than the strategy:

* **Every backtest was costed with no commission floor.** The Workbench built
  `CostModel()` bare at both call sites; that constructor defaults
  `min_commission` to 0.0 so pre-M27 backtests keep their numbers, against a
  configured 6.60. On swing over 40 symbols the drag is 1.5% of gross P&L at
  100k per symbol and 10.4% at 20k - a fixed fee is trivial on a large
  position and ruinous on a small one, and live positions are the small ones.
* **The backtester could hold shorts the live system cannot open.** The signal
  adapter mapped a sell to MINUS conviction. It means close the position -
  swing's carries `exit_reason=trend_broken` - and the live OMS submits buys
  and sells-to-close only. mean_reversion spent 48% of the AAPL series short,
  volatility 45%. A sell now goes flat.
* **Swing barely trades.** Exposure changes 7 times in 300 bars and never
  returns to zero after bar 52 - one trade per symbol in 14 months. So the
  Monte Carlo cone resamples near-buy-and-holds, and walk-forward manufactures
  exactly one entry per window at the slice boundary: 12 symbols, 1 full-run
  trade each, 3 walk-forward trades each. Neither tool says much about swing
  until it exits.

**Correlation is a limit now, not a table.** `PortfolioGovernor` trims against
a correlated cluster the same way it trims single-name and sector: holdings
whose returns track the candidate's at or above 0.70 are capped at 30%
combined. The cluster is defined per candidate rather than as a fixed
partition, which is what correlation actually is.

Sector was the proxy, and the proxy fails in the conditions the limit exists
for - correlations converge in a crisis, and a bank and a homebuilder in
different sectors stop being different at the moment that matters.

**The rail had to be fed before it could bite.** `existing_returns` was an
empty dict in `SignalToOrderBridge`, with a comment calling it a documented
simplification. It made two rails inert rather than lenient: nothing to
correlate against, and `PortfolioRiskChecker` computing portfolio VaR and ES
for a book it believed was empty. The warm start already seeds 300 daily bars
per symbol - the history existed and was never handed over. Series are indexed
by timestamp, not bar number, so correlating two symbols compares the same day;
pairs sharing fewer than 20 observations are skipped, because correlation on a
handful of points is noise. A symbol with no history is NOT assumed
correlated - the opposite of the unknown-stop rule, and deliberately so, since
that default would refuse every symbol the app has never held.

## Already built, despite appearing on review wishlists

Monte Carlo; walk-forward (on the Workbench since M19); regime probabilities and
an exposure scalar the risk engine applies; volatility-targeted sizing (the 1% is
a ceiling, not a constant); EMA rather than simple moving averages; a correlation
table.
