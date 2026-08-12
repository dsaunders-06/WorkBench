# The G1 window — frozen 12 August 2026

The acceptance gate for W2's replay harness. **Frozen evidence: never
regenerate these files silently.** A gate whose input moves is not a gate.

| | |
|---|---|
| `risk_decisions.frozen.csv` | 2,931 rows, 31 July – 12 August 2026 |
| `open_position_entries.frozen.json` | the book as it stood: 10 positions |
| sha256 of the decisions | `D201799C0296FF70930AD32AD1F319E66987A5C01F60F10B1516631D1DC089F8` |

## How it was taken, and why that mattered

**Copied out with PowerShell, never Bash**, and the reason is sharper than the
standing constraint records. Measured the same minute, same directory:

| file | Bash | PowerShell |
|---|---|---|
| `equity_curve.csv` | 13,811 bytes, 301 rows, dated 27 July | 461,666 bytes, 9,971 rows |
| `risk_decisions.csv` | 1,151,003 bytes | 1,151,003 bytes |

**The sandbox is per-FILE, not blanket.** One file is frozen at 27 July while
its neighbour passes through live. That is worse than a uniformly stale view: a
spot-check on the wrong file *confirms* Bash is fine, and the next file read is
nine thousand rows short with nothing to say so.

## What the window contains

    2,511  Position limit
      269  Cost-to-risk (trade too small)
      106  Aggregate risk-at-stop cap
       45  approved

All classify under `refusals.rail_of`; none fall to `UNCLASSIFIED`.

Decisions per day run 270 · 20 · 540 · 615 · 445 · 708 · 33 · 269 against a
replay's one per symbol per day, which is why the comparison unit is
`(symbol, day) -> the set of rails that bound` rather than a row-for-row match.

## Two symbols excluded, and why

**`AAA` — one row, approved, 12 August 08:53:32 UTC. It is mine.**
`Settings(_env_file=None).data_dir` resolves to the LIVE data directory. Inside
pytest `conftest` sets `QAT_DATA_DIR`, so tests are safe; scratchpad diagnostic
scripts run outside pytest and are not. Two probes written during W2 built a
`RiskEngine` without an explicit `data_dir`, and `AuditLog` wrote here.

One row in 2,931, for a symbol that does not exist, changing no conclusion —
but recorded rather than removed, because the mechanism matters more than the
row and a record with a documented blemish is worth more than one somebody
edited. **Any script run outside pytest must pass its own `data_dir`.**

**`WES.AX` — one row, 6 August, refused by the position limit.** An ASX ticker
in a US book, predating this work. Provenance unknown; excluded from the gate
and left in the record.
