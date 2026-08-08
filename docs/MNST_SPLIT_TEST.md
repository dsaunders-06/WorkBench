# MNST split test — instructions for Monday 10 and Tuesday 11 August 2026

Print this. It is self-contained; it assumes no memory of the conversation that
produced it.

## What this is for

**One question, which cannot be answered by reasoning: what does Alpaca do to a
held quantity, and to a resting protective order, when a stock splits?**

The application has no handling for corporate actions (M39). A split doubles the
broker's share count, so reconciliation compares tracked 8 against broker 16 and
halts the session; the resting stop is left at a price that may liquidate the
position at the open. Before that can be fixed, somebody has to see what the
broker actually does. This paper account has processed **zero** corporate actions
in its life, so it has never been observed.

**MNST splits 2-for-1 with an ex-date of Tuesday 11 August.** Measured from
Alpaca's own announcement feed: `old_rate=1.0, new_rate=2.0`, record date
24 July, payable 10 August.

Paper account. No real money is involved at any point.

## The position (placed Saturday 8 August)

| | |
|---|---|
| Buy | **8 shares MNST**, market |
| Reference price | $90.85 (Friday close) |
| Stop | **$72.68** — 20.0% below |
| Time in force | **GTC** (Alpaca expires it at 90 days) |
| Risk at stop | 8 × $18.17 = **$145.36**, ~0.14% of equity |

Queued outside market hours, so Alpaca submits it at Monday's open.

**Expect the position to be liquidated on Tuesday.** Post-split MNST trades near
$45.43, and a sell-stop resting at $72.68 is then *above* the market — it
triggers immediately unless Alpaca adjusts it. That is the M39 hazard, and
watching it happen is the point of the exercise.

---

# ⚠️ THE ONE RULE

## Do NOT start the application before Monday's open.

The app must not be running when the MNST order fills. It does not track MNST
and will not absorb a fill for a symbol it does not track, so the first
reconciliation poll after the fill reads it as an unexplained divergence and
**trips the kill-switch, halting the whole session**.

Start the app roughly **15 minutes after the open** instead, once the fill is
confirmed. Adoption then takes MNST on as baseline, silently and correctly.

The usual "start the watcher before the app and confirm REGIME within seconds of
the bell" ritual is **suspended for Monday only**. REGIME still classifies on the
first live bar after the engine starts, so a 15-minute-late start still confirms
it works — only the timing check is deferred.

---

# MONDAY 10 AUGUST

US open is **13:30 UTC / 23:30 AEST**.

- [ ] **1. Confirm the app is not running.** It was closed on Saturday with a
      clean shutdown. Check Task Manager for `QuantAdvisoryTerminal.exe` and
      close it if it is up.

- [ ] **2. Wait until ~15 minutes after the open** (≈23:45 AEST).

- [ ] **3. Confirm the order filled**, at Alpaca in the browser. Note the actual
      fill price and quantity. If it did **not** fill, stop here — there is
      nothing to observe, and see "If it did not fill" below.

- [ ] **4. Capture the pre-split state.** This is the half that cannot be
      recovered afterwards. In PowerShell:

      cd "C:\Claude Programming"
      .\.venv\Scripts\python.exe scripts/analysis/capture_split_state.py MNST pre-split

      It writes a timestamped JSON under `scripts/analysis/split-captures/` and
      prints a summary. **Check the printed summary shows a position of 8 and at
      least one live order carrying the stop.** If it shows no position, the fill
      has not settled yet — wait five minutes and run it again.

- [ ] **5. Start the watcher**, then the app:

      & "C:\Claude Programming\.venv\Scripts\python.exe" "C:\Claude Programming\scripts\watch_session.py"

      then launch `C:\QuantAdvisoryTerminal\QuantAdvisoryTerminal.exe`.

- [ ] **6. Confirm the startup lines.** Their absence is the signal, not their
      content:

      Build: M60+M59 (ae33689, ...)
      Broker-fill watermark restored to ...
      Restored 1 closed trade(s) from closed_trades.csv
      Restored 11 open lot(s) ... or a line naming MNST as having no entry record
      Adopted 11 ...                        <- ELEVEN, not ten
      REGIME ... shortly after startup

      **`Adopted 11` is the one to check.** If it still reads 10, MNST was not
      adopted and the rest of the test will not work.

- [ ] **7. Confirm the kill-switch has NOT tripped.** Look at the Risk Console.
      If it has tripped, the app was running when the fill landed — see
      "If the kill-switch trips on Monday" below.

- [ ] **8. Leave the app running overnight** as normal.

Expect an otherwise quiet session: risk-at-stop sits near the cap and the
position limit is full, so few or no new entries will be permitted. That is the
rails working. A log that goes quiet is indistinguishable from an app that has
died, so if in doubt check that `equity_curve.csv` is still growing under
`%LOCALAPPDATA%\QuantAdvisoryTerminal\data`.

---

# TUESDAY 11 AUGUST — ex-date

- [ ] **9. Expect the kill-switch to trip.** Tracked 8 against broker 16 is an
      unexplained divergence and the session halts. **This is the experiment
      working, not a fault.**

- [ ] **10. Capture the post-split state** before changing anything:

      cd "C:\Claude Programming"
      .\.venv\Scripts\python.exe scripts/analysis/capture_split_state.py MNST post-split

- [ ] **11. Declare the anomaly in the Risk Console.** Use *"Declare a difference
      explained…"*, symbol `MNST`, reason something like
      `2-for-1 split, ex 11 August`. This clears the halt and quarantines MNST.
      It is also the first live exercise of that mechanism.

      Note the declaration explains the difference; it does **not** correct any
      record. That is still manual, by design.

- [ ] **12. Confirm the session resumes** — the kill-switch shows inactive, and
      the quarantined-positions panel lists MNST.

---

# WHAT THE CAPTURES MUST ANSWER

Compare the `pre-split` and `post-split` JSON files. Four questions, in order of
how much they matter:

1. **What happened to the resting stop?** Cancelled, left at $72.68,
   price-adjusted to ~$36.34, quantity-adjusted to 16, or some combination.
   **This decides the design of the M39 fix and is the whole reason for the
   exercise.**
2. **Did the quantity double** from 8 to 16, and is `avg_entry_price` halved to
   ~$45.43 or left stale at ~$90.85?
3. **Did a `SPLIT` account activity appear?** That endpoint has returned zero
   rows for this account's entire life.
4. **What did the application do** — the divergence, the halt, and whether
   declare-then-quarantine worked end to end.

---

# IF SOMETHING GOES DIFFERENTLY

**If the order did not fill.** Nothing to observe; no harm done. Cancel the
resting order. Other forward splits follow: SFBS 2-for-1 on 21 August, IESC
2-for-1 on 24 August, APH 2-for-1 on 3 September.

**If the kill-switch trips on Monday** (before the split). The app was running
when the fill landed. Declare the anomaly exactly as in step 11 — the reason is
different but the mechanism is the same — or close the app and restart it, which
re-adopts MNST cleanly as baseline. Either works.

**If the position is liquidated at Tuesday's open.** Expected, and it is a
result rather than a failure — it means Alpaca did *not* adjust the resting stop,
which is the most important thing the test can tell us. Capture the state anyway;
the `post-split` file will show the fill and the empty position.

**If the app will not start at all.** Do not troubleshoot at the bell. The
previous build is recoverable from
`C:\Claude Programming\build\` and the install is
`C:\QuantAdvisoryTerminal`. A hash proves the right bytes landed, never that they
run — this build was launched and confirmed working on 8 August.

**Nothing here requires a code change or a redeploy.** The deployed build
already contains everything the test needs.
