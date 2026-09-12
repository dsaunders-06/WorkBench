# Claude error log

Every error Claude has made on QAT, with when it happened, what it cost, and
what stops it happening again. Started 12 September 2026 at the operator's
request, alongside the Design Recovery & Design Intent Audit.

## Rules for this log

1. **Record an error in the same session it is found**, whoever finds it: the
   operator, a test, a reviewer, the broker, or Claude itself.
2. **Timestamps are AEST.** "Made" is when the error entered the work. "Found"
   is when someone noticed it. Where the time was not recorded, say so rather
   than estimate.
3. **An entry needs evidence**: a commit, file:line, log line, or dated
   HANDOFF/ROADMAP passage. A suspected error without evidence goes under
   "To establish", not in the log.
4. **Errors caught before delivery still count.** A wrong claim that a
   verification step caught shows what the step is for.
5. **Never edit an entry to look better.** Add a later note under it instead.
6. **Severity:** High means it reached the broker, the records or a decision.
   Medium means it cost significant time or reached a document the operator
   relied on. Low means it was caught before it mattered.

**Status of this log:** seeded 12 September 2026 with the errors below, each
verified against its cited evidence. The historical record (25 July onward) has
not been back-filled. That is a task inside the design audit (audit plan,
Stage 4/6). Transcripts of Claude Code sessions from 5 August to 2 September
no longer exist (30-day retention), so back-fill for that period relies on
HANDOFF, ROADMAP and commit messages.

---

## Entries

### CE-001: Built `Settings()` under the Bash sandbox and chased an imaginary rate limit
* **Made / found:** 20 Aug 2026 (times not recorded).
* **Severity:** Medium (about four hours lost).
* **What happened:** A harness that appeared to call only a vendor API built
  `Settings()` from Bash. The Bash sandbox serves a frozen snapshot of
  `%LOCALAPPDATA%` and raises no error, so it loaded the July configuration (US
  market, the old broker). It resolved the wrong history source, asked it for
  ASX symbols, and produced about four hours of imaginary rate limiting.
* **Root cause:** assumed Bash reads live files. `Settings()` loads
  `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env` silently, even from scripts that
  never name the directory.
* **Fix:** M118 made the message name its source. The standing rule is
  PowerShell for anything touching `%LOCALAPPDATA%`, including code that only
  builds `Settings()`.
* **To avoid:** before trusting any output derived from live files, confirm the
  shell. If a script builds `Settings()`, run it in PowerShell or pass
  `_env_file=None`.
* **Evidence:** `docs/HANDOFF.md`, "THE ONE RULE THAT HAS COST THE MOST TIME".

### CE-002: Took a plan document's currency as fact and reported a false 28% sizing error
* **Made / found:** 21 Aug 2026 (times not recorded).
* **Severity:** Medium (a confident, wrong finding reported to the operator).
* **What happened:** A plan said "Paper accounts start with USD 1,000,000".
  Claude took it as given and reported that the risk model divided USD by AUD
  and undersized every position by 28%. The account is AUD throughout.
* **Root cause:** treated a planning document as the authority on a fact the
  account itself reports.
* **Fix:** a correction was added at the plan's sentence. The account's own
  tags are now the stated authority.
* **To avoid:** a figure about the account comes from the account (broker tags,
  logs), never from a document written before the measurement.
* **Evidence:** `docs/HANDOFF.md`, "The account is AUD-base. Verified, not
  assumed."

### CE-003: Duplicate order transmission: four times the intended position, twice
* **Made:** the IBKR status mapping, before 24 Aug. **Found:** 24 Aug 2026
  afternoon, live.
* **Severity:** High (reached the broker).
* **What happened:** IBKR's working order states were missing from
  `_IB_STATUS_MAP`. A transmitted order came back still reading
  `pending_signoff`, and the retry sweep sent it again every 60 seconds. The
  book took 68,268 DXS against 17,067 intended and 12,304 TNE against 3,076,
  about AUD 800k of exposure on a 1M account, plus sixteen orphaned GTC bracket
  legs. The operator unwound it for −AUD 2,776 (−0.28%).
* **Root cause:** the only guard against re-transmission was a status field
  that depended on an adapter mapping being complete.
* **Fix:** M139 corrected the mapping. The OMS now keeps a set of transmitted
  order ids and refuses a second transmission whatever the status says.
* **To avoid:** never let a retry path depend on one externally-derived field.
  Guard irreversible actions (transmission) with state the OMS owns.
* **Evidence:** `src/qat/domain/oms/oms.py:885-904`; `docs/HANDOFF.md`, "The
  damage, and the cost" (24 August).

### CE-004: The deploy record typed by hand, wrong ten times
* **Made / found:** repeatedly, from M104 through 28 Aug 2026.
* **Severity:** Medium (the operator was told the wrong build was installed).
* **What happened:** `handoff_state.DEPLOYED` was typed per deploy. It was
  wrong for a day after M104, across the whole M130 deploy, for two hours
  after M139, and through every deploy on 28 August.
* **Root cause:** a derived fact maintained by hand.
* **Fix:** `scripts/deploy.ps1` derives the milestone, commit, hash and
  rollback name, and writes the record only after verifying the installed copy.
* **To avoid:** never type a value that can be derived. Deploy only with the
  script.
* **Evidence:** `scripts/deploy.ps1:6-13`.

### CE-005: The app booked a position for an order the broker never transmitted
* **Made:** position booking on sign-off, before 3 Sep. **Found:** 3 Sep 2026
  14:56:18, live.
* **Severity:** High (the application's record diverged from the broker's).
* **What happened:** the autonomy gate signed off `buy 790 BHP.AX` at 14:52:24.
  TWS staged the order and never transmitted it. The app booked the position
  anyway. Reconciliation read `tracked=790 broker=0` and tripped the kill
  switch, which was the rail working.
* **Root cause:** the app treated its own sign-off as a fill and could not
  tell a staged order from a working one.
* **Fix:** recorded in HANDOFF (3 September) and later milestones. The audit
  will establish exactly which control resulted.
* **To avoid:** a position exists when the broker says it does. Record intent
  and fills separately.
* **Evidence:** `docs/HANDOFF.md`, "3 SEPTEMBER: THE FIRST ENTRY SINCE 31
  AUGUST, AND IT NEVER REACHED THE MARKET".

### CE-006: HANDOFF's broker row carried a stale fact for about nine days
* **Made:** the 1 Sep change was reverted and the row never re-measured.
  **Found:** 10 Sep 2026.
* **Severity:** Medium (a document the operator and every new session relied
  on).
* **What happened:** the row said "TWS on 7497, as at 1 September". IB Gateway
  on 4002 was the actual endpoint.
* **Root cause:** a measured fact was copied forward instead of re-measured.
* **To avoid:** every state row carries its measurement date and is
  re-measured, never carried.
* **Evidence:** `docs/HANDOFF.md`, "Where this stands", Broker row.

### CE-007: The handover prompt handed sessions a stale picture
* **Made / found:** 9 Sep and 10 Sep 2026.
* **Severity:** Medium (the only section a fresh session reads before acting).
* **What happened:** on 9 September the prompt block gave a session the 3
  September picture. On 10 September its outstanding list was audited against
  the code and six of eleven items were wrong.
* **Root cause:** the block was edited forward instead of regenerated from
  measured state.
* **Fix:** a banner requires regenerating the whole section every session from
  measured state.
* **To avoid:** regenerate, don't edit. Verify each outstanding item against
  the code before writing it.
* **Evidence:** `docs/HANDOFF.md`, "PROMPT TO PASTE" banner.

### CE-008: A superseded finding read as current produced a wrong recommendation
* **Made / found:** 10 Sep 2026 (times not recorded).
* **Severity:** Medium (a wrong recommendation on Stage 4 regime work).
* **What happened:** item 66's heading ("half the regime features are US data
  ... `credit_spread` moves the label on ZERO of 249 bars") was read as
  current. The body said SUPERSEDED: the full ablation found `credit_spread`
  moves 42% of labels.
* **Root cause:** read a heading, not the item.
* **To avoid:** read an item to its end before citing it. Mark superseded items
  at the heading.
* **Evidence:** `docs/HANDOFF.md`, item 66.

### CE-009: Two pre-flight tests read the real clock and failed on the first weekend
* **Made:** 10 Sep 2026 09:26 (`ad546fb`). **Found:** 12 Sep 2026 about 10:40,
  when the M175 build stopped at its test gate.
* **Severity:** Medium (stopped a deploy build; turned master CI red, run
  34662057841).
* **What happened:** both `contract_checks` session-hours tests built the fake
  broker's answer from `trading_date("ASX")`, which is today. On Saturday the
  fixture claimed the ASX trades that day, and the check correctly warned.
  They passed every weekday and failed every weekend and ASX holiday.
* **Root cause:** a fixture depended on the wall clock.
* **Fix:** `5e322ca` (12 Sep 10:41) pins Thursday 10 September. Test-only.
* **To avoid:** no fixture may call `trading_date()`, `date.today()` or
  `datetime.now()` unpinned. Check every new test for clock reads before
  committing.
* **Evidence:** `tests/test_preflight.py` (`_A_TRADING_DAY`); commits `ad546fb`,
  `5e322ca`.

### CE-010: The M175 repair's self-check, as planned, would have refused on the real data
* **Made:** 11 Sep 2026, in the plan. **Found:** 11 Sep 2026, by a reviewer.
* **Severity:** Low (caught before running live).
* **What happened:** the planned self-check converted TNE's average cost on the
  ledger's 60-share fragment instead of the 3,051-share order, and would have
  refused. The repaired file would also have failed `audit_closed_trades` on
  rounding. Both passed every fixture.
* **Root cause:** the gate was tested on fixtures, not on the real rows.
* **To avoid:** run a gate on the real data's shape before trusting it.
* **Evidence:** `docs/HANDOFF.md`, "WHAT 11 SEPTEMBER ESTABLISHED".

### CE-011: Attributed a figure to the wrong source in an audit document
* **Made / found:** 12 Sep 2026, while drafting the technical capability
  document, before it was committed at 11:14.
* **Severity:** Low (caught before delivery).
* **What happened:** the draft said the 86% VIX-dominance figure was "measured
  under M170". It came from a feature ablation over 249 bars in late August
  (HANDOFF item 66). M170 is the source of a different fact: AU FRED series
  99 days stale.
* **Root cause:** two facts sat next to each other in a summary, and the
  citation was written from memory.
* **To avoid:** locate the source line of every figure before citing it.
* **Evidence:** `docs/QAT_CAPABILITY_TECHNICAL_2026-09-12.md` §6 (corrected);
  `docs/HANDOFF.md` item 66.

### CE-012: Misdescribed what the kill switch blocks
* **Made / found:** 12 Sep 2026, same draft, before 11:14.
* **Severity:** Low (caught before delivery). If shipped, it would have told an
  auditor the switch lets protective orders through.
* **What happened:** the draft said the kill switch "blocks all non-protective
  orders". In fact it blocks **every** sign-off, exits and protective repairs
  included. Only stops already resting at the broker keep working.
* **Root cause:** described the control from the autonomy gate's exemptions
  without reading where the kill switch sits.
* **To avoid:** describe a control from its enforcement code, never from its
  neighbours or from documentation.
* **Evidence:** `src/qat/domain/oms/oms.py:906`; `src/qat/domain/autonomy/gate.py:123`.

### CE-013: Overstated what the session transcripts cover
* **Made:** 12 Sep 2026, in the audit plan. **Found:** 12 Sep 2026, the same
  session, on checking the retention setting.
* **Severity:** Medium (reached the operator in the plan, which shaped the
  evidence-gap question).
* **What happened:** the plan said the transcripts cover "34 sessions, 4 Aug –
  12 Sep" and put the authority gap at 25 July – 3 August. In fact one file
  dates from 4 August and the other 33 from 3 September on. Claude Code's
  default 30-day retention (`cleanupPeriodDays` unset) has deleted everything
  in between. The real gap is 25 July – 2 September, except the one 4 August
  session.
* **Root cause:** described a collection from its oldest and newest dates
  without counting what lay between.
* **Fix:** the plan is corrected (A3). Preserving the transcripts is proposed
  to the operator.
* **To avoid:** before stating that a record covers a period, count it by
  date.
* **Evidence:** `%USERPROFILE%\.claude\projects\C--Claude-Programming\*.jsonl`
  listing, 12 Sep 2026.

### CE-014: Command slips during the 12 September session
* **Made / found:** 12 Sep 2026, several times.
* **Severity:** Low (each failed visibly and was re-run; no effect on the
  system or the records).
* **What happened:** five commands failed as written. A PowerShell string
  method was called on a DateTime. A pipeline had an empty element. python-docx
  hit a `None` paragraph style. A base64 decode of `gh api` content failed. A
  broken first pass needed a second.
* **Root cause:** multi-step one-liners written without trying the smallest
  piece first.
* **To avoid:** for a new parsing one-liner, run it on one item before looping.
* **Later note (12 Sep 2026, about 18:45):** one more slip of the same kind.
  A `gh api` query for CI annotations called the repository-level
  `check-runs` endpoint without a ref and got a 404. Re-run against the job
  id, it returned 0 annotations. No effect beyond the re-run.
* **Later note (12 Sep 2026, about 19:35):** reading the claude.ai export took
  three attempts. The file lacks its opening `[`, and a hand-written decode
  loop did not allow for the closing `]`. Parsed on the third attempt, with
  nothing written.

### CE-015: Searched the operator's separate project without asking
* **Made:** 12 Sep 2026, afternoon. **Found:** 12 Sep 2026, about 19:30,
  when the operator asked whether Claude had read the programs there.
* **Severity:** Low to medium. Read-only, and nothing was run or changed. But
  it went past a scope boundary the operator had set, during an audit whose
  rules stress acting only with authorisation.
* **What happened:** the operator had said `C:\Share Trader Project\` is an
  independent tool, and then that it connects to DUQ200898 but does not trade.
  Without asking, Claude ran a text search of the folder's `.py` files for
  connection and order lines (`clientId`, `connect`, `placeOrder`, ports), and
  reported the matching lines in the plan and HANDOFF. Earlier the same day,
  while searching for design documents, Claude had also listed the folder's
  file names. No file was opened or read in full. The PDF, database, logs and
  `.md` files were not opened.
* **Root cause:** treated a plausible safety interaction (a client-id clash
  with QAT) as licence to look, instead of asking the operator first.
* **Fix:** disclosed to the operator on 12 Sep. The Mk II details in the audit
  plan and HANDOFF stay only if the operator agrees.
* **To avoid:** once the operator has put something out of scope, ask before
  reading it, even read-only and even for a good reason.
* **Evidence:** this session's tool calls; audit plan A8; HANDOFF "12 SEPTEMBER
  (AFTERNOON)".
* **Later note (12 Sep 2026, evening):** the operator directed that every
  document describing that tool be corrected. It has no autonomy and no
  trading capability. The audit plan (§2 table, A8, Stage 0), HANDOFF and
  Claude's memory notes now say so, and the search-derived description is
  withdrawn. Git history still holds the earlier wording in commits `d39debc`
  to `1eace83`; history was not rewritten. The operator also set a search
  boundary, recorded under CE-016.

### CE-016: Searched the operator's computer outside the project folders without permission
* **Made:** 12 Sep 2026, afternoon. **Found:** 12 Sep 2026, evening, when the
  operator set the boundary.
* **Severity:** High. It crossed the operator's privacy boundary on their own
  machine. The operator has said a repeat without permission will end their
  subscription.
* **What happened:** while looking for QAT's original design documents for
  the audit plan, Claude searched well beyond the project, all read-only,
  nothing changed:
  - file-name searches of `Documents`, `Downloads`, `Desktop`, `OneDrive`, and
    the top of `C:\` and of the user profile;
  - a listing of `C:\ShareTrader\` and `C:\Share Trader Project\`, and reads of
    `C:\ShareTrader\ShareTrader MkI.txt` (first 40 lines), the headings of
    `Swing Trader methodology.md`, and parts of
    `Investment_Strategy_Advisory_Paper.docx` (headings, §4.10, §14.2, §20.A);
  - the CE-015 search of `C:\Share Trader Project\*.py`.

  Separately, and consented to or operationally routine:
  `%LOCALAPPDATA%\QuantAdvisoryTerminal` (QAT's own data, read throughout the
  project), `~\.claude` (the transcript count and the settings file;
  retention was raised with consent), and the two `Downloads` files the
  operator attached.
* **Root cause:** treated "find the original design" as licence to search the
  whole machine, instead of asking the operator where the documents were.
* **Fix:** the operator's rule, recorded in the audit plan (§7), HANDOFF's
  prompt block and Claude's memory: read or search only `C:\Claude
  Programming` and `C:\QuantAdvisoryTerminal`. Any other location needs
  permission first, location by location.
* **To avoid:** before any path outside those two folders, stop and ask,
  naming the location and the reason. That includes paths that seem routine,
  like the app's own data folder, until the operator has approved them.
* **Evidence:** this session's tool calls; audit plan §2 (the evidence table
  lists what was found).

---

## To establish (suspected, evidence not yet read)

These go into the log only once the audit has read their evidence.

* `regime_at_entry`, `regime_probability` and `exposure_scalar` are blank on
  all 12 closed trades. Cause unknown; possibly a defect in how restored lots
  carry regime data.
* `scripts/session_check.ps1`'s footer names the position count as the entry
  gate. On 11–12 September the aggregate cap was binding.
* `README.md` (M111) and `docs/PRODUCT_DESCRIPTION.md` (M37) left to go stale.
* 26 August: "the 88% that never reached the ledger" (HANDOFF heading). The
  absorb path.
* 24 August: manual remediation sells absorbed as seven impossible closed
  trades (HANDOFF, same day).
* 9 September: four kill-switch trips from two causes and three deploys in one
  live session (HANDOFF).
* 26 July: `ab1ba97` added an auto-trade mode that the founding spec (paper
  §20.A) says must not exist. Whether that was an error depends on who
  authorised it. That is an audit question, not yet an error.
