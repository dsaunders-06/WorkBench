# QAT Design Recovery & Design Intent Audit, R12: Regime Assessment

**Brief §10 ("Audit regime logic"). DRAFT for Checkpoint B.**
**Prepared:** 15 September 2026. Read-only: nothing in the system was changed.
The brief: "Do not redesign the regime system. This is an audit of what
exists." This section proposes no change.

**Sources**
* The code, re-read 15 Sep: `domain/regime_engine/engine.py`, `fusion.py`,
  `feature_matrix.py`; investigator 1, section D
  (`stage3/investigator-1-data-to-signal.md`), which this re-reading confirms.
* The live evidence: `s09-s10-ai-and-regime/tools/regime_evidence.py`
  (read-only). It reads the log (27 Jul – 12 Sep), `risk_decisions.csv` and
  `closed_trades.csv`.
* The 28 Aug feature ablation: the comparator's own output in transcript
  `58424b93` (2026-08-28 07:42–08:06Z), not HANDOFF's summary of it.
* History: `git log` over `domain/regime_engine/`, with each build's commit
  checked by `git merge-base`.

**The deployed configuration** (`.env` re-read 15 Sep): no regime setting is
overridden. Six features, `VIXCLS` as the VIX series, no Yahoo macro series,
eligibility mass 0.5, benchmark `STW.AX`, 99 breadth symbols.

---

## 12.1 The pipeline

| The brief asks | What the code does | Where |
|---|---|---|
| **Inputs** | Six HMM features: `log_return`, `realized_vol`, `vix_level`, `yield_curve_slope`, `credit_spread`, `breadth`. The rules also read the benchmark's 200-day average and the **previous** curve slope and 200-day average | `feature_matrix.py:84-122`; `engine.py:372-391` |
| **Data sources** | `STW.AX` from yfinance (return, volatility, the 200-day average); the watchlist's latest prices (breadth); FRED `VIXCLS`, `T10Y3M`, `BAA10Y`. `DGS3MO` and `DGS10` are fetched and ignored | `feature_matrix.py:76-82`; investigator 1 D |
| **Frequency** | The posterior, the rules and hysteresis run on **every benchmark tick**, one per 60 s poll during the session. The matrix gains one row per trading day; the day's row is rewritten as the price moves. FRED is polled hourly | `engine.py:322-404`; `runtime.py:820` |
| **Lookback** | 300 daily bars seeded at launch, and the matrix is never trimmed. Realised volatility 20 bars, breadth over a 50-bar average, the bull block over 200 closes | `warm_start.py`; `feature_matrix.py:35-36`; `engine.py:39` |
| **Standardisation** | Each column is z-scored with statistics fitted at each fit (`scaling.py`). **Live from M146, 26 Aug 14:38**; raw features before that | `hmm_core.py:155-159`; build check below |
| **HMM** | `GaussianHMM`, 4 states, diagonal covariance, seed 0, 100 iterations. Each state is characterised by its mean raw return and volatility | `hmm_core.py:117-122, 204-226` |
| **Refit schedule** | The code refits every 20 new daily bars, or whenever the model is unfitted (`engine.py:356`). **The model is unfitted after every launch, so in practice it refits once per launch, at the first live tick.** 51 of 51 runs that published a label fitted exactly once (300 or 301 rows × 6). No run spanned 20 trading days, so the 20-bar refit has never run | `engine.py:356`; tool §1 |
| **Fusion logic** | From the HMM posterior and the state characteristics, five scores (bull, bear, sideways, high_vol, low_vol). Then the rules: **bull set to 0** below the 200-day average; **US VIX below 15 adds 1.0 to low_vol, above 25 adds 1.0 to high_vol**; recession = Φ(−0.53 − 0.63 × curve slope) × (bear + high_vol) / 2; recovery = the bull score when the curve steepened, the 200-day average rose and price is within ±5% of it, plus 0.5 × the steepening. Then normalised | `fusion.py:93-186` |
| **Hysteresis** | The label changes only when a challenger leads by more than 0.15 on 3 consecutive updates. **Updates are ticks, so 3 updates take about 3 minutes.** The gate is new at each launch, and its first update takes the leader outright | `fusion.py:194-231`; `engine.py:98, 387` |
| **Labels** | bull, bear, sideways, high_vol, low_vol, recession, recovery | `domain/regime.py` |
| **Probability calculations** | The published probabilities are the **normalised fused scores**, rule bonuses included, not the HMM's posterior | `fusion.py:182-186`; `engine.py:396-403` |
| **Exposure scalars** | bull 1.0, low_vol 1.0, recovery 0.9, sideways 0.7, bear 0.5, high_vol 0.4, recession 0.3. The label's scalar multiplies every buy's share count, before the OMS's 10%-of-cash cap | `fusion.py:30-38`; `risk_engine/engine.py:234` |
| **Strategy eligibility** | A strategy is eligible when its regimes hold at least 0.5 of the probability mass. Swing's are sideways, bull, low_vol and recovery. Before the first classification no strategy may enter | `strategies/engine.py:258-290`; `swing.py:38-65` |

**Constants.** The VIX thresholds, the rule bonus, the recession
coefficients, the recovery band, the scalar table and the hysteresis settings
are all hard-coded in `fusion.py`, and **`fusion.py` has not changed since the
first commit** (`fa9ba47`, 25 Jul). The recession coefficients are described
in the file itself as "Illustrative … NOT the Fed's actual published
calibration … Replace … before relying on this" (`fusion.py:20-23`).
`settings.vix_shock_level` is not read by the regime engine (investigator 1 D).

## 12.2 What the live record shows

From `regime_evidence.py` (the log, 27 Jul – 12 Sep):

* **135 runs** of the engine; **51 published a label**: 18 on `SPY`
  (30 Jul – 17 Aug) and 33 on `STW.AX` (20 Aug – 11 Sep). No fit failed.
* **The first label after each launch:** recovery 20, low_vol 14, bull 7,
  sideways 5, high_vol 4, bear 1.
* **Changes within a run: 19** in total. Recovery → bull 16, recovery →
  sideways 2, bear → bull 1. **No other label, once set, ever changed within
  a run.**

### A launch artefact decides the first label

The engine starts its "previous" curve slope and "previous" 200-day average at
**0.0** (`engine.py:109-110`, since `fa9ba47`), and the warm start does not set
them (`engine.py:154-218`). So at the first classification after a launch:
* "curve steepening" equals the whole curve level (0.74–0.95 in the logged
  lines), which adds half of that to recovery;
* the 200-day average counts as "rising";
* when `STW.AX` is within 5% of its 200-day average, recovery also receives
  the whole bull score (`fusion.py:174-180`);
* the hysteresis gate takes that first reading as the label, without the
  persistence test (`fusion.py:204-207`).

From the second tick the steepening is zero and the bonus is gone. The label
moves once a challenger has led it by more than 0.15 on three consecutive
ticks.

**Live evidence.**
* **20 of the 33 ASX-era runs opened on recovery.** 18 changed, after a
  median **3.1 minutes** (range 2.9–7.8): to bull 16 times and to sideways
  twice.
* Recovery is absent from the top three probabilities in every one of the
  19 within-run transition lines.
* In the SPY era recovery was in the first classification's top three in 16
  of 18 runs and never led.
* Two recovery openings never changed. 4 Sep 11:13 (M164) was relaunched
  7 minutes later. For 24 Aug 11:21 (M137), which ran until 13:04, why the
  label held is NOT DETERMINED.

**Effect on orders.**
* R9 found 6 of 20 proposed entries sized at the recovery scalar 0.9: TNE
  twice (24 Aug), BHP (3 Sep), TWE and TAH (4 Sep), COH (10 Sep). **All six
  were evaluated within 61 seconds of a launch's first classification**
  (13:05:00 → 13:05:01, 15:19:36 → 15:19:36, 14:51:25 → 14:52:19,
  14:27:27 → 14:28:24/25, 10:20:36 → 10:21:37).
* **The OMS's cash cap cut all six further.** The cap is applied after the
  scalar and does not depend on it, so the artefact changed no transmitted
  quantity (derived, from `risk_per_trade.py`'s columns).
* Five more recovery-sized approvals, TNE at 10:21–10:35 on 24 Aug, fall in
  the log's 66-minute hole (12.5).

### The US VIX sets the label when it is below 15

* **All 12 classifications made with `VIXCLS` below 15 were low_vol.** The
  other 2 low_vol readings were at 15.46 and 15.28.
* In the ASX era all 8 low_vol labels had the VIX below 15.
* No classification had the VIX above 25; the highest logged was 20.66.
* By construction, an HMM score exceeds the rule's 1.0 only when the
  posterior-weighted z-score behind it does: each score is a posterior-weighted
  sum of z-scores capped at 2 (`fusion.py:69-81, 124-128`).

### The inputs, as read

* **FRED ages** when read, in calendar days: `VIXCLS` median 2, max 5;
  `T10Y3M` median 1, max 4; `BAA10Y` median 3, max 6 (about 420 reads each).
* Fetch failures: 10 poll failures, after each of which the engine keeps the
  series' previous value (`macro_fred.py:219-223`), and 2 history loads that
  failed once and succeeded on the retry (no "Could not load" line follows).
* **Breadth** was a constant 0.5 on 20 Aug. M104 logged "No breadth symbols
  cover every benchmark bar" and named `breadth` a column that never moved.
  It is real from 21 Aug (M118, which carries `787e000`): 94 symbols, then
  99 from 1 Sep.
* **The raw-spread line** ("Raw feature spread is led by vix_level at
  85.0–85.1%", 24 fits since M146) describes scale **before** standardisation.
  It says nothing about influence.

## 12.3 The brief's six determinations

### 1. Which inputs materially drive the classification?

**(a) The US VIX, by construction and in the live record.** Outside 15–25
the VIX rule adds a fixed 1.0 to one label. Below 15 it decided the label
every time (12 of 12).

**(b) The US curve level, at every launch**, through the artefact above.
20 of 33 ASX-era runs opened on recovery.

**(c) Inside the HMM, not cleanly measured.** The only measurement is the
28 Aug ablation. It removed one column and counted the bars whose label
changed (transcript `58424b93`, comparator output):

| Column removed | Full window (249 bars) | Earlier (125) | Later (124) |
|---|---|---|---|
| `vix_level` (US) | 213 (86%) | 106 (85%) | 103 (83%) |
| `credit_spread` (US) | 104 (42%) | 20 (16%) | 69 (56%) |
| `yield_curve_slope` (US) | 75 (30%) | 26 (21%) | 90 (73%) |
| `breadth` (AU) | 67 (27%) | 23 (18%) | 81 (65%) |

⚠️ **The `vix_level` and `yield_curve_slope` rows are confounded.**
* With a column removed, the engine reads it as **0.0** (`engine.py:419-422`).
  That zero-fill was added in `6ace6fc` (07:48Z). Both rows' full-window runs
  print that commit, and their window runs came after it (07:58–08:06Z).
* The fusion rules still read the values. **A VIX of 0.0 is "below 15", so
  the ablated arm added 1.0 to low_vol on every bar.** A slope of 0.0 sets the
  recession term to Φ(−0.53) and removes the recovery term.
* The code comment says "a zero contributes no bonus" (`engine.py:409-413`).
  For the VIX that is false.

So 86% measures VIX leaving the HMM **plus** a constant low-vol bonus. It
cannot be read as the influence of the VIX's information. HANDOFF item 66
read it that way ("It still dominates by INFORMATION, at 86% of labels"), and
so did the 12 Sep capability document ("driven largely by US conditions"). The
`credit_spread` and `breadth` rows are clean: neither column reaches a rule.
Their percentages move with the window (16–56%, 18–65%), as the comparator
itself warns. Their full-window runs printed `eaf1aec*`, an uncommitted
working tree, so the exact code those two runs used is not in git.

### 2. Are the inputs appropriate for the ASX?

The audit records facts and makes no design judgement.
* 3 of the 6 HMM features are US series.
* Of the rule inputs, the VIX and the curve are US; the 200-day average is
  the only Australian one.
* The VIX thresholds 15 and 25 are fixed in code with no stated calibration
  (`fusion.py:27-28`).
* The setting that looks like a threshold, `vix_shock_level`, feeds the
  advisory macro read and the Regime Monitor (`signal.py:437`,
  `regime_monitor.py:315, 452`), not the regime engine. Pre-flight warns when
  the VIX series is switched and that setting is not (`preflight.py:195-210`).
  **No check covers the engine's own 15 and 25.** If the series were switched
  to `^AXVI`, they would apply to the Australian index unchanged (derived).
  Pre-flight is a script the app does not run (R5 §5.3 #23).
* The recession coefficients are self-described placeholders (12.1).

### 3. Do US inputs dominate?

**In the rule layer, yes**, by construction and in the live record:
* the VIX rule decides low_vol below 15;
* the US curve drives the recession term, the recovery term and the launch
  artefact;
* the only Australian rule input is the 200-day bull block.

**In the HMM itself, not determined.** The one clean comparison is mixed:
`credit_spread` (US) moved more labels than `breadth` (AU) on the full window
(42% against 27%), and fewer on each half (16% against 18%; 56% against
65%).

### 4. Are the Australian inputs sufficiently current?

* **The regime's Australian inputs are market prices only**: `STW.AX` and the
  watchlist, from the 20-minute-delayed feed, updated every poll.
* **No Australian macro series feeds the regime.** HANDOFF records that the
  Australian rate series on FRED are monthly and were "99 days stale when
  measured" on 8 Sep. That was measured for the macro matrix, not the regime,
  and the audit has not re-measured it.
* The US FRED inputs were 1–3 days old at the median (12.2).
* Breadth was not a live input until 21 Aug (12.2).

### 5. Is regime information recorded with trades?

| Record | Regime recorded? | Evidence |
|---|---|---|
| `risk_decisions.csv`, entries | **Yes**, label and scalar on every buy evaluation from 24 Aug 10:21 (M94 added the label, `69869ec`, 19 Aug): 4,787 rows. bull 2,411 (47 approved), low_vol 1,720 (1), sideways 606 (9), recovery 45 (11), none yet 5 (0) | tool §5 |
| `risk_decisions.csv`, exits | **No**, by design: 171 exit evaluations; exits are not sized by the regime (`engine.py:371-406`) | tool §5 |
| `closed_trades.csv` | **No**: 12 of 12 blank. Restored lots never carry it, and every position held overnight is a restored lot (R5 §5.3 #16) | tool §5 |
| `decision_journal.csv` | **No field for it** (`decision_journal.py:36-53`) | — |

### 6. Has the regime logic changed over time?

The fusion rules, the scalars and the hysteresis have not changed since
25 Jul. What changed is the HMM's input and fitting, and what the label
governs:

| When | Change | Commit | Live from |
|---|---|---|---|
| 25 Jul | First build: HMM + rules + fusion + hysteresis; eligibility by label membership | `fa9ba47` | — |
| 30 Jul | Real FRED; daily bars; warm start from 300 bars (M27a) | `1687664`, `373041a`, `3458715` | 30 Jul |
| 30 Jul | Swing's regimes widened to sideways, bull, low_vol, recovery (operator, AE-10) | `44564c8` | 30 Jul |
| 31 Jul | Eligibility by probability mass (M27b, operator "Both", AE-12) | `9b9fa50` | 31 Jul |
| 14 Aug | Convergence counters (logging only) | `d19ce1e`, `c4a82e5`, `bee937c` | — |
| 19 Aug | The label recorded on each risk decision (M94) | `69869ec` | first row 24 Aug |
| 6–20 Aug | Benchmark `SPY` → `STW.AX` as the market setting moved to ASX (65 runs on `STW.AX` from 6 Aug; the last `SPY` run 19 Aug 09:12) | config | first `STW.AX` label 20 Aug (M104) |
| 20 Aug | Bars on the exchange's trading day, not UTC (M111); breadth alignment (M112) | `24750ac`, `787e000` | M112 from M118, 21 Aug |
| 26 Aug | The fit on standardised features | `52f9d54`, `ee8c26a`, `5644a1e` | M146, 26 Aug 14:38 |
| 28 Aug | Columns chosen by name; an absent column reads as 0.0 (Milestone C) | `b59677c`, `be1473d`, `6ace6fc` | no effect at the deployed six columns |
| 8 Sep | The VIX series becomes a setting; Yahoo tickers can feed the engine | `4698b86`, `5d2bb7e` | **not enabled** (`VIXCLS`, no Yahoo series) |

The labels seen changed with them. SPY era (first labels): low_vol 6,
high_vol 4, bull 4, sideways 3, bear 1. ASX era: recovery 20, low_vol 8,
bull 3, sideways 2.

## 12.4 Against the intent

The paper (the governing source for "philosophy and strategies", R4 §4.00)
describes regime adaptation (P §9–§11) and a decision matrix that switches
strategies by regime (P §10). R4 §4.14 and R6 record:
* the first build already had the same six features and the same scalar
  table as today;
* it had no ML ensemble and no decision matrix.

Those are R6 and R7 items. This section adds three things about the regime
**as it runs**:
* in 20 of 33 ASX-era runs its first label was an artefact of the launch that
  lasted about three minutes;
* below a US VIX of 15 one rule sets it;
* it has never been refitted on its own schedule.

The regime scalar also set few final order sizes: the cash cap cut 18 of 20
entries after the scalar was applied (R9 §9.2), so for those 18 the scalar
did not set the quantity sent (derived).

## 12.5 Found in passing, for other sections

* **R13 (evidence integrity): the retained log has a 66-minute hole,
  24 Aug 10:06:27 → 11:12:37 AEST**, between `qat.log.6` and `qat.log.5`
  (tool §0). It is the morning of the first real ASX orders. The evidence
  snapshot's copies of the seven files have the same sizes. `risk_decisions.csv`
  has rows inside the hole (TNE, above). R9 and R10 counted from the log from 19 Aug; **their counts for
  24 Aug morning may be short**, to be checked in R13.
  *Later notes, 15 Sep:*
  - R13 §13.6 checked the counts: none is short.
  - The hole's cause is recorded in commit `ab5175d`: Claude's session
    watcher held the log open and rotation failed silently (CE-037).
* **Error log:** the confounded ablation reading and the false comment are
  recorded as CE-032.

## 12.6 NOT DETERMINED

* Why the 24 Aug 11:21 run's recovery label held until the run ended.
* How much of the HMM's own classification the US columns decide (12.3 (c)).
* Whether the recovery label on TNE's decisions of 10:21–10:35 on 24 Aug was
  the launch artefact. The run that made them falls in the log's missing hour,
  and the label held for at least 14 minutes, longer than the artefact's
  usual 3.
