# Corporate-action announcements on IBKR — the decision

**Stage 1 Task 5.** The plan says this task's deliverable is a recorded
decision, not code, and that no option is implemented before the operator has
chosen. This is the record. **Nothing has been implemented.**

Written 19 August 2026. Every figure below was measured against the code or the
live paper Gateway, not carried forward.

---

## The measurement

**IBKR has no structured corporate-action feed.** Measured against ib_async
2.1.0: `reqFundamentalData` returns XML report documents and
`reqHistoricalNews` returns unstructured headline text. Neither is what M39's
detector consumes. `broker_capabilities.py` now reports IBKR implementing
**11 of 12** — `announcements` is the only gap, and the only one of the four
originally missing that has no port at all.

**yfinance does not close it, and this is worth stating precisely because
yfinance is already the ASX data source and therefore looks free.** Measured
today against `BHP.AX`:

| what yfinance gives | forward-looking? | use to M39 |
|---|---|---|
| `Ticker.splits` | **no** — historical (BHP's last is 2002) | none. A split appears *after* it happened |
| `Ticker.calendar['Ex-Dividend Date']` | yes | partial — see below |
| `Ticker.calendar['Earnings Date']` | yes | already used elsewhere |

**A retrospective split feed is exactly too late.** M39 exists to know a split
is coming *before* the ex-date, because the failure it prevents is an
unadjusted stop riding through one — which is how MNST lost 51.4% on a position
that should have been roughly flat. A source that tells you afterwards
describes the loss rather than preventing it.

---

## What actually happens on IBKR today — and it is not "nothing"

`CorporateActionMonitor._fetch` calls `broker.announcements(...)` inside a
`try/except Exception`. On `IBAdapter` the method does not exist, so the
`AttributeError` is caught, and **every held symbol is added to
`_unreadable` on every sweep**.

That is not silence — M39 was built so blindness reads as a STATE. It works.
The Risk Console says:

> Corporate actions: COULD NOT BE READ for BHP.AX, CBA.AX, … — the detector is
> blind on these, which is not the same as nothing being pending. **See the log
> for why the query failed.**

and the Dashboard raises the same banner. So option 1's machinery already
exists and already fires.

### But it degrades into exactly the failure this project keeps finding

**The message describes a transient fault. The condition is permanent.** It
says *the query failed — see the log for why*, and the log says
`AttributeError: 'IBAdapter' object has no attribute 'announcements'`, every
time, for ever. There is no query. Nothing an operator does will change it.

At the configured `protection_sweep_seconds = 300` and a full book of 10
positions, that is **120 warnings an hour, 2,880 a day**, plus a permanently
lit banner instructing someone to investigate something unfixable.

This project's own habit list names the result: *"An alarm you learn to ignore
is worse than no alarm."* Three `session_check` bugs in four days were this
shape — an instrument asserting something false about a healthy app. **On IBKR,
M39's blindness reporting becomes the fourth.**

**So option 1 as the plan describes it — "accept the gap and make it loud" — is
already built, and is already the wrong kind of loud.** A permanent capability
gap is being announced through a transient-failure channel.

---

## The options, with what each actually costs

### 1. Accept the gap, and report it as a CAPABILITY rather than a FAILURE

Distinguish two states the code currently merges:

* **UNSUPPORTED** — this adapter has no `announcements` method. Permanent,
  knowable at startup, stated once, calmly. *"Corporate-action detection is
  UNAVAILABLE on this broker."*
* **UNREADABLE** — the method exists and the query failed this pass. Transient,
  worth alarming about, worth a log line, worth "check the log".

Small and precise: a capability check at wiring time rather than an
`AttributeError` swallowed per symbol per sweep. Keeps the honest claim,
removes 2,880 daily warnings that mean one thing.

**Cost:** the ex-date gate — the piece *observed working in production*,
refusing CRWD — has no input on ASX. `M60`'s declare-then-quarantine has no
input. A split on a held ASX position is not detected before the ex-date open.
**The MNST failure mode is unprotected, and saying so clearly does not make it
protected.**

### 2. Source announcements elsewhere

ASX publishes company announcements, so a feed could supply them.

**Cost:** real work, and **yfinance does not do it** — measured above. That
means a new vendor, a new `Announcement` translation, and a new failure mode to
own, and it belongs with Stage 2's market-data decision rather than being
smuggled in here. Not free, not quick, and not available today.

**One cheap partial exists and should not be oversold:** yfinance already
returns `Ex-Dividend Date` for ASX symbols. An ex-dividend date drops the price
by roughly the dividend and can therefore trip a stop. That is a *smaller,
different* hazard from a split — it does not change the share count and does
not invalidate a stop's quantity — so it is worth knowing and **is not a
substitute for split detection**.

### 3. Drop corporate-action detection for the ASX phase

**Cost:** on IBKR this is operationally identical to option 1 — **neither
detects anything** — so the only difference is whether the application says so.
Option 3 removes machinery that transfers and costs nothing dormant; option 1
keeps it, labelled, ready for the day a feed exists.

**There is therefore no case for option 3 over option 1.** It is strictly worse
on honesty and equal on protection.

---

## Recommendation

**Option 1, refined: accept the gap, and report UNSUPPORTED as a capability
state rather than a recurring query failure.**

Three reasons, in order of weight:

1. **Option 2 is not available today** and is a Stage 2 decision with a vendor
   attached. Choosing it here would block Stage 1 on a purchase.
2. **Option 3 buys nothing.** Same protection, less honesty.
3. **Option 1 as currently built is actively harmful** — 2,880 warnings a day
   and a permanent red banner is how an operator learns to stop reading
   banners, which costs more than the gap it reports.

**What choosing this means, stated so it cannot be discovered later:** on the
ASX phase, a split on a held position will **not** be detected before the
ex-date open. The ex-date gate and M60's quarantine are inert. The rail that
would have caught MNST is not present, and the app will say so rather than
imply otherwise.

**And it follows that M43 (trading halts) stays unbuilt**, because ASX halts
are announcement-driven and its shape depends on this choice. Recorded, not
deferred by accident.

---

## What is NOT being decided here

* Whether to buy an ASX announcements feed at a real paper trial. Revisit with
  Stage 2, priced as one decision alongside the market-data question.
* Whether the yfinance ex-dividend date is worth wiring as a partial signal.
  It is a separate, smaller question and mixing it in here would let a
  dividend-date feature read as split coverage.

**Awaiting the operator's choice. No code has been written.**
