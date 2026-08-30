# Absence is not staleness — design

**30 August 2026.** Item 33: treat *never printed this session* as its own entry
refusal, distinct from stale.

## 1. What was found, and how it changes the item

Item 33 says the feed's blind window and the entry gate line up by coincidence,
and that nothing asserts it. Investigating before designing confirmed the gap,
corrected one claim, and found a sharper hazard the item only half-names.

### ✅ Confirmed, and it is one line

`market_data.py:290`, inside `_check_staleness_once`:

    for symbol in self.symbols:
        last = self._last_seen.get(symbol)
        if last is None:
            continue

**A symbol the feed has never delivered is skipped by the staleness rail
entirely.** It is never marked stale, never publishes `DataStaleEvent`, and
never enters `StrategyEngine._stale_symbols`. Absence is not staleness, and here
is the branch that proves it.

### ✅ Confirmed: the feed-health signal reaches a display and stops

`MarketDataFeedEvent` exists precisely for the case where *"a feed that never
delivered anything raised nothing at all"*. Its only subscriber is
`main_window.py:83`. **Nothing in `domain/` consumes it, and no entry decision
gates on feed health.**

### ⚠️ The item overstates one part

Signals are generated inside `StrategyEngine._on_market_data`, which is
**tick-driven**. A symbol with no tick never reaches the handler, so it cannot
signal. "No data at the bell" is therefore not by itself an entry hazard, and
the 10:29 gate is not the only thing standing in the way.

### ⚠️ And it understates another: this is a RACE, not a coincidence

A *pre-session* print — yesterday's close served as if current — is caught by
the staleness arithmetic: `elapsed = (now − last) − 1200s`, stale beyond 900s,
so a print from yesterday is ~18 hours old and far past the 2,100s line.

But **exclusion is computed by a periodic pass while the signal is computed on
tick arrival.** Between a pre-session-stamped tick landing and the next pass
running, a signal can be generated from data that is not today's. A bigger
margin does not fix a race; an assertion at the point of decision does.

## 2. The design: a gate that refuses, and a rail that reports

Two pieces with one job each. **The gate enforces. The rail makes the condition
visible before an entry is ever attempted.** They are deliberately not the same
mechanism, because a rail that runs periodically cannot close a race and a gate
that runs only on an order cannot tell you the state of the book.

### 2.1 The gate — `AutonomyGate`

`AutonomyGate.__init__` gains one parameter, following the pattern the file
already establishes for `scorecard_source`:

    last_print_source: Callable[[str], datetime | None] | None = None

Its existing comment states the reason, and it applies unchanged here: *"supplied
as a callable rather than a ledger reference so the gate stays a pure decision
function with no knowledge of where evidence comes from, and so it can be
exercised without a trade history."*

In the **buys** section — after the market-closed check and the sell exemption,
before the appetite rails — the gate refuses when the symbol has no print
belonging to the current trading session:

* `last_print_source(symbol)` returns `None` → **"no price at all this session"**
* its trading date is before the current trading date → **"last price is from a
  previous session"**

Two distinguishable reasons, because they are two different facts and the log
should say which. Both map to one new `refusals.py` entry, separate from
`("stale", …, "Stale market data")`.

**The comparison is `mc.trading_date(market, …)`, not a calendar date.** The
exchange's session date is the only correct notion of "this session", and a raw
UTC date is precisely the bug M120 fixed in the unattended test — where a fixture
dated itself into the future whenever the market's date lagged UTC's.

### 2.2 ⚠️ BUYS ONLY. This must never refuse a sell

Sells already return allowed above this point as risk-reducing, and protective
stops return allowed earlier still. **Refusing an exit because the feed is quiet
would strand a position in exactly the conditions where getting out matters** —
strictly worse than the hazard being prevented. This is the same asymmetry the
gate already applies, and the new check sits below both exemptions so it cannot
reach them. A test plants a sell to prove it.

### 2.3 When the source is not wired

If `last_print_source` is `None` the gate behaves exactly as today — it does not
refuse. That keeps every existing call site and the backtester unchanged.

⚠️ **This is a guard that can be silently disabled by not wiring it**, which is
items 59 and 67's shape, and M156's. It is therefore pinned by a **wiring test**
asserting `runtime.py` constructs the gate with a source, not merely that the
parameter exists.

### 2.4 The rail — visibility, not enforcement

`_check_staleness_once`'s `last is None` branch stops being a silent `continue`.
Symbols with no print are counted and reported in **one line, with a count**, on
transition rather than every pass:

    N of M watched symbol(s) have not printed at all this session, so they are
    ABSENT rather than stale and the staleness rail cannot see them. They
    cannot be entered.

M154's shape: a count, not an adjective. M151 asserted a suppression that never
reached the log — 678 claimed against 774 still present — and a line with no
number cannot be checked against anything.

⚠️ **It does NOT publish `DataStaleEvent`.** That event means "last printed N
seconds ago", which is false for a symbol that never printed, and routing absence
through it would make the log lie in the exact way this item exists to stop.
Enforcement is the gate's job.

### 2.5 ⚠️ The trigger condition, and why it is not "the session has opened"

The obvious wording is "report absence once the session has opened". **`MarketDataFeed`
cannot express that**: it holds `bus`, `source`, `symbols`, the thresholds and
`source_delay_seconds`, and knows nothing about a market or a session. Adding a
market to a pure data component to answer a reporting question is the wrong
trade.

**The line fires when at least one symbol HAS printed and others have not.**
That is self-contained, needs no new dependency, and states the condition that is
actually interesting: *the feed is working, and these symbols are not in it.*

It also disposes of the two noise cases for free. Before the first tick — at the
bell, or on any launch outside hours — nothing has printed, so there is no line
rather than a false "94 of 94 absent". And a wholly dead feed stays
`MarketDataFeedEvent`'s question, not this one, which keeps the M28a separation
between "one symbol is silent" and "the feed is down".

## 3. Testing

**At the layer the defect lives, with a planted violation.**

1. **A buy on a symbol whose last print is from a previous session is refused**,
   with a reason distinct from "stale".
2. **A buy on a symbol that has never printed is refused**, with the other
   reason. Both assert the wording, since two facts sharing one message is the
   thing being fixed.
3. **A buy on a symbol that printed this session is ALLOWED** — the control.
   Without it, a gate that refuses everything passes tests 1 and 2.
4. **⚠️ PLANTED: a SELL on a symbol that has never printed is ALLOWED**, and so
   is a protective stop. This is the failure mode that would strand a position,
   and asserting it cannot be left to inspection.
5. **The trading-date boundary**, both sides: a print at 23:59 Sydney yesterday
   refuses; one at 00:01 Sydney today does not. A calendar-date or UTC-date
   implementation fails this.
6. **The wiring test** — `runtime.py` builds the gate with a `last_print_source`.
7. **The rail reports a count** when some symbols have printed and others have
   not; **reports nothing before the first tick** (the bell and every
   outside-hours launch, which is the noise case §2.5 disposes of); and
   publishes no `DataStaleEvent` in either case.

## 4. Blast radius

**`AutonomyGate` is the entry path.** Every buy this system makes passes through
it. A defect here either refuses everything — visible, and the safe direction —
or allows something it should not, which is silent. The new check is additive,
sits below both existing exemptions, and defaults to today's behaviour when
unwired.

Verification is the full suite plus ruff, black, mypy and bandit. Item 22's three
green tests hid a broken order path that the full suite found in 134 failures.

⚠️ **A watched session is required and the suite is not a substitute.** What the
suite proves is that the refusal fires on constructed inputs. What it cannot
prove is the behaviour at a real bell, where the interesting question is whether
this refuses everything for the first twenty minutes and whether that is correct.
**The item was deliberately deferred on 25 August to avoid being appended to a
long day of other changes; implementation is therefore planned for an open
market, not for tonight.**

## 5. Out of scope

* **Replacing yfinance with IBKR as the price source.** Item 33 calls it the
  deeper fix and it is a separate piece of work with its own measurement.
* **Gating entries on feed health.** `MarketDataFeedEvent` reaching only a
  display is a real finding, recorded here, but feed-wide health is a different
  rail from per-symbol absence and mixing them would repeat the M28a mistake of
  halting an account for one symbol's silence.
* **The 15:40 end of the window.** Already documented; unchanged here.
