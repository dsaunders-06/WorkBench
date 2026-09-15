# QAT Design Recovery & Design Intent Audit, R10: OMS / Execution / Broker Assessment

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §8 ("Audit the execution / OMS / broker boundary"). Final, for the operator's review at Checkpoint B.**
**Prepared:** 14 September 2026. Read-only: nothing in the system was changed.
**Records:** the log from 19 Aug to 12 Sep (the ASX era), the ledgers, and the
IBKR statement for 24 Aug–11 Sep. Trading has been suspended since 14 Sep.

**Sources**
* The code: investigator 3's report (`stage3/investigator-3-signoff-to-reconciliation.md`),
  re-read where cited.
* The live evidence, from two read-only tools in
  `s08-s14-execution-and-incidents/tools/`:
  - `execution_evidence.py`: how often each execution behaviour ran, when, and
    under which builds;
  - `incident_episodes.py`: what reconciliation and the resting-order scan
    caught.
* The kill-switch and gate tables in R9, from `gate_and_halts.py`.

The brief asks to keep **"code exists"** apart from **"behaviour has been
demonstrated under realistic conditions"**. Here "demonstrated" means a log
line the behaviour writes when it runs, on the IBKR paper account, during a
real ASX session.

---

## 10.1 The path, and where each step is recorded

| Step | What happens | Recorded where |
|---|---|---|
| Signal → order intent | the bridge sizes a candidate; the risk engine approves or refuses | `risk_decisions.csv` (every evaluation) |
| Intent → pending sign-off | the OMS trims to whole shares and the cash cap, and creates `pending_signoff` | journal "proposed"; the cash-cap trim only in the log |
| Pending → sign-off | the autonomy gate (18 rails) or a human in the Blotter; then the OMS's own checks (status, duplicate guard, kill switch, protective re-read, cash) | journal; log |
| Sign-off → transmission | `broker.place_order`, the only caller (`oms.py:1067`). An entry is a market parent, GTC, with STP and LMT children in one OCA group | log "Order signed off and transmitted" |
| Transmission → **booked** | **the ordered quantity is booked at once, whatever status IBKR returned** (`oms.py:1134-1137`), and a fill event is published at the reference price (`oms.py:1164-1208`) | in memory; `open_position_entries.json`; the ledger's open lot |
| Broker acceptance or rejection | IBKR errors arrive asynchronously, are classified IGNORE / WARN / REJECT / HALT (`ib_errors.py:129-150`), and a rejection reverses the booking (`oms.py:1310-1365`) | log "IBKR REJECTED order", "Reversed … of the booking" |
| Fill | absorbed only in the 5-minute reconciliation poll, from IBKR's executions; the entry price is corrected to the fill | log "is filled at the broker", "ENTRY PRICE CORRECTED"; `absorbed_fills.json` |
| Reconciliation | tracked quantity against the broker's, less working buys; an unexplained difference trips the kill switch | log "Broker reconciliation mismatch" |
| Ledger | a lot opens at transmission and closes on the exit fill | `closed_trades.csv` |

## 10.2 The brief's questions

| The brief asks | Answer (code) | Live evidence |
|---|---|---|
| **Where can duplicate transmission occur?** | Guarded three ways: sign-off accepts only `pending_signoff` (`oms.py:882`); a set of transmitted ids refuses a second send (`oms.py:900-904`, in memory only); the gate blocks any order not pending (`gate.py:125-126`). The retry sweep still re-evaluates transmitted orders every minute, and aliased ones twice (investigator 3, A) | The CE-003 retry pattern recurred **249 times** and was blocked every time by the gate's status rail ("order is not pending sign-off (status=transmitted)", R9). The transmitted-id guard has **never fired** |
| **Where can an order be recorded as a position before the broker confirms it?** | **At sign-off, always** (`oms.py:1134-1137`). The operator kept this on 3 Sep and chose a reversal on rejection instead (AE-28) | Three times it put the app's record wrong: **3 Sep** BHP 790 booked, never transmitted (CE-005); **4 Sep** five A2M sells booked that IBKR had cancelled (tracked −38,544 against 9,636 held); **26 Aug** the app's own WOW and SEK fills absorbed a second time as "foreign" (tracked double). Each tripped the kill switch through reconciliation |
| **Where can broker-side staged or untransmitted orders occur?** | At the broker's own precautionary settings, which the API cannot read: a share-count limit (500 on 3–4 Sep), and an order without market data (IBKR code 354 on 4 Sep). Controls: an executed-quantity field (`adapter.py:23-31`), the Error 383 audit, and `broker_max_order_shares`, **unset** | Error 383 six times on 3–4 Sep. BHP staged on 3 Sep. On 4 Sep A2M's sell was refused on size or TIF 11 times in 3 h 22 min before one filled (13:42:33) |
| **Where is the fill price obtained?** | At transmission the record carries the **reference price** (the delayed feed's last close). The fill's price arrives later: in the reconciliation poll from IBKR's executions, or at startup from IBKR's average cost converted out of its commission (investigator 3, C, D) | Mid-session corrections 2 (31 Aug, 10 Sep); startup corrections 8 (7 symbols, up to 12 Sep). The 12 Sep ledger repair (M175) moved net P&L from −4,065.73 to −3,495.02; the ledger now sums to **−3,495.02** (`evidence_chain.py`) |
| **Can application prices differ from broker prices?** | Yes, by design: sizing and the first record use a 20-minute-delayed price; IBKR fills at market | COH 10 Sep: announced 136.54, filled 135.736 (−58.9 bp). JHX 31 Aug: referenced 41.59, recorded fill 41.9185 (`open_position_entries.json`). Quantified across all trades in R13 |
| **How are orphaned orders detected?** | The resting-order scan compares resting legs with what the book justifies, every poll (`oms.py:2579-2758`) | **10 detections: 1 real, 9 false positives.** The real one: A2M's legs left resting on a flat symbol on 4 Sep. The other nine were all at the moment of an entry: the entry's own working parent, or its own STP and LMT pair counted as two, read as unjustified (`incident_episodes.py`) |
| **How are they handled?** | Quarantine the symbol against new entries until three clean scans or an operator clear. **Never cancel**: `resting_order_cancel_enabled` is off (outstanding item 2) | 4 quarantines logged as lifted |
| **How are protective stops established?** | In the entry bracket: STP and LMT, GTC, OCA type 1, at the broker, so they outlive the app. Every buy gets a stop (`engine.py:226-228`) | Every launch from 25 Aug read "all carry a stop resting at the broker", except two on 9 Sep ("9 of 10", IAG) |
| **How are they re-armed?** | At startup and every 300 s: a held position with no resting STP gets a proposed STP or OCA at its entry levels, signed by the gate even with the market closed (investigator 3, F.3) | **23** protective orders came to rest after sign-off, 9 symbols, 1–9 Sep |
| **How does the kill switch interact with broker-side protection?** | A trip does nothing at the broker; resting legs stay. It blocks the re-arm's sign-off. It does **not** block an exit's release of legs, which runs first (CE-017). The manual close refuses before touching the broker | 9 Sep: IAG's legs cancelled at 11:21:46; the switch tripped in the same second; the re-arm was blocked until the operator reset at 12:20 (CE-017) |
| **Is every execution path covered by the same controls? Do exits and entries follow equivalent safety paths?** | **No.** Sells skip gate rails 10–17, the governor, the cost rail, the per-order cap, the corporate-action gate and the resting-order quarantine (investigator 3, H). The autonomous exit and the manual close release legs in **opposite orders** relative to the kill-switch check. There are two leg-cancel implementations with different tests for "gone" (R5 §5.3 #5) | Only the autonomous exit has run live (below) |
| **Which paths are proven live, and which remain theoretical?** | — | 10.3 |

## 10.3 Proven live, or code only

"Last build" is the last build under which the behaviour logged. **The
deployed build, M175, has never transmitted an order.** It ran once, on
Saturday 12 Sep, with no session. **M174 transmitted none either:** its only
execution event was absorbing BHP's stop fill.

| Behaviour | Live runs (19 Aug–12 Sep) | Last | Status |
|---|---|---|---|
| Entry (bracket), signed by the gate | 26 sign-offs, 18 symbols, 8 days | 10 Sep, M173 | **proven** |
| Entry confirmed filled after "transmitted" | 2 | 10 Sep, M173 | **proven** |
| Entry price corrected to the fill | 2 mid-session, 8 at startup | 12 Sep, M175 (startup) | **proven** |
| Protective stop filled at the broker, absorbed | BHP, 11 Sep | M174 | **proven** (once) |
| Target filled at the broker, absorbed | LOV 26 Aug, RHC 27 Aug | 27 Aug | **proven** (LOV only partly absorbed: R14) |
| Signal exit (market sell), signed by the gate | **13 orders, 3 symbols**: A2M ×11 on 4 Sep, IAG and SEK on 9 Sep | 9 Sep, M172 | **proven, narrowly**. Never under the M173 time-in-force fix (outstanding item 1) |
| Exit cancels its protective legs first | 4 (IAG ×3, SEK) | 9 Sep, M172 | **proven**, and its hazard with it (CE-017) |
| Exit refused because a leg still rested | 1 (IAG) | 9 Sep | **proven** (once) |
| Protective re-arm resting after sign-off | 23, 9 symbols | 9 Sep, M172 | **proven** |
| Rejection classified; booking reversed | 27 classified; **1 reversal** (A2M, 4 Sep 12:40) | 9 Sep | **proven** (the reversal once) |
| Reconciliation mismatch trips the kill switch | 6 episodes | 4 Sep, M164 | **proven** |
| Missed executions replayed at startup | 3 | 9 Sep | **proven** |
| Resting-order orphan detection and quarantine | 10 (1 real) | 10 Sep | **proven**, with a high false-positive rate |
| Kill switch survives a restart | 17 "RESTORED AT LAUNCH" | 10 Sep | **proven** |
| IBKR reconnect exhausted → kill switch | 4 | 4 Sep | **proven** |
| **Human sign-off in the Blotter** | **0**: all 51 transmissions in the log were signed by the autonomous executor | — | **code only** in the ASX era |
| **Manual close from the Positions table** | **0** | — | **code only** |
| Time-stop exit | 0 | — | code only (no position reached 30 days) |
| Duplicate-transmission guard (the id set) | 0 | — | code only; the gate's status rail does the work |
| Protection-pending grace; protection-level change | 0; 0 | — | code only |
| Commission verified against IBKR (M175) | 0 | — | **code only** (outstanding item 3) |
| Corporate-action detection or stop adjustment | 0 | — | code only; detection unsupported on IBKR (R7 #50) |
| Daily-loss and drawdown trips; gate day-P&L rails; opening-auction and never-ticked refusals; price-drift refusal | 0 each | — | code only |
| De-lever trim; orphan cancel | off | — | code only (disabled) |

> ⚠️ **Correction, 15 Sep (back-fill; CE-046).** The row "Rejection
> classified; booking reversed … proven (the reversal once)" was wrong. The
> one live reversal proved a **defect**:
> * At 12:40:50 on 4 Sep, under M165 (`cfb87ea`, built before the sign fix
>   `d4d0ea8` at 14:51), it logged "Reversed 9636.00 of the booking for
>   A2M.AX".
> * Reconciliation then read `A2M.AX tracked=-9636 broker=9636` from
>   12:43:49 until the relaunch at 13:17. The reversal subtracted where it
>   should have given back, and made a phantom short.
> * **A correct reversal has never run live.** The row should read: *1
>   reversal, wrong-signed; the fixed version is code only.*

## 10.4 Facts this section adds

1. **The autonomous path is the only one that has run.** Every order in the
   ASX era was signed by the autonomy gate, and the human paths have never
   been exercised live. That includes the operator's own recommend-mode
   fulfilment (Q1, R8 §8.5). This matters for any return to `recommend`.
2. **The exit path has barely run, and every run tripped the kill switch.**
   Three symbols ever:
   - **A2M, 4 Sep:** eleven of the thirteen exit orders, refused on size or
     TIF for 3 h 22 min.
   - **IAG, 9 Sep:** error 10148 on the leg cancel (CE-017).
   - **SEK, 9 Sep:** the market sell was sent at 14:49:11. IBKR's TIF-preset
     notice (10349) was classified as a rejection, and the switch tripped at
     14:49:11.952. The order **filled at 14:49:40** (ledger) while the app held
     it as rejected. A re-arm was then proposed for a remainder that did not
     exist ("SEK.AX x948"), and the kill switch blocked it. 10349's handling
     is the M173 fix, unproven live (outstanding item 1).
3. **Booking at transmission is the common cause** of three of the six
   reconciliation trips (26 Aug, 3 Sep, 4 Sep). Every trip was the app's own
   record diverging, never the broker behaving unexpectedly (R14).
4. **Controls reached the live account mid-session and in stages.** On 4 Sep
   the running build, M164, was built at 17:00 on 3 Sep, before that night's
   rejection-handling commits (`8316a12` 22:03, `ca7cae8` 22:44). A2M's
   cancelled sells were therefore booked, and reconciliation tripped at
   10:25. The fix arrived with M165 at 12:27. The label "M165" was then used
   for two different builds that afternoon (`cfb87ea` 12:23 and `15ffd38`
   13:13).
5. **A resting stop did not fill with the price below it** (JHX, 10–11 Sep).
   Cause NOT DETERMINED; held until after the audit (tracker section 2).

## 10.5 Not determined

* Why JHX's stop did not fill.
* Carried from R5 §5.4:
  - whether IBKR's `reqExecutions` returns other client ids' executions;
  - whether the 202-on-bracket-child chain can reverse a real entry
    (investigator 3 §4);
  - how an adopted leg's fill is classified.
* Whether the price-drift check ever evaluated a price and passed. It logs
  refusals and skips, not passes.
