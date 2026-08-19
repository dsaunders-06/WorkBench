# IBKR capability measurement — W1.1, Stage 1 Task 1

> ## ⛔ STOP — the measurement found something that outranks it
>
> **`IBAdapter` cannot transmit a protective stop, and does not fail when
> asked to. It sends a MARKET order instead.**
>
> `to_ib_order` ([ib_translate.py:31](../../../src/qat/data/broker/ib_translate.py))
> branches on `limit_price` only:
>
> ```python
> if order.limit_price is not None:
>     return LimitOrder(action, order.quantity, order.limit_price)
> return MarketOrder(action, order.quantity)
> ```
>
> `OMS._propose_protective_order` ([oms.py:1062](../../../src/qat/domain/oms/oms.py))
> builds the protective stop as `side="sell"`, `order_type="stop"`,
> `stop_price=X`, **`limit_price=None`**. That falls through to
> `MarketOrder("SELL", quantity)`.
>
> **A protective stop for an unprotected position becomes an immediate market
> sell of that position.** The `Order` dataclass warns about precisely this,
> in a comment written when M31d introduced the distinction: *"submitting it
> as one would liquidate the position it was meant to protect."* Alpaca
> honours it (`alpaca_adapter.py:521`, `StopOrderRequest`). IBKR does not.
>
> Two more from the same three lines:
>
> * `stop_price` and `take_profit_price` are **silently dropped** on a
>   bracketed entry, so an entry that believes it is protected opens naked.
> * `to_ib_contract(symbol)` defaults to **`currency="USD"`** and
>   `IBAdapter.place_order` never overrides it, so ASX symbols are sent as USD
>   contracts.
> * `modify_order` only propagates `limit_price`, so M39's re-pricing of a
>   resting stop through a corporate action would be accepted and ignored.
>
> **Severity.** This is worse than the M70/M71 dormancy that made Task 3
> urgent. That recorded prices the account never paid. This one sells the
> book at market when it means to protect it. Nothing is at risk today
> because `QAT_BROKER=alpaca`, and no fix is applied here — Task 1 is a
> measurement and this needs its own plan-and-approval cycle. **Proposed as
> M95.**
>
> Why the test suite missed it: `tests/data/broker/test_ib_translate.py`
> covers `to_ib_order` for a market buy and a limit sell. There is no stop
> case. The capability audit did not catch it either, because `place_order`
> is CORE and present — the adapter has the method; it is the *translation*
> that is wrong. A capability matrix built on `hasattr` cannot see that.


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
| 1. Does `permId` survive a Gateway restart? | an order carrying a permId | **order placed — awaiting restart** |
| 3. Does a stop appear in `openTrades()`? | a stop | **ANSWERED: yes** |
| 4. How far back do executions go? | an execution | **still blocked — needs a real fill** |
| 2. Are ASX stops native or simulated? | IBKR documentation | **strong evidence found, see below** |

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

## The single write: one resting buy-stop, and what it answered

Operator-approved 19 August. **BUY 1 BHP STP @ 95.00 GTC**, against a last
close of 63.71 — ~49% above the market, so it cannot trigger. No position, no
fill, no short, no exposure. Placed with raw `ib_async`, **not** through
`IBAdapter`, which cannot transmit a stop at all (see the box at the top).

First: the `whatIfOrder` preview, which creates no order:

```
OrderState(status='PreSubmitted', commission=6.6, commissionCurrency='AUD',
           initMarginChange='21.02', maintMarginChange='19.11',
           equityWithLoanBefore='1003733.21', warningText='')
```

* **ASX trading permission is GRANTED** — confirmed, not assumed. A full
  margin preview came back with no permission error.
* **Commission is AUD 6.60**, exactly the ASX Fixed floor the plan quoted.
  Measured, and it is the input the cost-to-risk rail needs.
* Account equity ~**1,003,733** — the 10x-the-US-trial figure the plan warned
  changes which rails bind.

Then the order itself:

```
Trade(contract=Contract(secType='STK', conId=4036812, symbol='BHP',
        exchange='SMART', primaryExchange='ASX', currency='AUD'),
      order=Order(orderId=8, clientId=97, permId=828725903, action='BUY',
        totalQuantity=1.0, orderType='STP', lmtPrice=0.0, auxPrice=95.0,
        tif='GTC'),
      orderStatus=OrderStatus(status='PreSubmitted', permId=828725903,
        whyHeld='trigger', ...))
```

**Question 3: ANSWERED — yes.** The resting stop appears in **both**
`IB.openTrades()` and `IB.reqAllOpenOrders()`, count 1 each, agreeing on
symbol, action, quantity, `orderType='STP'`, `auxPrice=95.0`, status and
permId. `resting_stops` and `resting_stop_orders` are therefore buildable on
IBKR, and Task 4 can proceed on measured ground.

### `whyHeld='trigger'` — the field that speaks to question 2

The order reads `status='PreSubmitted'` with **`whyHeld='trigger'`**. That is
IBKR's own marker for an order **held at IBKR awaiting its trigger** rather
than working at the exchange — which is what a *simulated* stop is.

Two things follow, and they must not be conflated.

1. **This run cannot settle native-vs-simulated for LIVE ASX**, because IBKR
   states stops are *always* simulated in paper. Observing simulation in paper
   is consistent with either answer live.
2. **But the API exposes the distinction, and that is the actionable
   finding.** `whyHeld` means the app does not have to *assume* whether its
   protection is resting at the exchange — it can read it. A
   `resting_stop_orders` that surfaced `whyHeld` would turn the US trial's
   strongest safety claim from an assertion into an observation, on exactly
   the axis the plan worried it would lose. **Recommend Task 4 carry
   `whyHeld` through.**

`permId = 828725903`. **The order is still resting**, deliberately, for the
restart comparison. Cancel it with the `orderId=8` / permId above when done.

## What to do next

1. **M95 first — before Task 2, before Task 4, before anything.** `IBAdapter`
   turning a protective stop into a market sell is not something to carry
   into further IBKR work. It needs its own plan, a failing test proven red
   (`to_ib_order` with `order_type="stop"`), and the currency and
   `modify_order` gaps fixed alongside.
2. **Restart the Gateway and re-read permId 828725903** — that closes
   question 1 and validates or overturns Task 3's identity choice. Cheap, and
   the order is already resting.
3. **Question 4 still needs a real fill** and is the only one left needing an
   execution. Worth deciding whether it is worth a filled order, or whether
   `reqExecutions`' documented behaviour is enough.
4. **Question 2 stays formally open** for the live case, though `whyHeld`
   gives the app a way to stop caring: it can read what it currently assumes.
5. **Cancel the test order** when the restart comparison is done.

Tasks 2 to 5 remain unstarted, as planned.
