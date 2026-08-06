# Live trading readiness

**Drafted 6 August 2026, against build M56+M51.** The reference for the question
"what has to be true before this trades real money", written while the answer is
clearly *not yet* — which is the right time to write it, because the list is
harder to be honest about once there is pressure to go.

Nothing here is a recommendation to go live or not. It is the checklist, the
evidence against it, and the things that only start to matter when the money is
real.

---

## 1. Where the locks are

Live trading is **not reachable by configuration**. Three independent locks, in
increasing order of deliberateness:

| Lock | What it is | How it opens |
|---|---|---|
| `trading_mode` | Config, defaults to `paper` | A settings edit |
| `live_trading_confirmed` | Constructor argument on the broker adapter | **A code change** — no caller anywhere in `src/` passes it |
| `allow_autonomous_live_trading` | Separate flag with no Settings UI | A deliberate config edit, checked by the autonomy gate |

Setting `trading_mode='live'` **on its own makes the application refuse to
start** — `AlpacaLiveTradingNotConfirmedError` is raised when the adapter is
constructed. That is by design: reaching a real-money endpoint can never be the
result of one mistaken edit.

The third lock means there is no supported configuration in which this system
trades real money with no human in the loop. Removing that would be a decision
of a completely different kind from the other two.

---

## 2. The evidence gate — the system's own bar

The promotion gate already encodes what "proven" means. Measured 6 August:

| Test | Required | Actual | |
|---|---|---|---|
| Closed trades | 30 | **1** | ✗ |
| Average R | ≥ +0.20 | **−1.68** | ✗ |
| Win rate | ≥ 40% | **0%** | ✗ |
| Worst loss vs average win | ≤ 3× | no wins to compare | ✗ |
| Kelly sizing active | 20 trades | **inert** | ✗ |

That last row deserves its own sentence. **Every position this system has ever
taken was sized on two invented constants** — a 0.55 win rate and a 1.5
win/loss ratio, shipped as placeholders. Measured sizing does not switch on
until 20 closed trades exist. Going live before then means risking real money
on a position size derived from numbers nobody measured.

The scorecard currently reads `promoted-below-bar`: trading unattended on
evidence it does not have. That is permitted on paper because
`enforce_promotion_evidence` is off. It is the exact condition that flag exists
to prevent live.

---

## 3. The market problem

**The intended destination is the ASX. Alpaca cannot reach it.**

The trial is collecting evidence on US megacaps, through a US paper broker, on
US session hours, with a US commission model. An ASX system shares none of
those. What the trial genuinely validates is the **machinery** — protection
rests, fills are absorbed, trades are recorded, rails bind — and that is
market-agnostic. The **edge numbers are not**, and carrying them across would
be assuming the conclusion.

Reaching the destination needs a broker adapter that trades the ASX. `ibkr`
exists in the broker list and is a seam with no implementation behind it. That
is a substantial build, and it is on the critical path to live trading in the
intended market.

---

## 4. What is not built, and only matters with real money

Each of these is survivable on paper and expensive live.

**M39 — Corporate actions.** Nothing in the order, position or protection path
knows they exist. One ordinary 2-for-1 split produces four failures from a
non-event: the kill-switch trips on the doubled share count, the resting stop
sits at roughly twice the new price, the re-arm restores protection at a level
that liquidates the position, and the trade's P&L is wrong by the split factor.
**This is the highest-severity gap.** Ten positions held for a quarter makes it
a question of when.

**M43 — Trading halts.** No detection anywhere. The staleness rail covers
entry; it says nothing about the case that hurts — position held, symbol
halted, stop cannot fill, reopens materially lower.

**M41 — Earnings event risk.** With a 10-day minimum hold and a 30-day time
stop, holding through an announcement is arithmetically unavoidable, roughly
quarterly per position. The 6% gap budget was measured across 28,987 ordinary
nights; earnings gaps of 15–20% are common, and a stop does not help because
the price never trades there.

**M44 — Execution quality.** Every order is a market order. Slippage is
modelled at a flat 5bps regardless of size, time of day or spread. The first
real data point is not encouraging: the CVS stop gapped through and cost
**1.68R, not the 1R the sizing assumes**. If that is typical, every position is
sized against an understated downside — and `entry_slippage` is recorded on
every trade specifically to answer this, and is currently read by nothing.

---

## 5. What live trading tests that paper does not

Worth stating because a clean paper record can create false confidence.

* **Real fills.** Paper fills are optimistic. Partial fills, queue position and
  liquidity at the touch are all softer on paper than in the market.
* **Real slippage**, especially at the open, which is when this system's stops
  are most likely to trigger.
* **Halts, auctions and circuit breakers**, none of which paper simulates
  faithfully.
* **Margin, settlement and pattern-day-trading rules**, which have real
  consequences and no paper equivalent.
* **Tax and reporting**, entirely outside the system's scope today.
* **The operator's own behaviour under real loss** — the sign-off gate assumes
  a human who is calm, and paper losses do not test that.

---

## 6. The order these should be answered in

1. **Finish the validation run.** Configuration frozen, reviewed 20 August.
   Until there are closed trades, every other question is speculative.
2. **Reach 20 closed trades** so sizing is measured rather than invented, then
   30 so the promotion gate can be read at all.
3. **Build M39**, and probably M43. These are the ones that turn an ordinary
   market event into a loss.
4. **Read what M44 has been collecting.** The cost model's accuracy is already
   being measured; it just is not being looked at.
5. **Decide the market and broker.** If the destination is the ASX, the
   evidence has to be re-earned there, and an adapter has to exist.
6. **Only then** consider the locks in section 1 — and open them one at a time,
   with `execution_mode` set to `recommend` so every order is signed by hand,
   whatever the paper record says.

---

## 7. The honest summary

The **machinery** is in good shape and improving fast — protection rests at the
broker and survives restarts, fills are absorbed including partial ones, closed
trades are recorded and persist, refusals and approvals are both measured. Most
of that was built or fixed on 5–6 August, and it has been stable for less than
two days.

The **evidence** does not exist. One closed trade, a loss, on a strategy sized
by placeholder constants, in a market the system does not intend to trade.

Those are different statements and both are true. The first is what makes going
live *possible* one day; the second is why it is not today.
