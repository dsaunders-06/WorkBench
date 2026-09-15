# QAT Design Recovery & Design Intent Audit: Error-Log Back-fill Register

**Prepared:** 15 September 2026. The back-fill of Claude's errors across
QAT's whole history, which the audit plan listed as outstanding (tracker
section 7). The entries themselves are in `docs/CLAUDE_ERROR_LOG.md`. This
register shows how they were found and where in the development they
entered.

## How the history was searched

Three read-only tools, in `backfill/tools/`:

| Tool | Reads | Found |
|---|---|---|
| `fix_commits.py` | every commit (`git log`) | **632 of 984** commits carry a fix, retraction or correction cue. The cue words are broad (`fix`, `live`, `correct`), so this over-counts. It is an inventory, not a list of errors |
| `doc_incidents.py` | HANDOFF, the archived HANDOFF, ROADMAP (Claude's own records) | 73 warning headings and 156 admission lines: every place the writer recorded that something it did was wrong |
| `operator_corrections.py` | the operator's 1,411 typed messages from 24 Jul (de-duplicated across resumed sessions) | 69 carry a correction cue. About a dozen are genuine corrections; the rest are prompts and notices that quote the words |

**What became an entry:** an error that reached the broker, the records, a
decision, or a document the operator relied on. Each was checked against
its fix commit and, where it acted live, a log line.
`error_log_table.py` then placed every entry in the period its error
entered: from the date in its Made line, or from the commit that introduced
the mechanism (listed in the tool).

**The commit inventory by period** (`fix_commits.py`, flagged / all commits):

| Period | All commits | Flagged | Fix touching `src/` | Retractions | Docs only |
|---|---|---|---|---|---|
| 1 First builds, 24–31 Jul | 50 | 36 | 27 | 3 | 0 |
| 2 US-era hardening, 1–18 Aug | 309 | 184 | 94 | 20 | 35 |
| 3 ASX move, 19–23 Aug | 107 | 72 | 38 | 9 | 23 |
| 4 Live ASX, 24 Aug–11 Sep | 483 | 325 | 129 | 52 | 129 |
| 5 M175 and the audit, 12–15 Sep | 35 | 15 | 0 | 2 | 14 |
| **Total** | **984** | **632** | **288** | **86** | **201** |

## Every entry, by the period its error entered
| Period entered | Entry | Severity | Error |
|---|---|---|---|
| first builds (24-31 Jul) [fa9ba47: _IB_STATUS_MAP, first build] | CE-003 | High | Duplicate order transmission: four times the intended position, twice |
| first builds (24-31 Jul) [fa9ba47: booking at sign-off, first build (R7 #42)] | CE-005 | High | The app booked a position for an order the broker never transmitted |
| first builds (24-31 Jul) | CE-021 | High | Built autonomy without the AI entry role the operator had just approved |
| first builds (24-31 Jul) | CE-022 | Medium | Removed the kill switch's staleness trip and left the documentation saying it trips |
| first builds (24-31 Jul) | CE-025 | Low | A code comment and a commit message describe an entry buffer swing never had |
| first builds (24-31 Jul) | CE-026 | High | The first build was asked to port the operator's swing methodology and did not |
| first builds (24-31 Jul) | CE-027 | Medium | The first build left out parts of the brief without asking |
| first builds (24-31 Jul) [ab1ba97: OMS.pending_orders] | CE-041 | High | Two entries signed in the same second took the book to eleven against a cap of ten |
| first builds (24-31 Jul) | CE-042 | High | The kill switch lived in memory; restarts cleared halts silently, and wrong advice followed |
| first builds (24-31 Jul) [9b9fa50: M27b, eligibility gate] | CE-049 | Medium | Strategy gating ran on a hard-coded "sideways" default for the first 20 minutes of every session |
| first builds (24-31 Jul) | CE-055 | Medium | The 30-day time stop: a third-party example value adopted without checking it against the strategy |
| first builds (24-31 Jul) | CE-063 | Medium | The first build flooded the Blotter, with sells for symbols the account did not hold |
| first builds (24-31 Jul) | CE-064 | Medium | The first build invented sectors and showed them as data, and allowed unlimited leverage |
| first builds (24-31 Jul) | CE-065 | Medium | `.gitignore` kept the whole market-data layer out of git |
| US-era hardening (1-18 Aug) | CE-037 | High | A monitoring script blinded the log for 66 minutes on the morning of the first live orders |
| US-era hardening (1-18 Aug) [3ac992e: M50, fills recorded after downtime] | CE-039 | High | Seven impossible closed trades from the absorb path replaying across a restart |
| US-era hardening (1-18 Aug) | CE-043 | High | The sector cap was never wired; nine entries went in on 25 Aug with it inert |
| US-era hardening (1-18 Aug) | CE-056 | Medium | Regime metadata is never carried on a restored lot, so the ledger has none |
| US-era hardening (1-18 Aug) [3ac992e: M50 replay; the warning is from ab1ba97] | CE-066 | High | The ledger's exit matching dropped real shares twice, and its warning explained the shortfall away |
| ASX move (19-23 Aug) | CE-001 | Medium | Built `Settings()` under the Bash sandbox and chased an imaginary rate limit |
| ASX move (19-23 Aug) | CE-002 | Medium | Took a plan document's currency as fact and reported a false 28% sizing error |
| ASX move (19-23 Aug) [fbce78d: M97, recent_fills on IBKR] | CE-040 | High | The first exit: 179 of 183 executions never reached the ledger |
| ASX move (19-23 Aug) | CE-045 | High | The app never asked IBKR for the delayed data tier; an exit was refused, and three diagnoses were wrong |
| ASX move (19-23 Aug) | CE-047 | High | Every entry bracket's protective legs reduced instead of cancelling |
| ASX move (19-23 Aug) [40274fa: M95, the IBKR order builders] | CE-048 | High | The app's own orders carried no time-in-force, and a fix treated the wrong half of 10148 |
| ASX move (19-23 Aug) | CE-053 | Medium | A finding said IBKR serves no news; IBKR was never asked |
| ASX move (19-23 Aug) | CE-061 | Low | README and the product description left stale since 20 August |
| ASX move (19-23 Aug) | CE-062 | Medium | Told the operator they had clicked "Start session now"; they had not |
| live ASX (24 Aug-11 Sep) | CE-004 | Medium | The deploy record typed by hand, wrong ten times |
| live ASX (24 Aug-11 Sep) | CE-006 | Medium | HANDOFF's broker row carried a stale fact for about nine days |
| live ASX (24 Aug-11 Sep) | CE-007 | Medium | The handover prompt handed sessions a stale picture |
| live ASX (24 Aug-11 Sep) | CE-008 | Medium | A superseded finding read as current produced a wrong recommendation |
| live ASX (24 Aug-11 Sep) | CE-009 | Medium | Two pre-flight tests read the real clock and failed on the first weekend |
| live ASX (24 Aug-11 Sep) | CE-010 | Low | The M175 repair's self-check, as planned, would have refused on the real data |
| live ASX (24 Aug-11 Sep) | CE-017 | High | An exit cancels the protective stop, then the kill switch refuses the exit, and blocks the replacement stop too |
| live ASX (24 Aug-11 Sep) | CE-032 | Medium | Read a confounded ablation as the VIX's information share, behind a comment that hid the confound |
| live ASX (24 Aug-11 Sep) | CE-044 | Medium | The order id the OMS handed out was not the id it answered to; the retry sweep stalled |
| live ASX (24 Aug-11 Sep) | CE-046 | High | A rejected sell's reversal had the wrong sign, and it acted live |
| live ASX (24 Aug-11 Sep) [7f3efe3: M151] | CE-050 | Low | A log filter sat on the wrong handler and reported work it did not do |
| live ASX (24 Aug-11 Sep) | CE-051 | Medium | Four ablation measurements were believed, then retracted: the harness was not ablating |
| live ASX (24 Aug-11 Sep) | CE-052 | High | The ledger's costs were modelled, never the commission IBKR charged |
| live ASX (24 Aug-11 Sep) | CE-054 | Medium | Five symbols added to the universe with no sector, so the sector cap could not apply to them |
| live ASX (24 Aug-11 Sep) [85b4c02: the footer's rewrite] | CE-057 | Low | `session_check`'s footer names the position count as the entry gate; on 11–12 Sep it was the aggregate cap |
| live ASX (24 Aug-11 Sep) | CE-058 | Medium | Tests that could not fail were counted as evidence |
| live ASX (24 Aug-11 Sep) | CE-059 | Low | A pipe hid a build failure, again |
| live ASX (24 Aug-11 Sep) | CE-060 | Low | Two different builds carried one milestone label on 4 Sep |
| M175 and the audit (12-15 Sep) | CE-011 | Low | Attributed a figure to the wrong source in an audit document |
| M175 and the audit (12-15 Sep) | CE-012 | Low | Misdescribed what the kill switch blocks |
| M175 and the audit (12-15 Sep) | CE-013 | Medium | Overstated what the session transcripts cover |
| M175 and the audit (12-15 Sep) | CE-014 | Low | Command slips during the 12 September session |
| M175 and the audit (12-15 Sep) | CE-015 | Low | Searched the operator's separate project without asking |
| M175 and the audit (12-15 Sep) | CE-016 | High | Searched the operator's computer outside the project folders without permission |
| M175 and the audit (12-15 Sep) | CE-018 | Medium | The capability write-ups stated the design objective from agent-authored documents |
| M175 and the audit (12-15 Sep) | CE-019 | Low | Command slips during the 14 September session |
| M175 and the audit (12-15 Sep) | CE-020 | Medium | CE-013's correction was itself wrong: the transcripts cover every day from 24 July |
| M175 and the audit (12-15 Sep) | CE-023 | Low | Slips and pre-delivery catches in the second 14 September session |
| M175 and the audit (12-15 Sep) | CE-024 | Low | The handover said "all 449 entries refused"; it was 449 decisions on 4 symbols |
| M175 and the audit (12-15 Sep) | CE-028 | Low | A one-off edit script emptied a report file |
| M175 and the audit (12-15 Sep) | CE-029 | Low | Told the operator the decision journal was missing sign-offs that were there |
| M175 and the audit (12-15 Sep) | CE-030 | Medium | The audit plan's stage numbers collide with the brief's and the report's section numbers |
| M175 and the audit (12-15 Sep) | CE-031 | Low | Pre-delivery catches while drafting R9 (brief §7) |
| M175 and the audit (12-15 Sep) | CE-033 | Low | Catches while drafting R11 and R12, and one count that reached the operator |
| M175 and the audit (12-15 Sep) | CE-034 | Medium | Called TNE's 60-share ledger row "the remnant of the 24 Aug duplicate unwind" |
| M175 and the audit (12-15 Sep) | CE-035 | Low | Answered "Continue" with "No response requested", then misstated where the work stood |
| M175 and the audit (12-15 Sep) | CE-036 | Low | R18 listed two questions as UNKNOWN that R6 had already answered |
| M175 and the audit (12-15 Sep) | CE-038 | Low | The audit called the log hole's cause NOT DETERMINED; a commit records it |

**Count by period entered** (`error_log_table.py`):

| Period | Entries | High | Medium | Low |
|---|---|---|---|---|
| 1 First builds, 24–31 Jul | 14 | 6 | 7 | 1 |
| 2 US-era hardening, 1–18 Aug | 5 | 4 | 1 | 0 |
| 3 ASX move, 19–23 Aug | 9 | 4 | 4 | 1 |
| 4 Live ASX, 24 Aug–11 Sep | 18 | 3 | 10 | 5 |
| 5 M175 and the audit, 12–15 Sep | 20 | 1 | 5 | 14 |
| **Total** | **66** | **18** | **27** | **21** |

## What the register shows

1. **The serious errors entered early and surfaced late.**
   - 14 of the 18 High-severity errors entered before the first live order
     on 24 Aug: 6 in the first builds, 4 in US-era hardening, 4 in the ASX
     move.
   - Most of them were found only when the live account exercised them.
     Examples: the duplicate transmission (CE-003), the booking of an
     unsent order (CE-005), the absorb path (CE-039, CE-040, CE-066), the
     unwired sector cap (CE-043), the missing time-in-force (CE-048).
   - Tests passed throughout (CE-058).
2. **The first build carries the most.** Its 14 include the design-level
   drift: the swing rule (CE-026), the brief's omissions (CE-027) and the
   AI's role dropped (CE-021). It also holds the latent defects that bit on
   24–26 Aug.
3. **In the live weeks the errors changed kind.** Fewer entered in code, and
   more in records and claims: stale handovers (CE-006, CE-007, CE-008), a
   confounded measurement (CE-032), modelled costs (CE-052).
4. **The audit's own errors are mostly Low and caught before delivery**
   (14 of 20). The exceptions:
   - CE-016, the search-boundary breach, High;
   - five Medium: CE-013, CE-018, CE-020, CE-030, CE-034.

## Limits

* The commit inventory is a keyword sort. An error fixed in a commit whose
  message names no cue is not in it.
* An error never fixed and never noticed is in none of the three sources.
* Commit messages and HANDOFF are Claude's words. Where an entry rests on
  one, it says so. Where it acted live, a log line was read.
* Transcripts are complete from 24 Jul (CE-020). The four claude.ai chats
  before that were read for intent (R4), not searched for errors.