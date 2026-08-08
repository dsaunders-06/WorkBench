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

## One correction worth knowing about

`swing_net_of_costs.py` charges **0.038R** a round trip. An earlier pass used
0.132R, taken from the daily report's refusal rows — which are candidates the
cost rail **rejected** for being too small, not the trades actually taken. That
error made trailing stops look catastrophic when they are roughly break-even.
`actual_cost_to_risk.py` is what established the true figure, from the app's own
`CostModel` over the positions actually held.
