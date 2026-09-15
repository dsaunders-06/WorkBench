# QAT Design Recovery & Design Intent Audit, Annex A: Anomalies Register

**Prepared:** 15 September 2026, at the operator's instruction: "Continue to
flag and capture anomalies along the way, they too will be reviewed once the
audit is fully completed."

**What counts as an anomaly:** a fact the audit found that is unexpected,
unexplained, or contrary to what a record or document says. Some are
defects, some are gaps in the evidence, some are behaviours nobody chose.
Claude's own errors are in the error log (CE-nn). Where an anomaly is also
an error, both are cited.

**Status values:**

| Status | Meaning |
|---|---|
| **OPEN** | needs investigation or a decision |
| **HELD** | the operator has held it |
| **DECIDED** | the operator has decided it |
| **CLOSED** | explained or fixed, with evidence |
| **FROZEN** | a known defect, not fixed under the freeze |

**Risk** is what it puts at stake if trading resumes unchanged: **H**, **M**,
**L**.

Nothing listed here has been changed.

## A.1 Safety and the broker

| # | Anomaly | Evidence | Status | Risk | Decision needed |
|---|---|---|---|---|---|
| A01 | **JHX's resting stop did not fill with the price below it** (11 Sep close 39.01; stop 39.39) | IBKR statement; R10 §10.4; R16 §16.1 | **HELD** (operator, 14 Sep) | H | the TWS Orders panel read (R23 D5) |
| A02 | **An exit releases a position's broker stop before the kill-switch check; while tripped, the re-arm cannot replace it.** IAG unprotected about an hour on 9 Sep | `oms.py:731, 745`; CE-017; R10 §10.2 | **FROZEN** (operator: "decide later", 14 Sep) | H | R23 D1 |
| A03 | Two leg-cancel implementations, in opposite order against the kill switch | R5 §5.3 #5; R15 C28 | FROZEN | H (with A02) | with D1 |
| A04 | "Unknown IBKR code → halt" caused 7 of 19 kill-switch trips, none for a real unknown hazard | R14 incident 2; R15 C21 | OPEN | M | Phase 4 |
| A05 | The resting-order scan was wrong 9 times in 10, and each false detection quarantines entries | R10 §10.2 | OPEN | M | Phase 4 |
| A06 | SEK's exit filled while the app held it as rejected (9 Sep) | R10 §10.4 | CLOSED as an event; the handling (M173) is unproven live | M | observe in Phase 7 |
| A07 | Every entry bracket's legs used IBKR's "reduce" OCA type from 19 Aug to 7 Sep. Whether any leg was left resting against sold shares is NOT DETERMINED | CE-047 | CLOSED (fixed 7 Sep); the effect NOT DETERMINED | L now | none |
| A08 | Whether a paper stop fills while the app and Gateway are both closed has never been observed | HANDOFF standing instruction 2 | OPEN | H (bears on A01 and on the suspension) | with D5 |
| A09 | The configuration still says `execution_mode=auto`: a launch would trade | `.env`, read 15 Sep 11:41 | OPEN (standing) | H if launched | the operator, before any launch |
| A10 | The kill switch's reset needs no confirmation; tripping does | R7 #39 (class G) | OPEN | L–M | Phase 4 |

## A.2 The records

| # | Anomaly | Evidence | Status | Risk | Decision needed |
|---|---|---|---|---|---|
| A11 | **TNE's 3 Sep stop-out booked as 60 of 3,051 shares, labelled "target"**; loss understated by 6,937.44 | R13 §13.2; CE-066 | FROZEN (not repaired) | H (evidence) | R23 D4 |
| A12 | The exit matcher logged both shortfalls (TNE 2,991; SEK 951) and explained them away as "likely an adopted position" | the log, 3 Sep 14:51:18 and 9 Sep 14:59:40; CE-066 | FROZEN | M | with D4 |
| A13 | **The one live booking reversal was wrong-signed**: A2M tracked −9,636 against 9,636 held, 12:40–13:17 on 4 Sep | the log; CE-046; R10 correction note | CLOSED (fixed 14:51 that day); a correct reversal has never run live | M | observe in Phase 7 |
| A14 | The regime is blank on all 12 ledger rows | R5 §5.3 #16; CE-056 | FROZEN | M | Phase 7 prerequisite (R23) |
| A15 | Seven repairs rewrote the ledger; all authorised; only one left a mark in the record itself | R13 §13.5 and its later note | CLOSED (authority traced) | L | the practice going forward (R20 C27) |
| A16 | **The retained log has no lines for 66 minutes on 24 Aug**: Claude's watcher held the file and rotation failed silently | CE-037; R13 §13.6 | CLOSED (cause known, fixed M137); the lines are lost | L | none |
| A17 | The 9 Sep daily report was regenerated twice (stamped "10 Sep 04:48" and "04:53"; the zone is not stated). The superseding reports carry no analyst notes | `daily_reports.md`; `a24f0eb` | OPEN: the authority for the regeneration was not traced | L | review |
| A18 | Two different builds carried the label M165 on 4 Sep | the log; CE-060 | CLOSED (traceable by commit) | L | none |
| A19 | The earnings calendar is built for the US on an ASX book | R5 §5.3 #15; R7 #31 | FROZEN | M | Phase 4 |
| A20 | The promotion scorecard does not filter by market; the Kelly estimator does | R5 §5.3 #19 | FROZEN | L | Phase 5 |
| A21 | The report heading "Autonomy decisions blocked" counts every non-auto-signed row | R7 #59 | FROZEN | L | Phase 5 |
| A22 | The ledger booked costs as a model, not the commission, until 12 Sep | CE-052 | CLOSED (M175 repair) | L now | none |
| A23 | Empty report narratives are dropped without a log line (26 Aug; the weeks ending 4 and 11 Sep) | R11 §11.3 | FROZEN | L | none needed |

## A.3 Trading behaviour nobody chose

| # | Anomaly | Evidence | Status | Risk | Decision needed |
|---|---|---|---|---|---|
| A24 | **The sector cap was not wired until 16:21 on 25 Aug.** That day Financials reached 34.95% of equity against a 30% cap. A wired rail would have trimmed PNI by about half and refused ANZ (derived) | `7ba68ab`; IBKR cost basis; CE-043; R9 correction note | CLOSED (wired 25 Aug); the effect stands | M (history) | none |
| A25 | Two entries in the same second took the book to 11 of 10 (26 Aug) | CE-041 | CLOSED (item 58) | L | none |
| A26 | **The regime's first label after a launch is often an artefact** (20 of 33 ASX runs opened on "recovery", about 3 minutes) | R12 §12.2 | OPEN | M | Phase 4 (R20 C31) |
| A27 | The US VIX below 15 sets the label to low_vol by a fixed rule (12 of 12) | R12 §12.2 | OPEN | M | U3 (the operator) |
| A28 | The regime's 20-bar refit has never run; it refits once per launch | R12 §12.1 | OPEN | L | Phase 5 (C12) |
| A29 | **The cash cap set 18 of 20 entry sizes**, after the risk engine's sizing | R9 §9.2; R15 C18 | OPEN | M | Phase 4 |
| A30 | No entry took its 1% risk budget (0.13–0.70%, median 0.45%) | R9 §9.2 | OPEN (a consequence of A29 and placeholder Kelly) | M | Phase 4 |
| A31 | One position at its whole value filled the aggregate cap and refused every entry (A2M, IAG, JHX) | R16 §16.1 | OPEN | M | Phase 4 |
| A32 | On the record so far, measured half-Kelly would be zero at the 20-trade switch (derived, conditional) | R16 §16.2 | OPEN | M | R23 Phase 7 |
| A33 | Strategy gating ran on a hard-coded default for the first 20 minutes of each session | CE-049 | CLOSED (item 8, 10 Sep) | L | none |
| A34 | Swing decides on the forming intraday bar | R7 #18 | FROZEN | H (strategy integrity) | R23 D2 |
| A35 | The 30-day time stop against the specification's 10 working days | R7 #20; CE-055 | FROZEN | M | R23 D2 |

## A.4 The AI and the configuration

| # | Anomaly | Evidence | Status | Risk | Decision needed |
|---|---|---|---|---|---|
| A36 | The system prompt tells the model "Final trading decisions are made by a human", false in `auto` | `prompts.py:17`; R11 §11.4 | FROZEN | L | with D3 |
| A37 | Three launches were configured for the local model on port 8000; the `.env` now names 1234. Why is NOT DETERMINED | R11 §11.2; R21 U18 | OPEN | L | none |
| A38 | `DGS3MO` and `DGS10` are fetched and shown as regime "drivers" but drive nothing | R15 C11 | OPEN | L | Phase 5 |
| A39 | A feature computation runs on every tick and nothing reads it | R15 C10 | OPEN | L | Phase 5 (REMOVE after authorisation) |
| A40 | The de-lever sweep is off by default with no recorded decision | R7 #36 | OPEN | L | the operator |
| A41 | The force-start button could be armed by a keypress (20 Aug) | CE-062; `session_panel.py:154-168` | CLOSED: `NoFocus` (M107) and a confirmation dialog (M124) | L | none |

## A.5 The development record

| # | Anomaly | Evidence | Status | Risk | Decision needed |
|---|---|---|---|---|---|
| A42 | The 28 Aug ablation's "86% VIX dominance" is confounded; it had been read as the VIX's information share | CE-032; R12 §12.3 | CLOSED (recorded) | M (it framed a deferred decision) | U20, if the operator asks |
| A43 | 37% of the code is prose, and five comments or prompt strings have been found false | R15 C33 | OPEN | M (understanding) | Phase 5 |
| A44 | README and the product description stale since 20 Aug | CE-061 | OPEN | L | outside the audit |
| A45 | The rollback directories beside the install have not been measured (outside the search boundary) | R3 §3.6 | OPEN | L | the operator's permission, if wanted |

## A.6 Count

45 anomalies:

| By status | Count |
|---|---|
| OPEN | 20 |
| FROZEN | 12 |
| CLOSED | 12 |
| HELD | 1 |

The three flagged H that most need the operator:
* A01, JHX's stop;
* A02, CE-017;
* A09, the `auto` configuration, if the app is launched.
