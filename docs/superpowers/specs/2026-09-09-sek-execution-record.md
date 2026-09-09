# SEK.AX execution record, 9 September 2026 — evidence for a ledger repair

⚠️ **CAPTURED DELIBERATELY BECAUSE IT EXPIRES.** `reqExecutions` returns
SAME-DAY ONLY — measured 26 August 2026, when it returned 183 executions and
every one was from that day. Without this file the truth below is unrecoverable
after the 9 September session, and the ledger cannot be repaired against
anything.

Read from the live paper Gateway at 14:52 AEST by `scripts/ibkr_probe.py`,
read-only, clientId 99, account `DUQ200898`.

## The truth

**SEK.AX: 2,978 shares SOLD, average price 12.93**, in TEN partial
executions over 28 seconds, all under `permId=750830242` / `orderId=686`,
completing at 04:49:40 UTC (14:49:40 AEST).

| time (UTC) | shares | cumQty | price |
|---|---|---|---|
| 04:49:12 | 1706 | 1706 | 12.93 |
| 04:49:12 | 285 | 1991 | 12.93 |
| 04:49:15 | 36 | 2027 | 12.93 |
| 04:49:15 | 3 | 2030 | 12.93 |
| 04:49:16 | 6 | 2036 | 12.93 |
| 04:49:29 | 15 | 2051 | 12.93 |
| 04:49:29 | 2 | 2053 | 12.93 |
| 04:49:31 | 20 | 2073 | 12.93 |
| 04:49:38 | 262 | 2335 | 12.93 |
| 04:49:40 | 643 | 2978 | 12.93 |

⚠️ **TEN, NOT THIRTEEN.** An earlier version of this file and of HANDOFF.md
said thirteen; that was a miscount of the probe output, corrected here. The ten
rows above are the complete set and their shares sum to 2,978.

Commission totalled **33.88 AUD** across them. ⚠️ Worth noting on its own: the
app's cost model put the exit cost at **53.13** for the same trade, so it
overestimates commission here by about 57%. Not acted on, and the repair below
deliberately keeps the MODELLED cost so this row stays consistent with every
other row in the ledger rather than becoming the only measured one.

⚠️ **THE APP READ THIS POSITION AT 04:49:12**, twelve seconds in, when 2,030 of
2,978 had filled. That is the whole cause of the day's near-miss: it concluded
948 shares remained and proposed a protective SELL against a position that
finished flat 28 seconds later.

## Corroborating: the account held no SEK afterwards

`IB.positions()` at 14:52 returned NINE positions and SEK was not among them:

    BOQ 13586, BHP 793, ANZ 640, TWE 10412, JHX 1097,
    SUN 3192, WOW 1098, ASX 1314, TAH 64229

`reqAllOpenOrders` returned exactly two resting legs for each of those nine,
BHP included. Nothing rested against SEK.

## What the ledger says instead, and what to repair

`closed_trades.csv` holds TWO SEK rows after the 14:58 restart:

| closed_at | quantity | exit_price | net_pnl | exit_reason |
|---|---|---|---|---|
| 2026-09-09T04:49:12Z | 2978 | 12.90 | −6021.32 | signal |
| 2026-09-09T04:49:40Z | 2027 | 12.93 | −4037.74 | target |

**5,005 shares booked against a 2,978 position.** The first row was written
optimistically at transmit and carries the sized-against price rather than the
executed one; the second was booked by `absorb_broker_fills` on restart, which
replayed the same executions and misclassified them as a broker-side protective
fill — *"a resting protective order executed ... while this application was not
running"* — because the trip at 14:49:11 and the shutdown at 14:52:40 left no
reconciliation pass between them to absorb the fills while running.

**The repair is ONE row replacing both: 2,978 @ 12.93, `signal`.** No money is
affected — the broker was correct throughout and startup reads positions from
it — but `closed_trades.csv` is what `edge_min_trades`, the promotion gate and
the Performance tab read, so a double-counted exit corrupts the evidence base
the sizer is waiting on.

⚠️ **Do the repair with nothing holding the file**, and note that `trades.py`
backs the CSV up before its first amendment in a process
(`closed_trades.csv.bak-<stamp>`), which is the precedent to follow by hand.


---

## ✅ REPAIRED 9 September 2026, 17:18

Applied with the app closed, after a dry run, and backed up first to
`closed_trades.csv.bak-repair-20260909-071800` — the precedent `trades.py`
follows before its own first amendment in a process.

**Dropped** the duplicate written by `absorb_broker_fills` on restart:
2,027 @ 12.93, `target`.

**Amended** the original, mirroring exactly what `_correct_announced_price`
would have done had it run — exit price, realised P&L, exit cost and R-multiple:

| field | was | now |
|---|---|---|
| closed_at | 04:49:12 | 04:49:40 (last execution) |
| exit_price | 12.90 | **12.93** |
| exit_cost | 53.01 | 53.13 |
| gross_pnl | −5907.14 | **−5817.82** |
| net_pnl | −6021.32 | **−5932.12** |
| pnl_pct | −0.13585 | −0.133837 |
| r_multiple | −0.9612 | **−0.9469** |
| gross_r_multiple | −0.943 | −0.9287 |

**Left alone deliberately:** quantity, entry price, entry cost, stop, risk per
share, `exit_reason` (`signal` — it was a signal exit, not the `target` the
absorbed row claimed), and every excursion field. The excursion figures on the
kept row are the app's own tracking through the hold and are self-consistent
(`worst_price` 12.90 against `mae_r` −0.943); the absorbed row's
`best_price == entry_price` and `mfe_r == 0.0` were replay defaults carrying no
information.

⚠️ **The cost-proportionality was VERIFIED, not assumed.** The repair script
asserts that entry and exit costs sit at the same rate against their own
notional before using that rate, and the assertion passed.

**Result:** 11 rows; SEK booked at 2,978, matching the broker exactly; today's
true net **−7,797.75**.

⚠️ **THE 9 SEPTEMBER DAILY REPORT IS STILL WRONG** — written at 16:04:48, it
says *"3 closed trade(s), net $-11,924.91"* against a true 2 and −7,797.75. It
is a derived artefact of the corrupted ledger and was not regenerated. The
ledger underneath it is now correct.
