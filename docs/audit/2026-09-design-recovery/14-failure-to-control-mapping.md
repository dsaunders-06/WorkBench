# QAT Design Recovery & Design Intent Audit, R14: Historical Failure → Control Mapping

**Brief §14 ("Distinguish safety from complexity"). DRAFT for Checkpoint B.**
**Prepared:** 14 September 2026. Read-only: nothing in the system was changed.

The brief: "Do not equate complexity with bad design. Some complexity is
justified because QAT has experienced real failures." For each incident it
asks three things: **was the resulting control necessary**, **is the current
implementation proportionate**, and **did the fix introduce secondary
complexity**.

**Sources**
* The log, through `execution_evidence.py` and `incident_episodes.py`
  (`s08-s14-execution-and-incidents/tools/`), and `gate_and_halts.py` (R9).
* The code and commits, cited by hash.
* The error log (CE-nnn) and the drift map (R7 #nn).

The verdicts below are the audit's judgement and are marked as such. Each rests
on the facts in its row. Nothing is recommended for removal (§16 and R20 do
candidates; nothing is changed).

---

## 14.1 The incidents the brief names

| # | Incident (evidence) | Control(s) it produced (commit) | Has the control acted live since? | Necessary? | Proportionate? | Secondary complexity? |
|---|---|---|---|---|---|---|
| 1 | **Duplicate transmission**, 24 Aug. IBKR's working states were missing from the status map, so a transmitted order still read as pending and the retry sweep resent it every 60 s: 4× TNE and DXS, about AUD 800k of exposure, 16 orphaned legs; unwound for −2,776 (CE-003) | The status map corrected, and an OMS set of transmitted ids that refuses a second send (M139, `oms.py:885-904`) | The CE-003 retry pattern recurred **249 times** and the gate's status rail blocked each one. The id set has **never fired** | **Yes.** It reached the broker at four times the intended size | **Yes.** The root fix (the map) and one independent guard the OMS owns; small | **Little.** The id set lives in memory only, which is sound because pending orders do not survive a restart either |
| 2 | **Staged / untransmitted TWS order**, 3 Sep. TWS held a 790-share BHP order on its 500-share precautionary limit; the app booked 790 against a broker holding none; reconciliation tripped the switch (CE-005) | An executed-quantity field; IBKR rejections heard and classified, and a **reversal of the booking** on rejection (`ca7cae8`, `8316a12`, 3 Sep night); an Error 383 audit; `broker_max_order_shares`, left unset. **Booking at transmission was kept** by the operator's choice (AE-28, "Drop Task 3") | **Not in time for the next day.** The build running on 4 Sep (M164, built 3 Sep 17:00) predated all of it. A2M's five cancelled sells were booked, and reconciliation read tracked −38,544 against 9,636 held and tripped the switch at 10:25. From M165 (12:27): 27 rejections classified, **1 reversal** (A2M, 12:40) | **Yes.** A phantom position | **Partly** (audit's judgement). The reversal repairs a booking made too early; the root, booking before the broker confirms (R7 #42), remains | **Yes, and it caused incidents.** The rule "an unrecognised order-scoped IBKR code halts the account" (`8316a12`, AE-28 "Unknown → serious → halt") produced **7 of the 19 kill-switch trips** (4 Sep ×2, 9 Sep ×5). Four were IBKR's notice that the app's own orders carried no time-in-force, which `e5b16ca` (9 Sep, M173) called "a code defect after all". Three were cancels of a leg IBKR had already cancelled (10148, reclassified by `77d5485`, M172). One of them disabled IAG's re-arm (CE-017). SEK's exit filled while the app held it as rejected (R10 §10.4) |
| 3 | **Reconciliation mismatch**: 6 trips, 24 Aug–4 Sep | The rail itself (first build, P §20.I); the in-flight tolerance for working buys (M160, `f051c2f`, 31 Aug); the position-anomaly store that can "explain" a known divergence | **6 trips, every one the app's own record diverging, never the broker behaving unexpectedly** (`incident_episodes.py`): **TNE** 24 Aug (the duplicate unwind); **LOV** 26 Aug, a target fill only partly absorbed (54 polls, tracked 2,843 against 0; the ledger's "unabsorbed remainder" repair row); **SEK and WOW** 26 Aug, the app's own fills absorbed again as "foreign", tracked double; **JHX** 31 Aug, a partial fill in flight (then M160); **BHP** 3 Sep, staged (incident 2); **A2M** 4 Sep, cancelled sells booked (incident 2). None since 4 Sep | **Yes.** It caught every one of the app's own booking errors before they compounded | **Blunt** (audit's judgement). One symbol's divergence halts the whole book, and each trip needed the operator's reset | **Some**: the in-flight tolerance and the anomaly store. The rail has been the backstop for defects elsewhere, chiefly booking at transmission (3 of 6) |
| 4 | **Incorrect fill prices**: records carried the price an order was sized at, not the fill; the ledger's costs were the fill basis, not the commission (M175) | Mid-session correction from IBKR's executions; startup correction from IBKR's average cost, converted out of commission (`signal_bridge.py:532-631`); `price_source` stamps; the M175 repair script, applied 12 Sep | Mid-session 2, startup 8 (7 symbols). The repair moved the ledger's net P&L from −4,065.73 to **−3,495.02**, which the ledger now sums to | **Yes.** Prices feed P&L, R-multiples, the Kelly inputs and the promotion score | **Heavy** (audit's judgement): three correction paths for one root, recording a price before the fill exists | **Yes**: the commission-inclusive conversion, the stamps, a one-off repair script that rewrote ledger records (R13 inventories them) |
| 5 | **Corporate-action risk**: the MNST loss in the US era (R7 #50) | M39: detection, entry refusal (OMS G4), re-arm deferral, stop adjustment. Shadow mode; closed by decision 10 Sep | **Never acted.** IBKR supplies no announcements, so detection is unsupported on the live broker (investigator 3, F.7). 0 log lines | The hazard is real (a split mis-prices a resting stop) | **No effect on this broker** (fact). The module cannot detect anything on IBKR | **Yes**: three hooks into the OMS and bridge for a control that cannot fire |
| 6 | **Orphaned protective orders**: 24 Aug (the duplicate unwind left 16 GTC legs, CE-003); 4 Sep (A2M sold while its legs rested) | The resting-order scan and quarantine (`cedb55e`, 24 Aug), cancel behind an off-by-default flag (AE-26); the manual close's own leg cancel (`ed129d9`, 2 Sep); **the autonomous exit cancels legs before selling** (`e0c780d`, 7 Sep) | Scan: **10 detections, 1 real** (A2M, 4 Sep); **9 false positives**, all at the moment of an entry (the entry's own working parent, or its own STP and LMT counted twice). Exit leg release: 4 times on 9 Sep (IAG, SEK) | **Yes** for detection; A2M's orphan was real | **No** for the scan's precision (fact: 9 of 10 false). Each false positive quarantined its symbol against new entries until three clean scans (COH's lasted 15 minutes, 10:29–10:44 on 10 Sep). It cannot remedy a real orphan (outstanding item 2) | **Yes, and it is the live defect.** The exit's cancel-first ordering (`e0c780d`) was approved on the claim that a failed exit "self-heals" through the re-arm, which the kill switch disables: **CE-017**, IAG unprotected about an hour on 9 Sep. There are now two leg-cancel implementations with different tests for "gone" |
| 7 | **Kill-switch behaviour**: before 25 Aug the switch lived in memory and a restart cleared it silently (`kill_switch.py:31-37`); 9 Sep, five trips in one session and a deadlock with the re-arm (CE-017) | Persistence across restarts (`5e5c726`, 25 Aug); confirmation on trip (`fada322`, 25 Aug); the HALT class (incident 2); 10148 reclassified (M172); explicit TIF on every order (M173) | Persistence: **17** restores at launch. 19 trips, none from the loss limits | **Yes** (persistence) | Persistence, yes. Reset still needs no confirmation (R7 #39) | **Yes.** The switch blocks every sign-off, protective re-arms included, and does not block an exit's leg release (CE-017). Its trip sources grew to include broker-code classification, which caused most trips in September |
| 8 | **Ledger and commission discrepancies**: 24 Aug manual unwind sells absorbed as impossible closed trades (the backup `closed_trades.csv.bak-20260824-152809-PRE-IMPOSSIBLE-TRADE-REPAIR` records the repair); 26 Aug LOV unabsorbed remainder; the TNE 60-share remnant; M175's fill-basis costs | Repair scripts (`scripts/repair_*`); `audit_closed_trades` (no caller in the app, R5 §5.3 #18); the commission auditor (M175) | `COMMISSION VERIFIED` **never logged** (outstanding item 3). Repairs applied by hand-run scripts | **Yes** for the evidence the strategy is judged on | **Unproven**: the check that would catch the next discrepancy has not yet run on a real order | **Yes**: repaired and synthetic records now sit in the ledger (TNE remnant, LOV repair row), inventoried in R13 |

## 14.2 Two further incidents the records show

| # | Incident | Control | Since | Assessment |
|---|---|---|---|---|
| 9 | **Two entries in the same second**, 26 Aug. WOW and SEK were signed 173 ms apart, each against a book of nine. The book reached eleven, and the count (refusing at `>=`) cost 1,036 refusals on 27 Aug (R9, R16 §16.3 c) | Transmitted orders count as committed exposure (`72191a9`, item 58, 27 Aug) | Not recurred | Necessary; small; no secondary complexity found |
| 10 | **The app's own fills treated as foreign**, 26 Aug. The broker's ids for WOW and SEK were not recognised as the app's, so their fills were absorbed a second time (R10 §10.2) | Orders aliased under the broker's id (item 56, 31 Aug, `oms.py:1091-1103`) | No reconciliation trip of this kind since 26 Aug | Necessary. It adds identity machinery (app id, permId, aliases, a resolved-id event) that investigator 3 found has untested paths (§4) |

## 14.3 What the mapping shows

1. **Almost every control here followed a real failure, and most were
   necessary.** The complexity is largely earned (brief §14's own caution).
2. **One design choice sits under many incidents: booking at transmission.**
   The order is booked before the broker confirms it (R7 #42, kept by the
   operator on 3 Sep, AE-28). It is the common root of:
   - three of the six reconciliation trips (26 Aug, 3 Sep, 4 Sep);
   - the reversal machinery;
   - three price-correction paths and a repair script;
   - the aggregate-cap trap's A2M route (R16 §16.1).
3. **Fixes have produced the next incidents.** Four chains:
   - The "unknown code → halt" rule from 3 Sep caused seven trips. Four came
     from a missing time-in-force in the app's own orders, three from benign
     cancels.
   - One of those trips, together with the 7 Sep cancel-first exit, left IAG
     unprotected (CE-017).
   - The resting-order scan from 24 Aug is right about 1 time in 10.
   - Each fix was reasonable where it was made. The interactions were not
     checked (CE-017's "to avoid").
4. **Controls reached the account mid-session, one step behind the
   incidents.** The 3 Sep fixes were not in the build that traded on 4 Sep
   (R10 §10.4 item 4).
5. **The controls that would catch the next discrepancy have not run.**
   Commission verification, the time-in-force fix on a real exit, and the
   manual-close path are all code only (R10 §10.3).
