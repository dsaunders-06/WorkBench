# QAT Design Recovery & Design Intent Audit, R13: Data & Evidence Integrity Assessment

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §11 ("Audit data and evidence integrity"). Final, for the operator's review at Checkpoint B.**
**Prepared:** 15 September 2026. Read-only: **no record was repaired**. The
brief: "Do not silently repair historical records." Every defect below is
reported and left as it stands.

**Sources**
* **The broker's record:** the IBKR activity statement for 24 Aug – 11 Sep
  (archived 12 Sep, `Documents\QAT-audit-evidence\2026-09-12\broker-statements\`).
  Its text was extracted into the session scratchpad only. The statement and
  its text are not committed.
* **The app's records:** `closed_trades.csv` and its 12 backups,
  `open_position_entries.json`, `decision_journal.csv`, `risk_decisions.csv`,
  the log; 27 backup files in all.
* **Tools** (read-only, `s11-evidence-integrity/tools/`):
  - `ledger_vs_broker.py`: every broker execution against the ledger and the
    open records. Its parse is checked against the statement's own totals: all
    symbols reconcile within rounding;
  - `ledger_versions.py`: every retained version of the ledger, in order, and
    what changed between them;
  - from R12, `regime_evidence.py` §0 (the log's coverage).
* **The operator's words** for who authorised each repair (transcripts
  `f2d132cc`, and the extracts in `stage4/tools/`).

---

## 13.1 The evidence chain

The brief's chain: Market Data → Signal → Decision → Order → Fill → Position
→ Exit → Ledger → Performance.

| Link | What records it | Kept? | Checked against the broker? |
|---|---|---|---|
| Market data | nothing but log lines (yfinance, 20-minute delay). No bar or tick store | **No.** A decision's inputs cannot be replayed from QAT's own records; a re-fetch gets the vendor's data as adjusted since | — |
| Signal | **not recorded as such.** The strategy engine logs deployment and eligibility changes, not signals (`strategies/engine.py`). A buy signal is visible only as the risk evaluation it caused; the bridge logs an exit signal only when the minimum hold holds it back (`signal_bridge.py:1388`) | No | — |
| Decision | `risk_decisions.csv`, every evaluation (4,958 rows); `decision_journal.csv`, changes of verdict only (477 rows) | Yes | — |
| Order | the journal (proposed, signed, rejected), the log, the broker | Yes | **yes**: every ASX-era transmission is on the statement |
| Fill | the log (`execDetails`), `absorbed_fills.json` (30-day retention), the broker | Partly (30 days) | **yes** (13.2) |
| Position | `open_position_entries.json` (current state only, overwritten), the broker | Current only | **yes**: 9 of 9 match (13.2) |
| Exit | the journal, the log, the ledger | Yes | yes |
| Ledger | `closed_trades.csv` (12 rows, 8 positions), with 12 backups | Yes, with history | **yes: 7 of 8 positions match; 1 does not; 2 round trips are missing** (13.2) |
| Performance | `equity_curve.csv` (the broker's own account value, every 60 s); the reports and scorecards, computed from the ledger | Yes | The equity curve is the broker's figure. **Everything computed from the ledger inherits 13.2** |

## 13.2 The app's records against the broker's

`ledger_vs_broker.py`, statement 24 Aug – 11 Sep (36 executions):

**Seven of the eight ledger positions match the broker exactly.** LOV, RHC,
PNI, A2M, IAG, SEK and BHP match on:
* quantity;
* entry price and exit price;
* **costs, equal to IBKR's commission to the cent**;
* net P&L within 4 cents of IBKR's realised P&L.

**All nine open positions match too.** Each entry record's price equals the
broker's fill.

**The rest do not:**

| Item | The ledger | The broker | Difference in realised P&L |
|---|---|---|---|
| **TNE, bought 24 Aug 15:19:36, stopped out 3 Sep 12:31:40** | 60 shares; net −139.17; exit reason "target" | 3,051 shares; realised −7,076.61 | **ledger understates the loss by 6,937.44** |
| DXS round trip, 24 Aug (four duplicate buys of 17,067, unwound) | nothing | realised −2,888.46; commission 702.16 | −2,888.46 |
| TNE's first lot, 24 Aug (four duplicate buys of 3,076, unwound) | nothing | realised +112.10; commission 703.30 | +112.10 |
| **Total realised** | **−3,495.02** | **−13,208.84** | **−9,713.82**. The three lines above sum to −9,713.80; the 2 cents are the rounding of the printed rows |

**Why TNE is 60 shares** (the log and the code, 3 Sep):
1. TNE's stop filled at 12:31:40 while the app was not running. At the
   14:50 launch the broker no longer held TNE, so no lot was restored for it.
2. The missed-exit replay rebuilt the lot from **one** missed fill:
   `quantity=fill.quantity` (`signal_bridge.py:497-504`). `missed_fills`
   returns IBKR's per-execution fills uncollapsed (`oms.py:1892-1909`), while
   the absorption collapses them to one per order (`oms.py:2116-2121`).
3. The absorption then recorded the whole order: "BROKER-SIDE FILL absorbed:
   sell 3051 TNE.AX at 30.69". The ledger answered "**Sell of 3051 TNE.AX
   exceeded tracked entries by 2991 - unmatched portion ignored**" (log,
   3 Sep 14:51:18).

So the lot was sized to one partial execution, 60 shares, and 2,991 shares
were dropped (derived from the code and the log; which execution carried 60
is not recorded, because the app was not running).

**Why it says "target".** The same startup path has no stop level for a
symbol no longer held. An unknown stop is labelled "target"
(`oms.py:2433-2449`, investigator 4 §2.6). The stop was 30.69: Claude's
report of the broker's orders on 24 Aug at 15:26 ("SELL STP 3,051 @ 30.69"),
and the ledger row's own risk per share (32.94926 − 2.25926 = 30.69). The
fill averaged 30.6858.

**Why the two 24 Aug round trips are missing.** They are the unwind of the
duplicate transmission (CE-003).
* **Operator-directed:** "yes, flatten them" (14:23), "do as suggested"
  (14:32, DXS in tranches), and the operator's own "Sell order placed" (14:42).
* **Sent outside the app**, by `flatten_positions.py` and
  `unwind_in_tranches.py` and in TWS. So the app's journal and ledger hold no
  record of them.
* When TNE's sales came back into the app at the 15:18 relaunch, they were
  matched against the lot opened at 15:19:36. That made seven rows that
  "closed before they opened". Those rows were removed by
  `repair_impossible_closed_trades.py`, on the operator's "yes" to "Shall I
  stop the app and repair the ledger?" (15:26).
* DXS's sales never reached the app at all. No app line mentions DXS after
  its fourth buy at 14:07:51.

The remediation's net cost, −2,776.36, exists only at the broker.

## 13.3 The brief's fourteen checks

| Check | Finding | Evidence |
|---|---|---|
| **Missing fields** | Ledger: regime label, probability and scalar blank on 12 of 12; `earnings_at_entry` and `held_through_earnings` blank on 12 of 12; `reference_price` and `entry_slippage` blank on 11 of 12 (only BHP has them). Open records: `price_source` blank on 5 of 9 (WOW, JHX, TWE, TAH, COH) and `reference_price` blank on 5 (ANZ, ASX, BOQ, SUN, WOW). The journal's OMS rows leave market, session, equity and cash blank (investigator 4 §2.13). Exit rows in `risk_decisions.csv` carry no regime, by design (R12 §12.3 5) | `ledger_vs_broker.py` §4 and §5 |
| **Repaired records** | Seven repairs rewrote the ledger or the open records after the event (13.5). All seven left a backup; only one left a mark in the record itself | `ledger_versions.py` |
| **Retroactively modified records** | Beyond the repairs, the app amends its own rows: A2M's exit 6.51 → 6.47 and IAG's 7.68 → 7.67 on 9 Sep, and the startup price correction rewrote open records' entry prices. The 9 Sep daily report was regenerated twice (appended, marked "REGENERATED") | `ledger_versions.py`; `daily_reports.md` |
| **Missing regime metadata** | 12 of 12 ledger rows (R12 §12.3 5; restored lots never carry it, R5 §5.3 #16) | — |
| **Incorrect entry prices** | **None today:** all 8 closed and 9 open entry prices equal the broker's fill. Until the 10 and 12 Sep repairs they were the order's reference price or IBKR's commission-inclusive average (e.g. PNI 17.9258 against a fill of 17.91; BOQ's open record 6.3856 = 86,754.96 ÷ 13,586) | 13.2; 13.5 |
| **Incorrect exit prices** | None today (TNE's 30.6858 is the broker's average). A2M and IAG were corrected by the app on 9 Sep | 13.2 |
| **Incorrect commissions** | **None on 7 positions** (equal to IBKR's to the cent, since 12 Sep). TNE's costs cover 60 shares (3.36 against 170.85). Before 12 Sep the costs were the fill basis, not the commission (PNI 137.38 against 87.57). **The commission check against IBKR has never recorded a result**: `commission_checks.csv` does not exist in the data folder (outstanding item 3) | 13.2; data folder listing |
| **Incorrect slippage** | Not measurable for 11 of 12 closed trades: no reference price was recorded for positions entered before the field existed (M156/M157). The ledger's costs exclude modelled slippage (investigator 4) | ledger blanks |
| **Duplicate trades** | At the broker: 4 × TNE and 4 × DXS on 24 Aug (CE-003). In the ledger: SEK's exit recorded twice on 9 Sep (2,978 and then 2,027 shares against 2,978 held), repaired the same evening | statement; `ledger_versions.py` |
| **Partial fills** | LOV's exit reached the ledger as 4 partial rows totalling 374 of 3,217 shares; a repair row added the other 2,843. **TNE's exit lost 2,991 shares to a lot sized from one partial execution** (13.2). IBKR marks most executions "P" | ledger; statement codes |
| **Remnant positions** | **None at the broker** on 11 Sep: the app's 9 records match the broker's 9 positions. The ledger's 60-share TNE row is **not** a remnant of the 24 Aug unwind, as the capability document, R14 and R16 called it: it is the 3 Sep stop-out of the swing entry, truncated (13.6) | 13.2 |
| **Synthetic / repaired records** | LOV's 2,843-share row, written by a repair script; its exit reason says so ("target (ledger repair 26 Aug - unabsorbed remainder)"). The seven impossible TNE rows of 24 Aug (removed). The US-era records, retired to `docs/archive/alpaca-era/` (in git) on 21 Aug | `ledger_versions.py` |
| **Audit records generated by repair scripts** | The scripts leave **backups** (27 in the data folder) and print their before-and-after to the Claude Code session (in the transcripts). Only LOV's row and the regenerated reports carry a mark in the record. The broker orders sent by the two unwind scripts left **no record in the app** | 13.5 |
| **Differences between broker and app** | Realised P&L −13,208.84 at the broker against −3,495.02 in the ledger (13.2). Open positions agree | 13.2 |

## 13.4 What each issue affects

● affects; ○ does not; ◐ partly.

| Issue | Operational correctness | Risk | Performance measurement | Strategy validation | Auditability | Promotion evidence |
|---|---|---|---|---|---|---|
| TNE truncated to 60 shares; "target" for a stop-out | ○ (positions and stops were right at the broker) | ○ (the risk rails read the broker) | ● (loss understated 6,937.44; one stop counted as a target) | ● (a swing stop-out misrecorded) | ● | ● (the scorecard and the Kelly estimator read the ledger) |
| 24 Aug round trips absent | ○ | ○ | ◐ (the ledger does not reconcile with the account) | ○ (not strategy trades: the defect's unwind) | ● (a −2,776.36 loss with no app record) | ○ |
| Missed-exit replay sizes the lot from one execution (code; any exit that fills in pieces while the app is closed) | ○ (records only: positions are read from the broker) | ○ | ● | ● | ● | ● |
| Regime and earnings fields blank | ○ | ○ | ◐ | ● (results cannot be analysed by regime or by earnings) | ● | ◐ |
| No reference price, so no slippage, on 11 of 12 | ○ | ○ | ● (execution cost unknown) | ◐ | ● | ○ |
| `price_source` blank on 5 open records (derived, not observed) | ○ (the prices are right) | ○ | ○ | ○ | ● (the record does not say how it got its price) | ○ |
| Commission check never run | ○ | ○ | ◐ (the costs happen to match, verified here by hand) | ○ | ● | ○ |
| Repairs with a backup but no in-record mark | ○ | ○ | ○ (the results now reconcile) | ○ | ● | ○ |
| LOV partial absorb and repair row | ○ | ○ | ○ (now reconciles) | ○ | ◐ (one exit is five rows, one synthetic) | ○ |
| SEK recorded twice (repaired 9 Sep) | ○ | ○ | ○ (now reconciles) | ○ | ◐ | ○ |
| No stored market data or signals | ○ | ○ | ○ | ● (no decision can be replayed from QAT's own records) | ● | ◐ |
| The log's 66-minute hole, 24 Aug | ○ | ○ | ○ | ○ | ◐ (the journal and risk records cover it: 13.6) | ○ |

**Effect on R16's Kelly finding.** R16 applied the estimator to the ledger's
eight positions. With TNE at its broker loss:
* the average loss rises from 3,809.54 to 4,965.78 (losses 29,794.67 ÷ 6),
  against an average win of 9,681.10;
* the ratio falls from 2.54 to 1.95, and half-Kelly's break-even win rate
  rises from 28.2% to 33.9%, against a win rate of 25%.

Measured Kelly is still zero, now by a wider margin (derived, the estimator's
arithmetic as in R16).

## 13.5 Every retroactive change to the ASX-era ledger

In the order of the ledger's content (`ledger_versions.py`; the backup names'
stamps mix UTC and local time, so the files' modified times give the order).

| When | Change | By | Authority | Backup / mark |
|---|---|---|---|---|
| 21 Aug | The US-era records retired from the live files to `docs/archive/alpaca-era/` | `retire_alpaca_era.py` | **operator-directed**: "any reference to or use of data arising from the Alpaca test in the app is no longer required. You can keep it … in offline logs" | backups `*.bak-20260821-*`; the archive is in git |
| 24 Aug 15:28 | 7 TNE rows that "closed before they opened" removed (730 shares, stored net −266.28) | `repair_impossible_closed_trades.py` | **operator-approved**: "yes" (15:26) to "Shall I stop the app and repair the ledger?" | `…-PRE-IMPOSSIBLE-TRADE-REPAIR` |
| 26 Aug | LOV's exit: 374 of 3,217 shares absorbed in 4 rows; a 5th row for the other 2,843 written by a script | `repair_lov_partial_absorb.py` | approved in general terms that day ("Proceed as suggested"); **not matched message to repair** | `…-PRE-LOV-REPAIR`; the row's exit reason |
| 27 Aug | The repair row had been written with surplus columns; realigned | not identified | not identified | `closed_trades.bak-preRowRepair-52596.csv` |
| 9 Sep 13:19 → 14:59 | The app amended A2M's exit (6.51 → 6.47) and IAG's (7.68 → 7.67) | the app (exit-price correction) | — (automatic) | the app's own backup, `…-20260909-132411` |
| 9 Sep 17:18 | SEK's double record (2,978 + 2,027 shares) reduced to one row | a repair run (backup `…-repair-20260909-071800`, stamped in UTC) | approved in general terms ("yes start item 3"); **not matched message to repair** | that backup |
| 10 Sep 14:52 | Entry prices restored to full precision (stored at 4 decimals) | `repair_entry_price_precision.py` | **operator-directed**: "apply the rebuild, build the detection, and use the P&L precision that is most accurate" | `…-precision` |
| 12 Sep 10:52 | Entry prices moved to the true fill and costs to IBKR's commission, on all 12 rows (M175); net −16,087.64 stored before, −3,495.02 after (the older sum had one blank row) | `repair_fill_basis.py` | **operator-approved** step by step ("do in the order suggested", "yes", "yes") | `…-fill-basis-*` |

> **Later note, 15 Sep (back-fill).** The three gaps in the Authority and
> By columns are now traced (§13.7):
> * 27 Aug: the row was realigned by Claude's `repair_collapsed_row.py`,
>   after "do it now";
> * LOV and SEK were each approved by a specific operator message.
>
> Every one of the seven repairs now has a traced authority. SEK's double
> record came from the same defect as TNE's shortfall (CE-066).

The open records (`open_position_entries.json`) have their own six backups.
Their prices were IBKR's commission-inclusive average cost until 12 Sep. The
fill-basis repair stamped `price_source: fill` only where the log held the fill
itself (`fill_basis_repair.py:405-416`), 4 of 9. The other five were
re-derived at the next launch from the average cost by formula
(`signal_bridge.py:592-618`), which sets the price and leaves the source blank.
All nine now equal the broker's fill.

## 13.6 Corrections to earlier drafts, and the log hole

* **"The TNE remnant" is wrong.**
  - The 12 Sep capability document called the 60-share row "a 60-share
    remnant" and said the rest left through the 24 Aug clean-up; it flagged
    the label as unverified.
  - R14 (incident 8), R16 (§16.2) and `evidence_chain.py` repeated it as "the
    remnant of the 24 Aug duplicate unwind".
  - The broker shows the unwind ended at 14:50, before the 3,051-share entry
    at 15:19:36, and the stop sold all 3,051 on 3 Sep. The row is a
    **truncated record of a real swing stop-out** (13.2).
  - R16's "without the TNE remnant" arm therefore removes a real trade, and
    its count of exits was wrong: the eight are 2 targets, 3 stops and 3
    signal exits. Correction notes are added to R14 and R16, and the error is
    logged as CE-034.
* **The 24 Aug log hole does not shorten R9's or R10's counts.** From
  10:06:27 to 11:12:37 AEST the log is missing. The records cover that hour:
  - `decision_journal.csv` has 2 rows (TNE buys refused by the per-order cap
    at 10:21 and 10:33);
  - `risk_decisions.csv` has 48 approved TNE evaluations;
  - no sign-off and no transmission.

  R10's order counts are complete, and R9's rail counts come from
  `risk_decisions.csv`. What the hole does lose is that run's log lines: its
  launch, its regime label (R12 §12.6) and any kill-switch or reconciliation
  line. Why the log has the hole is NOT DETERMINED.

  > ⚠️ **Correction, 15 Sep (back-fill; CE-037, CE-038): the cause IS
  > recorded.** Commit `ab5175d` (M137, 24 Aug 11:03) states that the log
  > "froze at 5,242,781 bytes … at 10:06:27 and stayed frozen across a full
  > application restart":
  > * `watch_session.py`, Claude's session watcher, held the file open;
  > * the handler's rotation rename failed (WinError 32), and every record
  >   after it was silently dropped.
  >
  > `qat.log.6` is exactly 5,242,781 bytes and ends at 10:06:27, which
  > corroborates the commit independently. The fixed build's first line is
  > 11:12:37. The audit should have searched the history for that date before
  > writing NOT DETERMINED.

## 13.7 NOT DETERMINED

* Which of TNE's executions on 3 Sep was 60 shares (the app was not running;
  the statement aggregates the order).
* Why DXS's unwind sales never reached the app's absorption (no app line after
  14:07:51 on 24 Aug).
* ~~Who or what realigned the LOV repair row on 27 Aug.~~ **Settled 15 Sep:**
  Claude's scratch script `repair_collapsed_row.py` ("un-collapse the one
  ledger row whose last two columns were written as a list"), run after the
  operator's "do it now" (27 Aug 17:07; transcript `58424b93`).
* ~~Which chat message authorised the LOV repair (26 Aug) and the SEK repair
  (9 Sep) specifically.~~ **Settled 15 Sep:**
  - **LOV:** the operator chose option "1" (15:09:09), "Install M147 and run
    the repair in the same stop/start window". The repair ran at 15:09:36
    (transcript `5cbbd672`).
  - **SEK:** Claude wrote "Close the app and I'll start on the ledger repair"
    (16:05:51). The operator replied "App is closed" (17:15:59), and the
    repair ran at 17:17:58 (transcript `f20567d2`).

  Both are **operator-approved**. §13.5's "not matched message to repair" is
  superseded.
* ~~Why the retained log has no lines from 10:06:27 to 11:12:37 on 24 Aug.~~
  **Settled 15 Sep:** a monitoring script blocked rotation (CE-037; §13.6).
