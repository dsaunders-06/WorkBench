# Stage 4 evidence: the authority register

**What this is.** The record of who decided each thing the drift map (report
§7) classifies. Every entry cites the Claude Code transcript it comes from, by
session id and timestamp, so it can be re-read. Operator words are quoted
verbatim. Claude's words are quoted where they are what the operator was
approving.

**Sources and how they were read (14 September 2026).**
* The Claude Code transcripts in `%USERPROFILE%\.claude\projects\C--Claude-Programming\`
  (the same 34 files are in `Documents\QAT-audit-evidence\2026-09-12\transcripts\`).
  They cover every day from **24 July 2026 15:52 AEST**. Report §4 and the
  audit plan said the 25 July – 2 September sessions had been deleted. That was
  wrong (CE-020).
* Two extracts, both read in full: every message the operator typed (1,391,
  deduplicated), and every decision the operator made in a dialog
  (AskUserQuestion, 133). The dialogs matter: many decisions were made there,
  not typed.
* Scripts used, kept in `stage4/tools/`. All only read, and none opens
  `%LOCALAPPDATA%`:
  - `transcript_spans.py <dir>`: the first and last record time in each file
    (the CE-020 check);
  - `operator_messages.py <out> [skip-session]`: every typed operator message;
  - `condense.py <in> <out> <maxchars>`: dedupe, and truncate long pastes;
  - `ask_answers.py <out> [skip-session]`: every dialog question and answer;
  - `window.py <session> <from-utc> <to-utc> [maxchars]`: both sides of the
    conversation in a time window;
  - `find_brief.py <file> <phrase>`: operator messages containing a phrase.

  Run them with the repo's venv Python.
* Times are AEST. Session ids are the first 8 characters of the transcript file.

**Authority values** (audit plan A2): *operator-directed*; *agent-proposed,
operator-approved*; *agent-only*; *unknown*. Where an approval came in a
batch, or on an agent claim later shown to be wrong, the entry says so.

---

## AE-01 · 24 Jul 15:52 · `64d334fe` · the build brief (typed)

The operator started the first build by pasting the paper's §20 master prompt,
with the paper attached. A diff against the paper's own §20 text
(`C:\ShareTrader\Investment_Strategy_Advisory_Paper.docx`, read 14 Sep) finds
**exactly one change**, in §A:

> paper: "…uses an LLM as an analyst that proposes and explains — while a
> human approves every live order."
>
> as pasted: "…while a human approves every live order**, with a future
> function to allow automated orders tied to tested rules and selectable
> methodology**."

The principles further down were left as the paper wrote them ("There is no
auto-trade toggle", "Do not add an auto-trade toggle"). The closing line was
changed to "The attached provides all context, methodologies and rationale."

**Reading.** The operator adopted human sign-off as the starting state and, in
the same sentence, made automated orders a planned function, "tied to tested
rules and selectable methodology". This is operator-authored, and it predates
the first line of code.

## AE-02 · 24 Jul 15:53 · `64d334fe` · first build decisions (dialog)

* "Fresh build, but mine ShareTrader for reusable logic"
* ShareTrader's autonomous journal is "Paper only"
* "Write a detailed implementation plan first (Recommended)"

Each milestone M1–M9 then went plan → approval → build, with approvals given
as "yes" / "Let's keep going" (24 Jul 16:18 – 21:37). No message in this
session discusses swing's entry rule, stop or target. Its parameters reached
the operator only inside milestone plans approved as a whole.

The first option's own description was "read ShareTrader's existing
strategy/dashboard code first to port over useful logic (**e.g. the swing
trader methodology**, existing indicators)". Claude's survey agent was
instructed to read `Swing Trader methodology.md` (2026-07-24T05:56Z). Its
report (T05:59Z) describes the reference app's swing function and never the
methodology file's content (CE-026). The same report called the reference
app's autonomous path and AI-involvement sliders "precisely the pattern your
spec and the paper's master prompt explicitly forbid".

## AE-03 · 25 Jul 20:11 and 20:13 · `64d334fe` · the no-leverage rule

Typed: "as a hard requirement, Trades must never fully deplete Cash
Available, this account can never be leveraged, this must be a hard coded
rule."

Dialog, on how much cash to keep: "Make it a selectable value in Settings,
default $1.00". *(The live `.env` sets 1,000 today, report §3.5. Who set it is
not recorded.)*

## AE-04 · 25 Jul 10:16 and 19:39 · `64d334fe` · AI routing and order handling (dialog)

* AI routing: "Make all the possible permissions a selectable option in the
  settings tab"
* A sell with no holding: "Long-only: suppress it (Recommended)"
* Bulk sign-off: "Multi-select + bulk sign-off" (Claude had recommended
  one at a time)

## AE-05 · 26 Jul 09:47 → 18:37 · `49741caa` · the autonomy decision, and the AI entry role

1. **Operator, 09:47 (typed):** "The next development for this app will be
   auto trading, once all trade methodologies have been fine tuned and all
   necessary safeguards have been developed and baked in. … The end game is to
   develop this across all 15 Strategies, with Swing being the first to be
   fully developed."
2. **Claude, 10:24:** a gap report against the reference app and a six-phase
   plan. Gap 10 names the reference app's rule that "the AI may only veto or
   shrink a new entry; it never touches a protective exit". Phase 5
   ("Autonomy, narrowly") includes "**the entry-only AI asymmetry**".
3. **Operator, 10:44 (typed):** "Only focus on developing QAT and move forward
   with the above. As this is in a paper trading environment, develop the
   autonomy but make it an option in the settings tab to either auto trade or
   the app making recommendations, supported by it's reasoning for human
   approval. Also, are we including macro market analysis in the AI
   integrations."
4. **Claude, 18:37**, reporting the finished build under "Parity items I
   deliberately skipped": "**AI entry confirmation.** The original let an LLM
   veto or shrink a new buy, with an 'AI Involvement' slider. I kept the gate
   LLM-free. I still think that's right for exits; for *entries* it's a
   legitimate feature I chose not to build." The same list names "Trailing /
   break-even stops. Brackets are static once placed" and the Friday
   per-position AI review as not built.
5. No later operator message responds to item 4. The operator's next message
   (18:40, `64d334fe`) is about a stray branch.

The commit (`ab1ba97`, 18:23) gives its reason for an LLM-free gate: "an
earlier build of the reference app put a model in front of protective exits
and it declined 100% of 494 sell signals in a day." That incident concerns
exits. The approved plan had already kept AI off exits.

**Authority.** Autonomy as a mode: **operator-directed** (items 1, 3; and
AE-01). No AI in the entry decision: **agent-only**. It departs from the plan
the operator approved at item 3, was disclosed after the build, and the
record shows no response.

## AE-06 · 27 Jul 14:30 – 14:39 · `64d334fe` · promotion evidence off on paper

The operator: "Whilst we're in testing phase and using paper trading, I'm
comfortable with the current setup." Claude then noted "`enforce_promotion_evidence` is off, so `swing` will
auto-trade without having cleared the promotion bar." The operator asked, "Am I
not understanding a key evolution needs to happen first before auto-trade?"
Claude answered: "You're not misunderstanding — you're skipping a rung
deliberately", and suggested turning enforcement on at about 30 trades. The
operator changed nothing. **Agent-proposed; operator informed; operator left it.**

## AE-07 · 27 Jul 09:53 · `64d334fe` · session start at the open (dialog)

* "Start/stop the session with market hours (Recommended)"
* "No — leave execution mode as set (Recommended)"

## AE-08 · 28 Jul 11:15 – 14:14 · `64d334fe` · costs, the principal strategy and the hold, and a third-party review

* **Operator, 11:15:** "IBKR Brokerage fees are min $6.00 per buy/sell
  transaction so we need to ensure trading frequency does not grossly erode
  prospective profit making. Initial thinking is Swing method will be
  principal strategy, with an hold period of say 2 weeks, subject to Risk
  measures being deployed to mitigate larger losses."
* **11:36 / 11:42:** ASX pricing, "$6.60 for the Fixed pricing model".
* **Dialog 11:18:** costs "Apply now (Recommended)"; minimum hold "Block early
  signal exits, log it (Recommended)"; measured in "Make it configurable,
  default 10 trading days".
* **14:09:** the operator pastes a review by another AI ("I had this analysed
  by another AI … Nothing to change yet, but review and advise"). Among its
  suggestions: "Time stop (e.g., 30 trading days)".
* **14:14:** "Model your read into our next development stack."

## AE-09 · 29 Jul 08:38 · `64d334fe` · daily bars

"Yes, write up 27a plus, the live path should run on daily bars."
**Operator-directed** (answering Claude's diagnosis of that morning).

## AE-10 · 30 Jul 21:04 and 21:52 · `73e1e19c` · swing's regimes widened (dialog)

At 21:04 Claude reported that swing was gated to Sideways alone and
said: "it's your call, not a judgement I should slip into a milestone".
* Dialog 21:04: "Widen swing's regimes"
* Dialog 21:52, on which set: "sideways, bull, low_vol, recovery
  (Recommended)" (48.6% of measured sessions)

**Operator-directed**, the operator choosing among agent-drafted options.

## AE-11 · 31 Jul 08:49 · `73e1e19c` · unattended operation

"If this is to be an automated test, development must not be dependent upon a
human needing to press a button. Implement the deployment persistence, and
develop what else is required to allow for an automated test tonight."

## AE-12 · 31 Jul 14:22 – 14:56 · `73e1e19c` · the M28a–M33 batch

* 14:22 "Both", approving M27b (gating on regime probability mass) and M29
  (promotion evidence binding on live accounts only; Claude declined the
  review's advice to enforce it on paper as "circular").
* 14:31 "**Do all, in the order shown**", approving a list of one line per
  item: M28a ("the staleness rail … never once fired correctly"), M30 (gap
  risk and the concentration limits), M31 ("churn control: time stop,
  turnover budget") and M33 (correlation as a limit). Claude replied that M30
  and M31 were in the deferred "would this change which trades happen?"
  category: "You've directed them, so I'll build them — but I'll flag the
  decision points rather than choose silently."
* M28a removed the kill switch's staleness trip. Claude reported this after
  the build ("`KillSwitch.check_staleness` is gone"; a stale quote "can never
  halt the account"), and the operator acted on the report.
* Dialog 14:56: single-name "15% (Recommended)"; gap "Separate gap budget in
  the governor (Recommended)".
* 14:52: "I've removed the Staleness line from .env". The operator had been
  running the stale-quote threshold at 69 hours to stop false trips (commit
  `234e8d5`).

## AE-13 · 1 Aug 10:23 / 10:25 · `73e1e19c` · the end goal, and the autonomy condition

* "backtesting is key to validating decisions made and to be made so an
  important piece to the learning element I ultimately want to rely upon. What
  pathway makes best sense that aligns with the end goal of having an app that
  can make solid trade decisions, with or without human intervention?"
* "**For clarity, complete autonomy will not be implemented until I have the
  fullest confidence the mechanism works**, proceed as suggested."

## AE-14 · 1 Aug 09:20 and 09:46 · `73e1e19c` · sector, and re-arm

* "Sector concentration please." (M31c: trim, 40% → 30%)
* Dialog: "Build re-arm into the app (Recommended)"

## AE-15 · 4 Aug 16:45 · `87d1b020` · AI in the recommendation, in the reference app

"Earnings information in the original app was used by AI to deduce it's
recommended action (AI Deep dive), so I'm surprised to learn this hasn't
transferred across."

## AE-16 · 6 Aug 08:59 / 09:06 · `47042ff9` · the risk cap kept

"The Position limit appears to be doing the job it was designed to do … I'm
happy to widen this limit … At present it's 5%", then: "Fair call, I've
decided not to change it. On the back of what is emerging as a more stable
build, we'll consider this the conservative baseline, run it for 2 weeks,
review the outcomes". **Operator-directed.**

## AE-17 · 7 Aug 14:53 – 16:19 and 8 Aug 11:10 · `d5855f73` · the time stop against the intended cycle

* **Operator, 14:53:** "I'm struggling to recall how we landed on a 30 day
  hold, **the original Swing Strategy was meant to span a 10 trading day
  cycle**, so something has been lost along the way. It seems the sell
  decision needs strengthening also".
* **Claude, 14:57:** "30 was never derived from swing at all". It came from the
  28 July review. "The source paper (§4.10) isn't in the repo — so the 10-day
  cycle isn't recorded anywhere in the codebase." A replay on the ten held
  symbols, which Claude flagged as a selected sample, found 30 days "roughly
  right anyway"; "a 10-day cycle would about halve net return per slot-year".
* **Operator, 15:54:** a second third-party review is pasted (earnings
  filter at 50% size, a 60-day correlation window, trailing stops instead of
  the time stop). **16:19:** "Do as suggested and book the remaining items
  into the dev stack." (M57 earnings halving shipped the same day.)
* **Dialog 8 Aug 11:10:** of three proposals, only "Correlation window 300→60
  (Recommended)" was chosen. "Time stop 30→45" was declined.

**Reading.** The operator named the time stop as drift from their intended
swing cycle. Claude traced it and measured it. The operator then left the
time stop at 30.
*Corrected 14 Sep (AE-34):* "left" is accurate; "kept", used elsewhere, is
not. The operator declined a longer stop and never chose 30 over 10. The
specification's test condition is 10 working days.

## AE-18 · 8 Aug 15:53 · `cd2ae64a` · test posture

"this is a test environment, to make certain the machinery works … If we need
to vary fixed rules in order to deliver thorough testing, there is no real risk
in doing so and those changed rules can then be evaluated as to their
necessity."

## AE-19 · 12 Aug 10:02 · `9034806e` · corporate actions and autonomy

"Longer term development I want this to factor into autonomous decision
making". The dialogs that follow choose automatic re-pricing that "may never
tighten the stop" and "Shadow mode first".

## AE-20 · 12 Aug 15:59 – 16:20 · `fc4500e5` · the operator's development strategy

The operator attached "Autonomous US Share-Trading System — Evidence-Driven
Development Pathway Strategy Review 12/8/2026". It is held in the transcript as
an attachment record, read 14 Sep. The file itself is in `Documents`, outside
the boundary, and was not opened. It states:
* the long-term objective: "identify attractive share-trading
  opportunities; make explicit BUY/SELL recommendations; calculate appropriate
  position sizes; manage portfolio-level risk; execute trades autonomously when
  authorised; continuously protect open positions; maintain a complete audit
  trail";
* 15 "architectural principles that must be preserved", including "Autonomous
  execution must be controlled by an explicit autonomy gate rather than being
  an inherent capability of the strategy" and "Minimum-hold restrictions apply
  only to signal-driven exits";
* recommendation and autonomous modes using "the same underlying decision
  engine", with "Define precisely what evidence must exist before the
  autonomy gate permits execution";
* "Determine whether Sideways should actually qualify a trend-following
  strategy."

It calls the application "AI-driven" while describing a rule-based decision
path.

Operator, 16:12: "I'd prefer spending 6-12 months testing in that market [ASX]
than the US". Dialog 16:20: "Keep the rails; buy the SFBS observation
(Recommended)".

## AE-21 · 14 Aug 14:45; 15 Aug 14:28; 19 Aug 09:18 · `1111c286`, `00ce3f0d` · the US trial ends, the ASX move

* "I see little value in maintaining a freeze that serves little to no benefit"
* "I will conclude the current test period … I'm happy to establish the Paper
  trading account with [IBKR] and to then wire everything to the ASX."
* "Develop an implementation plan to move to IBKR."

## AE-22 · 19 Aug 14:15 – 14:32 · `00ce3f0d` · price data

Whether to buy the $25/month ASX data, then "Update the plan accordingly and
let's begin the work." The outcome was yfinance for prices and IBKR for
execution only (commit `709897a`).

## AE-23 · 20 Aug 20:23 and 21 Aug 21:47 · `25468f8a`, `f2d132cc` · news corroboration

* "I recall having a condition that there be at least 2 independent sources
  before pushing any news" (M115)
* Dialog: "Setting, default 1 source (Recommended)", loosened because no
  symbol was returning news

## AE-24 · 21 Aug 11:59 · `9083b85e` · the universe widened (dialog)

"Yes — all of it now"; "Full universe, all 10 slots".

## AE-25 · 21 Aug 21:45 → 25 Aug 21:17 · `f2d132cc`, `74fe73ed` · the AI recommendation request

* **Operator, 21 Aug 21:45 (typed):** "From the information in the Strategy
  Workbench page and the AI Advisor page, **I want all the intelligence
  relating to a Symbol to be analysed and a buy/sell/hold recommendation
  formed, against the prevailing market Regime, whilst following the rules of
  the current strategy.**"
* **Dialog 22 Aug 08:46:** "Both, with the verdict leading" (a deterministic
  rail verdict plus the same facts in the model's context). **08:49:**
  "Advisor gains it; Workbench gains parity (Recommended)".
* **25 Aug 21:17:** the operator re-quotes the request and asks Claude to
  "confirm everything has been done relating back to my original request".

What was built (M136) is an advisory panel. None of the dialog options offered
the operator a path from the recommendation to the order flow, and none of the
record states whether one was wanted. **NOT DETERMINED**: whether the operator
meant this recommendation to drive autonomous trades.

## AE-26 · 24 Aug · `f2d132cc`, `74fe73ed` · the per-order cap and the orphan rail

* 12:52: "make it a % of Cash available as a setting with a range from 0 to
  100% … with the default of 10%" (M138); 13:37: key it off "Spendable" (item 22)
* Dialogs: orphans "Detect, report, and cancel behind an off-by-default flag";
  "OCA-aware netting"; "ERROR + quarantine the symbol"; cancel "Flat symbols
  only". The flag is still off.

## AE-27 · 1 Sep 17:48 – 22:39 · `6b884879` · manual close

* "I want to add the ability to manual trade within the Automatic
  environment. Can this be done via the Positions table?"; "Design the sell
  features for now"
* Dialog 17:52: close during a halt "Allowed, but only with a second
  confirmation"
* 22:36: review finding C3 is explained to the operator. With the kill switch
  tripped, the close "cancels the legs, sells nothing, and can't re-protect →
  every halt-time close strips protection". The operator, 22:39: "ok, go with
  the first option". The close now refuses while tripped, before touching the
  broker.

## AE-28 · 3 Sep 17:18 – 21:54 · `bf81c3b3` · rejections and booking (dialogs)

"Classify by error code"; "Unknown → serious → halt (Recommended)"; "Teach the
sizer the ceiling"; "Stop and rethink the spec"; "Drop Task 3, rely on Tasks
4-5 (Recommended)". The last kept booking at transmission and added reversal
on a rejection.

## AE-29 · 7 Sep 16:50 – 17:10 · `bf81c3b3` · the exit-leg ordering (CE-017)

* Claude, 16:52, reporting the A2M orphan: asks whether autonomous exits should
  "follow M163's cancel-first ordering, or should I look at whether a different
  order is safer".
* **Operator, 17:09:** "look at whether a different order is safer now that the
  resting-order rail exists to catch orphans"
* **Claude, 17:10:** "Keep M163's cancel-first ordering". The argument: "Cancel-first
  fails → position unprotected. `verify_position_stops` detects it, and
  `signal_bridge` then re-arms automatically … With autonomous execution on,
  that sign-off is automatic. **Self-healing within a scan cycle.**"
* **Operator, 17:10:** "yes"
* Commit `e0c780d`, 17:23.

**Reading.** The re-arm cannot sign off while the kill switch is tripped (gate
rail 3, `oms.py:906`). The self-healing claim held only while the switch was
clear, and the switch was tripped on 9 September by the leg cancel itself.
Six days earlier (AE-27) the same hazard had been found in the manual path and
closed there by refusing before any broker action. The finding was not carried
to the autonomous path. **Agent-proposed, operator-approved on an agent claim
that was wrong.**

## AE-30 · 8 Sep 14:09 – 17:27 · `bf81c3b3` · the 7-regime macro matrix

* "This sits outside of the authority of autonomy, resultant action must be
  human driven only for now."
* 17:24: the operator pastes an architecture: "The Execution Layer (HMM Engine):
  The sole source of monetary authority … The Narrative Layer (7-Regime
  Matrix): … zero authority to move money … The LLM operates exclusively as an
  editor and copywriter." 17:27: "yes build it but also adjust it to make it
  work within the program".

## AE-31 · 10 Sep 13:41 / 14:23 · `d085983f` · the holding horizon

"the longer term vision for this app is to hold positions for up to 60 days",
then: "**The 60 day horizon is not to be relied upon in any decision making,
nothing has changed in regards to the current Position hold strategy.**"

## AE-32 · 12 Sep 18:36 · `ede4fc1d` · why `auto` stays on

"Keep the automation running, it's intended to not slow trade decisions by
having a human intervene and slow the process or corrupt decisions due to
timing whilst we are testing".

## AE-33 · 14 Sep 09:05 / 09:08 · `ede4fc1d` · Checkpoint A

The operator's statement of intent (report §4.00) and the AI's role (§4.001).
A multiple-choice dialog on the AI's role, just before, was dismissed. Its
options were "AI decides trades", "AI can veto or adjust" and "App autonomous,
AI advises". The operator then typed their own answer.

## AE-34 · 14 Sep, about 10:08 · `df2c900c` · the Stage 4 questions answered (typed)

* **Q1 (the AI's part):** "The recommendations made by the AI should be no
  different whether in Autonomous mode or Manual mode. The difference is the
  fulfilment process. It's decision making however, should be informed around
  strategy and rules."
* **Q2 (the swing specification):** "the spec for Swing Trading. The test
  conditions were initially set to 10 working days, the longer term view
  would be to extend this to 60 days, once the machinery was proven."
* **Q3 (the first build's departures):** "The original vision has been lost
  amongst multiple development branches arising during the build. These
  branches have been formed, sometimes from misinformation, or not anchoring
  back to the fundamentals. As seen in this audit, conflicting decisions being
  made has been the consequence of this."

How the audit applies them, with its reading of each, is report §8.5.
**Operator-directed.**

## AE-35 · 14 Sep, about 10:19 · `df2c900c` · trading suspended for the audit (typed)

"Prepare for handover, noting Trading will be suspended during the course of
this audit." This supersedes AE-32 (keep `auto` running, 12 Sep). At 10:20
the app was not running, and the configuration still read
`QAT_EXECUTION_MODE=auto`, `QAT_AUTONOMOUS_STRATEGIES=swing`. Nothing was
changed to enforce the suspension. **Operator-directed.**
