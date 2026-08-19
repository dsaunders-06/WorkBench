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

## ADDENDUM — the narrow version, priced (19 August, after the first draft)

The first draft priced "a corporate-action announcements feed". **That
overstates what the code needs**, and the operator was right to ask.

### What the data actually is

`Announcement` is six fields, three of which matter:

```python
symbol: str
ex_date: date        # the only field the gate and the quarantine key on
ratio: float         # new_rate / old_rate. 2.0 is a 2-for-1, 0.001 a 1-for-1000
action_id: str       # bookkeeping
payable_date: date | None
fetched_at: datetime
```

**Splits only.** Alpaca's query is `ca_types=[CorporateActionType.SPLIT]`, and
the adapter says why: *"a spin-off or a merger has no single ratio to apply,
and this account has never processed one."* No dividends, no mergers, no
spin-offs, no news, no earnings.

So the requirement is: **for each held symbol, a forward-dated split notice
carrying an ex-date and a ratio, refreshed daily.** No intraday need — the
notice must simply arrive before the ex-date open.

### The sources, priced

| source | ASX splits | forward-dated? | cost | |
|---|---|---|---|---|
| **yfinance** | yes | **NO** — historical | free | measured: BHP's last split is 2002 |
| **EODHD ASX Corporate Actions (beta)** | yes | **source is; product unconfirmed** | **USD 59.99/mo** | from ASX ReferencePoint E34, daily ~18:30 AEST |
| **ASX ReferencePoint** (direct) | yes | **yes** — "a calendar of forthcoming corporate actions… cum/ex dates" | licence, POA | the official source everyone else resells |
| **Twelve Data** | yes | **NO** — historical | Pro+ tier | |
| **FMP splits calendar** | forward-dated | — | — | **ASX not among supported exchanges** |
| **IBKR** | **no structured feed** | — | — | measured against ib_async 2.1.0 |

**One realistic candidate: EODHD at USD 59.99/month**, and it carries an open
question. Its beta documentation shows splits with `date`, `split` (e.g.
`"2000:3"`), `record_date` and `effective_date` — **no explicit ex-date**,
which is the one field everything downstream keys on. The underlying ASX feed
does carry cum/ex dates, so this is probably a documentation gap rather than a
data gap, but **it is unconfirmed and would have to be settled before paying.**

### The base rate, measured rather than assumed

`Ticker.splits` is useless for detection and exactly right for measuring how
often the rail would ever fire. Across the app's own ASX megacap watchlist,
94 of 100 symbols resolving, ten years:

**10 split events in 10 years — 0.0106 per symbol-year.** Holding 10 names for
12 months gives **0.106 expected events**, about one in nine years of trading.

But the composition matters more than the count:

| ratio | events | what it is | does it threaten a stop? |
|---|---|---|---|
| 0.97–1.03 | 6 | capital returns, minor adjustments | no — share count barely moves |
| 0.1, 0.2, 0.8, 0.85 | 4 | **consolidations** (ratio < 1) | stop left STRANDED below market — unprotected, not fired |
| **> 1.1** | **0** | **forward splits — the MNST direction** | **would fire the stop instantly** |

**Zero forward splits among 100 ASX megacaps in ten years.** MNST was a 2-for-1:
the price halves, so a sell stop set at the pre-split level sits *above* market
and fires immediately — that is the −51.4%. A consolidation does the opposite:
price rises, the stop is stranded below and simply never fires. Both are bad;
only one liquidates the position at the open.

Material events (ratio outside ±15%): **4 in 940 symbol-years**, so holding ten
names for a year gives roughly **0.04 expected** — and none historically in the
direction that causes the MNST failure.

### And the gap is not total, which the first draft did not say

A split changes the SHARE COUNT at the broker. Reconciliation compares tracked
quantity against the broker's and trips the kill-switch on divergence, so the
app is not blind to the CONSEQUENCE — only to the WARNING. That is detection
after the fact rather than prevention, and for a forward split the stop may
already have fired at the open. It is a degraded net, not no net, and it
already exists.

## Recommendation — unchanged by the pricing, but for better reasons

**Option 1, refined: accept the gap, and report UNSUPPORTED as a capability
state rather than a recurring query failure. Do not buy a feed during
testing.**

The first draft recommended this because option 2 was "not available today".
That was wrong — it IS available, at USD 59.99/month from EODHD. The pricing
makes the case *stronger*, not weaker:

1. **The rail would almost never fire.** 4 material split events in 940
   symbol-years. Holding ten names for a year: **~0.04 expected**. USD 720 a
   year to insure an event with a roughly one-in-twenty-five annual chance,
   during a phase whose entire purpose is to test machinery on a paper account
   where no real money is at risk.
2. **Zero events in the dangerous direction, in ten years.** Every material ASX
   event measured was a consolidation, which strands a stop below market. The
   forward split that fires a stop instantly — the MNST shape, the whole reason
   the rail exists — did not occur once among these hundred names.
3. **The candidate has an unresolved question.** EODHD's split records show no
   explicit ex-date, and `ex_date` is the one field everything downstream keys
   on. Paying before settling that would buy a feed the detector may not be
   able to consume.
4. **Option 1 as currently built is actively harmful** — 2,880 warnings a day
   and a permanent red banner is how an operator learns to stop reading
   banners. That costs more, today, than the gap it reports.
5. **The consequence is not undetected, only unwarned.** Reconciliation
   compares share counts and trips the kill-switch on divergence. Degraded, and
   not nothing.

### The consistency check, because it cuts the other way too

The operator has already decided **not** to buy ASX Total at USD 25/month
during testing, on the grounds that it cannot reach the app. Buying a **USD 60**
feed for a rail expected to fire 0.04 times a year would be a larger spend for
a narrower benefit. Declining it is the consistent decision, not merely the
cheap one.

### What would change this

* **A real ASX paper trial with evidence you intend to quote**, where one
  corrupted trade in the ledger matters more than USD 60. Revisit alongside
  Stage 2's market-data decision, priced as one purchase.
* **Any forward split appearing among held names** — the base rate is ten years
  of history, not a guarantee.
* **EODHD confirming a usable forward ex-date on splits.** Worth an email
  before any purchase, and worth doing *before* a trial rather than during one.

### What choosing this means, stated so it cannot be discovered later

On the ASX phase, a split on a held position will **not** be detected before
the ex-date open. The ex-date gate — the piece observed working in production,
refusing CRWD — and M60's declare-then-quarantine are inert. The rail that
would have caught MNST is absent, and the app will say so plainly rather than
imply otherwise.

**M43 (trading halts) therefore stays unbuilt by decision**, since ASX halts
are announcement-driven and its shape depends on this choice.

## What is NOT being decided here

* Whether to buy an ASX announcements feed at a real paper trial. Revisit with
  Stage 2, priced as one decision alongside the market-data question.
* Whether the yfinance ex-dividend date is worth wiring as a partial signal.
  It is a separate, smaller question and mixing it in here would let a
  dividend-date feature read as split coverage.

**Awaiting the operator's choice. No code has been written.**
