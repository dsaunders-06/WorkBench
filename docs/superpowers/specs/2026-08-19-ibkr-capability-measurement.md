# IBKR capability measurement — W1.1, Stage 1 Task 1

**Run 19 August 2026, 07:11 UTC, against paper account `DUQ200898`,
read-only, IB Gateway on port 4002.** Raw responses in
`2026-08-19-ibkr-capability-measurement-raw.md`, written by
`scripts/ibkr_probe.py`; this document is the reasoning and does not get
overwritten by a re-run.

**No order was placed.** The connection was opened with `readonly=True`.

---

## The headline: this measurement is one third of itself

Every call was reachable and none raised. **And the account is empty**, so
five of the six calls returned `[]` and an empty answer from an empty account
carries almost no information. It cannot distinguish "this works and there is
nothing to report" from "this silently reports nothing" — which is the exact
failure class W1.1 exists to expose.

**Three of the four questions Task 1 was written to settle turn out to be one
experiment, not three.** Questions 1, 3 and 4 all require at least one order
to exist:

| Question | Needs | Status |
|---|---|---|
| 1. Does `permId` survive a Gateway restart? | an order carrying a permId | **BLOCKED on the order** |
| 3. Does a stop appear in `openTrades()`? | a stop | **BLOCKED on the order** |
| 4. How far back do executions go? | an execution | **BLOCKED on the order** |
| 2. Are ASX stops native or simulated? | IBKR documentation | **partly advanced, see below** |

The handoff prompt treated question 1 as the cheap one — *"note a permId, let
Gateway restart, and look again"*. On a new account **there is no permId to
note**. It is the same single order that questions 3 and 4 need, and it should
be planned as one experiment rather than three.

## What IS settled

**All four IBKR calls exist and answer on a read-only session.** No
`AttributeError`, no permission error, no pacing violation. This was not
guaranteed — `reqExecutions` in particular could have refused on a fresh
account.

| call | outcome | count |
|---|---|---|
| `IB.managedAccounts()` | data | 1 |
| `IB.fills()` | empty | 0 |
| `IB.reqExecutions()` | empty | 0 |
| `IB.openTrades()` | empty | 0 |
| `IB.reqAllOpenOrders()` | empty | 0 |
| `IB.positions()` | empty | 0 |
| announcements | **absent** | — |

**`announcements` is confirmed absent**, as measured on 19 August against
ib_async 2.1.0. There is no structured corporate-action feed to port. This is
Task 5's decision, and it is now measured rather than inferred.

**The account is a paper account.** `managedAccounts()` → `['DUQ200898']`, DU
prefix. Both guards fired correctly: the live-port refusal was not triggered
(4002), and `check_paper_account` accepted the DU account.

## ASX contracts resolve, and IBKR states its own accepted order types

Read-only `reqContractDetails`, which the probe does not run — asked
separately because question 2's documentation source returned 403 to research:

| symbol | conId | primaryExchange | validExchanges | minTick |
|---|---|---|---|---|
| BHP | 4036812 | ASX | `SMART,ASX,ASXCEN` | **0.001** |
| CBA | 4036818 | ASX | `SMART,ASX,ASXCEN` | **0.001** |
| STW | 14065804 | ASX | `SMART,ASX,ASXCEN` | **0.001** |
| AAPL *(control)* | 265598 | NASDAQ | `SMART,AMEX,NYSE,…` | 0.01 |

Three findings, in descending order of confidence.

**1. `STP` and `STPLMT` are in the accepted order types for ASX contracts.**
IBKR's own per-contract statement, verbatim from `ContractDetails.orderTypes`:

```
ACTIVETIM,AD,ADJUST,ALERT,ALLOC,AVGCOST,BASKET,BENCHPX,CASHQTY,COND,CONDORDER,
DAY,DEACT,DEACTDIS,DEACTEOD,GAT,GTC,GTD,GTT,HID,IOC,LIT,LMT,LTH,MIT,MKT,MTL,
NGCOMB,NONALGO,OCA,PEGBENCH,REL,RELPCTOFS,SCALE,SCALERST,SNAPMID,SNAPMKT,
SNAPREL,STP,STPLMT,TRAIL,TRAILLIT,TRAILLMT,TRAILMIT,WHATIF
```

**This does NOT answer question 2.** `orderTypes` is what IBKR will *accept*,
and IBKR accepts a stop on exchanges where it simulates one. Native versus
simulated is not exposed on this field. What it does establish is that a stop
order on ASX will not be rejected outright — a weaker claim than the one the
risk model needs, and it should not be quoted as the stronger one.

**2. `STW` resolves on ASX**, conId 14065804, "STATE ST SPDR S&P/ASX 200".
The benchmark `runtime.py` must stream for `RegimeEngine` to fire exists as a
tradable IBKR contract.

**3. ASX minTick is 0.001, against 0.01 for the US control.** This is a
Stage 3 input measured early and for free. Tick size reaches order pricing
directly.

**A caveat that must not be lost:** `reqContractDetails` succeeds for products
the account cannot trade. **Resolving a contract is not evidence of ASX
trading permission.** The plan's blocker — ASX permissioned on the linked LIVE
account — is NOT confirmed by anything here.

## What protection this account actually provides

Task 1 Step 5 asks for this plainly, so: **unknown, and it should not be
assumed favourable.**

The US trial's strongest safety claim was ten of ten positions carrying a stop
resting at the broker, verified at every check across nineteen days, with
`PortfolioGovernor` measuring every position's risk *to that stop*. Nothing
measured today supports or refutes that transferring. IBKR's own paper-trading
documentation states stops are always simulated in paper, and this run cannot
see past that statement to the live case.

Until the single stop order is placed and observed:

* treat `risk_at_stop` on IBKR as **unverified**, not as optimistic or
  conservative — we do not yet know which;
* **adjust no rail.** That is an operator decision with the measurement in
  hand, and the measurement is not in hand.

## What to do next

1. **Place ONE stop on ONE small position** — the single write Stage 1 permits,
   operator-approved, and it answers questions 3, 4 and (after a restart) 1
   together. Requires *Read-Only API* to be unticked for that step only.
2. **Confirm ASX trading permission on the live account.** Contract resolution
   does not establish it, and paper mirrors live permissions.
3. **Question 2 stays open** and needs IBKR's per-exchange order-type listing,
   not the API.

Tasks 2 to 5 remain unstarted, as planned.
