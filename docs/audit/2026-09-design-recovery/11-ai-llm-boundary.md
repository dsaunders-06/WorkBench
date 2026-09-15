# QAT Design Recovery & Design Intent Audit, R11: AI / LLM Boundary Assessment

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §9 ("Audit the AI/LLM boundary"). Final, for the operator's review at Checkpoint B.**
**Prepared:** 15 September 2026. Read-only: nothing in the system was changed.
Trading has been suspended since 14 Sep; this works from the code at the
deployed build (M175, `src/` level with it) and the records to 12 Sep.

**Sources**
* The code: investigator 4, part 3 (`stage3/investigator-4-wiring-ledger-ai.md`).
  Its reachability result was **re-checked on 15 Sep** against the current
  tree (every importer of `ai_advisory`, every caller of `get_trade_rationale`,
  every import inside the package). Each line cited below was read.
* The live evidence: `s09-s10-ai-and-regime/tools/ai_evidence.py` (read-only):
  launches that fell back to the demo engine, AI Advisor questions, AI
  failures, and the report narratives.
* The operator's words: Checkpoint A (R4 §4.00, §4.001), the Q1 answer
  (R8 §8.5), and the register entries AE-05, AE-15, AE-25 and AE-30.

**The deployed configuration** (R3 §3.5; `.env` re-read 15 Sep): both request
classes use the **local** model, `openai/gpt-oss-20b`, served by LM Studio at
`http://localhost:1234/v1`. The Anthropic model is configured and selected by
neither class, so no AI request leaves the machine.

---

## 11.1 What the AI layer consists of

| Part | What it does | Where |
|---|---|---|
| Engines | `LocalEngine` (OpenAI-compatible POST), `AnthropicEngine`, `DemoLLMEngine` (canned replies). Chosen **once per launch**; an unreachable local server gives the demo engine for the whole session | `runtime.py:138-154` |
| Router | sends a request to the "sensitive" slot when positions are in its context, otherwise to the "general" slot | `router.py:37-49` |
| Service | five request types; four are wired to a screen or the reporter | `service.py` |
| Consumers | AI Advisor, Strategy Workbench, Regime Monitor (two panels), the daily and weekly report narrator | investigator 4 §3.1, re-checked |

The five request types (investigator 4 §3.4):

| Request | Asked from | Output schema | Where the output goes |
|---|---|---|---|
| `get_regime_narrative` | AI Advisor (`ai_advisor.py:353`), Workbench (`workbench.py:593`) | `AdvisoryRecommendation`: buy / sell / hold, rationale, confidence, risk flags | the screen's text panel |
| `get_macro_assessment` | Regime Monitor (`regime_monitor.py:469`) | `MacroAssessment`, including `suggested_exposure_scalar` | the panel; the scalar is **displayed only** (`schema.py:26-31`) |
| `get_macro_matrix_narrative` | Regime Monitor (`regime_monitor.py:286`) | `MacroMatrixNarrative`; its figures are **overwritten** by the computed ones (`service.py:199-299`) | the panel |
| `get_performance_narrative` | the reporter (`runtime.py:906-914`) | the rationale text only | "Analyst notes" in `daily_reports.md` / `weekly_reports.md` |
| `get_trade_rationale` | **no caller in `src`** | `GuardedRecommendation` | would call `RiskEngine.evaluate_order` (`guards.py:57-83`), writing a `risk_decisions.csv` row |

## 11.2 The brief's twelve items

| The brief asks | Answer (code) | Live evidence |
|---|---|---|
| **Inputs to the LLM** | A symbol question sends: the regime label and probabilities; every position `{symbol: qty}`; book risk metrics; fundamentals; the next results date; the held position's entry, P&L, R and distances; the rails' verdict; news; the operator's question (`context.py:82-218`). The macro and report requests send market-wide figures; **the report text includes per-symbol quantities and prices** (`reports.py:135-138`), against a comment saying it does not (`service.py:130-131`). Only secret values are redacted (`guards.py:30-38`). A prompt over 8,000 characters is refused, not cut (`guards.py:41-46`) | — |
| **Outputs from the LLM** | The schemas in 11.1 | 34 AI Advisor questions logged (11.3); model-written notes in 14 reports |
| **Is the output structured?** | **Yes.** Every reply is validated into a pydantic schema. Anthropic: one forced tool whose input is the schema (`llm_engine.py:73-117`). Local: `response_format` json_schema, then json_object, then text, then validation (`llm_engine.py:150-228`) | — |
| **Can it influence strategy selection?** | **No.** Strategies are deployed from settings at launch and from the Workbench's Deploy button, an operator action (`workbench.py:427-434`). No strategy module imports `ai_advisory` | — |
| **Can it influence sizing?** | **No.** `RiskEngine.regime_scalar` is written only by `RegimeEvent` (`risk_engine/engine.py:139-141`). The model's `suggested_exposure_scalar` is displayed and applied nowhere | — |
| **Can it influence approval?** | **No.** Neither the autonomy gate nor the Blotter reads AI output | every ASX-era order was signed by the gate (R10 §10.3) |
| **Can it influence execution?** | **No.** `ai_advisory` imports only `config`, `security`, `macro_analysis` and `risk_engine` (the last for the unwired guard): nothing from the OMS, the broker adapter, autonomy or strategies | — |
| **Can it call tools?** | **No executable tools.** The Anthropic engine's single tool is the output channel; nothing runs it and there is no agentic loop. The local engine has no tools | — |
| **Can it access broker functions?** | **No** (the imports above) | — |
| **Can it alter persistent state?** | **Only text.** The narrator appends "Analyst notes" to the report files, and the log records requests and failures. It writes no setting, ledger, journal or order. The unwired `get_trade_rationale` would write a `risk_decisions.csv` row | 14 reports carry model notes (11.3) |
| **What happens if the LLM is unavailable?** | At launch: the demo engine for that session (`runtime.py:149-153`). At a request: the screen shows "Advisor unavailable" (`ai_advisor.py:360-365`); the report is written without notes (`reporter.py:256-264`). **An empty narrative is dropped with no log line** (`reporter.py:261`) | **3 launches** fell back to demo, each trying `http://localhost:8000`: 16 Aug 21:51 (M92), 30 Aug 21:13 (M156), 11 Sep 09:47 (M174). Each was followed by another launch before the next session opened: 17 Aug 10:28, 30 Aug 21:23, 11 Sep 09:57. **No session ran on the demo engine** (derived from the launch times against session hours). 7 "Could not generate a report narrative" lines on 6 days (1, 4, 5, 6, 7 Aug; 3 Sep) |
| **Can the trading path operate without it?** | **Yes, entirely.** `AIAdvisoryService` is not registered with the orchestrator, and no trading-path module imports it (investigator 4 §3.9, re-checked) | every entry and exit in the ASX era came from the swing rule, the rails and the gate (R10) |

**Why the three launches tried port 8000** is NOT DETERMINED. The warning
prints the configured URL (`runtime.py:152`). The `.env` today names port 1234
and was last written at 09:56:50 on 11 Sep, between the third fallback and
the next launch. A successful launch logs nothing, so which URL the other
launches used, or whether they were set to the local model at all, is not
recorded.

## 11.3 What the AI was used for, live

From `ai_evidence.py`:

* **AI Advisor: 34 questions on 11 days, 28 Aug – 11 Sep**, 26 about a held
  symbol and 8 about one not held. The per-question log line was added by
  M153 (`71ebec4`, 28 Aug 08:43), so questions before then are not counted.
  None logged a failure.
* **Workbench AI note:** 1 failure (7 Sep).
* **Macro matrix narrative:** no disagreement warnings, and no refusal given
  invented figures.
* **Reports:** 17 daily reports (20 Aug – 11 Sep). 13 carry model-written
  notes and none carries the demo notice. The 4 without notes are 26 Aug,
  3 Sep (a logged failure) and the two regenerated 9 Sep reports. Of 3 weekly
  reports, 1 carries notes. 26 Aug and the weeks ending 4 Sep and 11 Sep have
  no notes and no failure line, so by the code their narrative came back
  empty (derived from `reporter.py:261`).
* **No human action on an AI answer is recorded.** No screen can create a buy.
  A human can act on an AI "sell" only through the manual close, and the
  manual close has never run live (R10 §10.3).

## 11.4 The brief's principle

> **"AI may analyse, explain, challenge or provide context, but deterministic
> risk and execution controls retain authority over actual trading."**

| Part of the principle | Finding |
|---|---|
| Deterministic controls retain authority over trading | **Holds, completely.** No AI output reaches strategy selection, sizing, approval, the OMS, the broker or settings (11.2) |
| AI may analyse, explain, provide context | **Yes**, on four screens and in the reports, on request |
| AI may **challenge** | **Only on a screen.** An AI "sell" or "hold" on a held symbol, or a "hold" against a signal, reaches no control. The approved 26 Jul plan let the AI veto or shrink entries; Claude built without it and disclosed that after the build (AE-05, CE-021) |

So the implementation meets the principle, more strictly than it asks: the
AI has no operative role at all.

**A false statement in the system prompt.** Every request tells the model
"Final trading decisions are made by a human, not by you" (`prompts.py:17`).
In the deployed mode (`auto`) the autonomy gate makes them, and it signed
every order of the ASX era (R10 §10.3). The model is told something untrue
about the system it advises on.

## 11.5 Against the operator's intent

The governing statements:
* **Checkpoint A (R4 §4.00, §4.001):** an app "capable of making recommended
  trades **using AI**"; in autonomous mode it acts "on its recommendation …
  subject to the embedded safety rails and in accordance with the selected
  strategy".
* **Q1 (R8 §8.5):** "The recommendations made by the AI should be no different
  whether in Autonomous mode or Manual mode. The difference is the fulfilment
  process. It's decision making however, should be informed around strategy
  and rules."
* **Earlier requests:** AI veto/shrink on entries, approved 26 Jul (AE-05);
  AI using earnings "to deduce it's recommended action" (AE-15, 4 Aug); "a
  buy/sell/hold recommendation formed, against the prevailing market Regime,
  whilst following the rules of the current strategy" (AE-25, 21 Aug).

| The intent | The system |
|---|---|
| The AI forms the recommendation | **No.** The recommendation both modes act on is the swing rule's signal, formed with no AI (`swing.py:115-178`). The AI's buy/sell/hold (M136) is produced on request, for one symbol, and is not attached to any order |
| The same recommendation in both modes; only fulfilment differs | **Half.** The same thing is acted on in both modes (the swing signal), and the AI's answer does not depend on the mode. But neither mode acts on the AI's answer. In recommend mode a human signs the swing's proposals in the Blotter (`blotter.py:458`), and the AI's view is not shown beside them |
| Informed around **rules** | **Partly.** The model receives the rails' verdict on the symbol: session, allow list or position, quarantine, regime eligibility, and the autonomy gate asked with a 1-share probe (`symbol_verdict.py:131-136`, `:262-263`) |
| Informed around **strategy** | **No.** The AI Advisor passes no `candidate_signal` (`ai_advisor.py:311-323`), so the model never sees what the swing rule says about the symbol. It is not given the swing specification (`Swing Trader methodology.md`) either. Only the Workbench passes a strategy name and backtest figures (`workbench.py:576-580`) |

**The gap runs the opposite way to the brief's concern.** The brief guards
against an AI with too much influence. Here the AI has less than the operator
intended: none. R7 item 3 stays **E**.

**One statement to reconcile.** On 8 Sep the operator pasted an architecture
for the macro matrix: "The Execution Layer (HMM Engine): The sole source of
monetary authority … The LLM operates exclusively as an editor and
copywriter", and said "yes build it" (AE-30). Checkpoint A and Q1, six days
later, give the AI the recommendation. The audit reads AE-30 as scoped to the
matrix. That reading is the operator's to confirm (11.7).

## 11.6 Other facts found

* **The output guard and `get_trade_rationale` are unwired** (R7 item 56).
  They are the only code in which an AI answer would meet the risk engine.
* **The router's "daily" call counter is never reset** (`router.py:35, 44,
  47`), so it counts per process, not per day. After the 200th general
  request in a process, every request goes to the sensitive slot. That matters
  only when the two slots name different engines; today both are local.
* **If the general slot were set to Anthropic**, the report narrative would
  send per-symbol quantities and prices to the cloud, contrary to the comment
  at `service.py:130-131` (derived; not the deployed configuration).

## 11.7 For Checkpoint B

* **Q-R11.** Does the 8 Sep architecture's "the LLM operates exclusively as an
  editor and copywriter" (AE-30) apply to the macro matrix only, or to the AI
  generally? Checkpoint A and Q1 read as giving the AI the recommendation.

## 11.8 NOT DETERMINED

* Which LLM URL the launches without a fallback used, and why three launches
  were configured for port 8000 (above).
* How many AI Advisor questions were asked before 28 Aug (no log line then).
