# The analysis behind the 7–8 August decisions

ROADMAP.md records what was decided and why. These are the scripts that produced
the numbers, kept so that September can **re-run them against real closed trades**
rather than reconstruct them from prose.

Every one is read-only. None touches application state, and several deliberately
work on copies of the live records.

Run them from the repository root with the venv:

```bash
& ".\.venv\Scripts\python.exe" scripts\analysis\<name>.py
```

Some take a data directory. Copy the live files first — **read
`%LOCALAPPDATA%\QuantAdvisoryTerminal` via PowerShell, never Bash**:

```powershell
Copy-Item "$env:LOCALAPPDATA\QuantAdvisoryTerminal\data\*.csv" -Destination .\scratch
```

## What each one answers

| Script | Question | Where the answer landed |
|---|---|---|
| `swing_exit_behaviour.py` | What actually ends a swing trade, and how long it takes | ROADMAP, *"What the exits do, measured"* |
| `swing_rail_sweep.py` | Does holding for 30 days buy anything the move has not already given | Booked item 3 |
| `swing_net_of_costs.py` | The same comparison net of what a round trip really costs | Booked item 3 — the column that decided it |
| `correlation_window.py` | Does the correlation window explain why the cluster cap never binds | M58b, booked item 2 |
| `sizing_model.py` | What would changing position size actually buy | *"Not booked, and why"* |
| `when_do_trades_land.py` | When can the current book produce closed trades at all | The 14–17 September burst |
| `actual_cost_to_risk.py` | What a round trip costs as a fraction of the risk taken | The 3.8% that overturned the sizing case |

## The caveat that applies to all of them

**Every replay runs over the ten symbols held on 8 August.** That is a selected
set — names this strategy chose and that survived to still be held — so the
figures are good enough to rank options against each other and **not good enough
to size a book on**. The relative comparisons inherit the bias too, just less of
it.

That limitation disappears the moment there are real closed trades, which is
what the mid-September time-stop burst delivers and what M58's diagnostics read.
**Re-run `swing_rail_sweep.py` and `swing_net_of_costs.py` against those trades
before revisiting the time stop** — the whole reason booked item 3 was declined
is that it was measured on this replay rather than on evidence.

## The two live-broker scripts, which are not replays

Both talk to the paper account. Neither places, cancels or modifies an order.

| Script | What it answers |
|---|---|
| `probe_alpaca_splits.py` | What Alpaca actually reports about a split — `old_rate`/`new_rate`, the date fields, whether the symbol filter works server-side, and how often `target_symbol` is missing. Written because the roadmap's own instruction for M39 was to measure the broker rather than reason about it. Its findings are in ROADMAP, M60 |
| `exercise_m54.py` | Whether M54's broker-failure refusal actually works against a **real** SDK failure, using deliberately invalid credentials. Its tests use fakes that raise on command, which proves the handler catches an exception and not that the real failure is the shape it expects. Writes to a scratch directory, never the live one. Findings in ROADMAP, M61 |
| `probe_feed_entitlement.py` | Whether SIP is genuinely paid for, or just the free tier's historical access. Only a request for RECENT data separates the two — a successful query for last week's bars proves nothing |
| `probe_market_data.py` | What running on IEX rather than the consolidated tape costs in ATR, and therefore in position size. Uses the application's own `compute_atr`, so it measures what the app would do rather than a reimplementation. Findings in `docs/MARKET_DATA_FINDINGS.md` |
| `capture_split_state.py` | One symbol's position and resting orders before and after a corporate action, so the two can be diffed. Nothing recovers the pre-split state after the fact |

`exercise_m54.py` is worth re-running whenever the Alpaca adapter changes: it is
the only thing that has ever exercised that rail end to end, and it costs
nothing — no market, no capital, no rule change.

## One correction worth knowing about

`swing_net_of_costs.py` charges **0.038R** a round trip. An earlier pass used
0.132R, taken from the daily report's refusal rows — which are candidates the
cost rail **rejected** for being too small, not the trades actually taken. That
error made trailing stops look catastrophic when they are roughly break-even.
`actual_cost_to_risk.py` is what established the true figure, from the app's own
`CostModel` over the positions actually held.
