# SEK.AX execution record, 9 September 2026 — evidence for a ledger repair

⚠️ **CAPTURED DELIBERATELY BECAUSE IT EXPIRES.** `reqExecutions` returns
SAME-DAY ONLY — measured 26 August 2026, when it returned 183 executions and
every one was from that day. Without this file the truth below is unrecoverable
after the 9 September session, and the ledger cannot be repaired against
anything.

Read from the live paper Gateway at 14:52 AEST by `scripts/ibkr_probe.py`,
read-only, clientId 99, account `DUQ200898`.

## The truth

**SEK.AX: 2,978 shares SOLD, average price 12.93**, in THIRTEEN partial
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

(Ten rows shown; the probe report holds all executions verbatim. Commission
totalled roughly 33.9 AUD across them, and IBKR's own `realizedPNL` figures sum
to about −5,851.7.)

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
