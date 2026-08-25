"""What build is this, exactly (M27b tooling).

The install was on M26 while the repository was four milestones ahead, and
nothing in the running application could have told you so - the Settings
screen showed configuration, never provenance. `pyproject`'s `0.1.0` is no
help either: it has never been bumped, so it reads identically on every build
ever made.

Three facts identify a build, and they are deliberately shown together:

* **the milestone** - what a human calls it, and the only part that can go
  stale, because it is maintained by hand;
* **the commit** - what it was actually built from, which cannot;
* **when it was packaged** - which catches the case where the milestone label
  and the commit are both right but the executable is old.

A frozen build has no git and no repository, so the stamp is captured at
package time into a generated module (see `invoke package`). Running from a
checkout there is no stamp, so git is asked directly and the answer is always
current. Neither path can silently report the other's answer: `source` says
which one produced the numbers.
"""

from __future__ import annotations

import subprocess  # nosec B404 - git metadata for display, no untrusted input
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from qat.domain.display_dates import format_display_date

# Bump when a milestone ships. Its accuracy is not load-bearing - the commit
# and the build time beside it are the ground truth, and a stale label is
# visible precisely because they disagree with it.
#
# Compound, because the numbering is a naming scheme rather than a sequence:
# M39-M44 were enumerated as future gaps on 4 August, before M45-M50 existed, so
# M40 shipping after M50 is not a regression. "M40" alone would read to an
# operator as the application having gone backwards.
# Compound, and this build is exactly the case the note above describes: M39 was
# enumerated as a future gap on 4 August, so "M39" alone would read to an
# operator as the application having gone backwards from M86. Two milestones
# ship here and both are named.
#
# M88 ships alone: it is the next number in sequence and reads forwards from
# M87 without ambiguity, so it needs no compounding.
#
# M89 ships alone for the same reason. It is a RECORD-CORRECTNESS build and
# changes no trading decision: a stop-out was being recorded as `target`, and
# seven of the twenty-three refusal messages the rails can emit were classified
# as "not recognised" on the Blotter and in the daily report. The OMS gained an
# injectable clock, which defaults to the wall clock and is inert in live.
# M90 is the first build since 3 August that CHANGES A TRADING-DECISION INPUT,
# and it ships under a recorded freeze lift rather than despite the freeze. The
# aggregate risk cap now measures positions on the broker's mark instead of the
# price they were opened at.
#
# THE REPORTED FIGURE WILL JUMP, and that is the fix rather than a fault:
# 5.01% -> about 6.34% on the book as it stands. Nothing is forced to sell -
# QAT_DELEVER_SWEEP_ENABLED=false in the live config - and entries were already
# refused at 5.01%, so no trade that would have happened now will not.
#
# M104 is the first build of the IBKR/ASX path, and it ships TWELVE milestones
# at once because M94 was the last thing packaged - the repository ran ten
# milestones ahead of any build, which is the state this constant exists to
# make visible rather than to hide.
#
# What an operator will see that is new: broker=ibkr now RESOLVES rather than
# refusing (M101), so the application can run against an IB Gateway; ASX
# symbols reach the ASX listing rather than failing to resolve (M96);
# corporate-action detection reports UNAVAILABLE as a standing condition
# instead of a per-symbol query failure every sweep (M100).
#
# THE ALPACA PATH IS TOUCHED, and not only added to. M100 changed the
# corporate-action monitor and both screens, M101 put a BrokerConnection engine
# first in the startup order for EVERY broker, and M98 added two optional
# fields to RestingStopOrder. All are no-ops on Alpaca by construction and none
# has run a session there.
#
# NO TRADING-DECISION INPUT CHANGES on the US path. The IBKR order translation
# changed profoundly - protective stops transmit as STP rather than as MARKET
# orders (M95), which on IBKR was a stop that liquidated the position it was
# meant to protect - but none of that path has ever executed in production.
#
# M109 ships FIVE milestones, all of them observability, and every one of them
# was written because the first two live ASX sessions on 19-20 August produced
# a true statement that answered the wrong question.
#
# What an operator will see that is new: a session announces itself at startup
# even when it was BORN healthy rather than transitioning into it (M108) -
# without that line every tool anchored on "Trading session started" fell back
# to the previous run, and on 20 August session_check reported a finished
# session's start time, its 1,056 errors and its adopted Alpaca positions
# against a session that had begun ninety minutes later. The entry allow list
# now announces itself too (M109), naming how many watched symbols may be
# entered and how many will signal and be refused; on 20 August it silently
# discarded six correct pre-open signals and was found four minutes after the
# setups had expired. "Test Broker Connection" now actually tests the
# connection instead of returning a tick regardless (M105).
#
# The pre-flight gained a tradable-universe check (M106) and then had it
# widened (M109), because the first version only asserted that the watchlist
# and the allow list OVERLAP - which was true on 20 August, and useless. It
# now warns when the allow list excludes part of the watchlist and names what
# it is refusing.
#
# THE ALPACA PATH IS TOUCHED. M108 changes SessionController for every market,
# so a US session will now emit a started line it did not emit before. M109's
# allow-list banner fires only when QAT_ENTRY_ALLOW_LIST is set, which is a
# machinery-test setting and empty on the US path.
#
# NO TRADING-DECISION INPUT CHANGES on any path. Nothing here touches sizing,
# gating, risk limits or order translation. M109's pre-flight WARN does not
# block a launch - the pre-flight is a hand-run script and has never been a
# startup gate - and the two new startup lines are log output.
#
# M118 ships M110-M118. The label sat at M109 on master this whole time because
# M111's bump was made on the `deploy/m111` branch, to exclude an unmeasured
# M112, and never came back - so `invoke package` on master would have stamped
# an M118 tree "M109". That is the exact staleness M109 was raised to fix,
# recurring by a different route, and it is why this constant is read back off
# a RUNNING build rather than trusted from the packager.
#
# CHANGES A TRADING-DECISION INPUT, twice.
#
# M111: the ASX daily bar boundary was UTC midnight, so a vendor bar stamped
# `2026-08-20 00:00:00+10:00` floored to the 19th. Every seeded ASX bar carried
# the day BEFORE the one it traded on, and today's half-finished session was
# admitted as a COMPLETED bar - so the swing entry's "previous bar" contained
# today's prices. It now reads yesterday's completed close. The daily-loss
# baseline also keys on the exchange trading date, so it will not re-arm an hour
# into the session when AEDT starts on 5 October.
#
# M112: the regime engine's breadth feature has been constant-zero for the whole
# ASX period - `_aligned_breadth` required TOTAL coverage of the benchmark's
# dates and kept 0 of 7 symbols on live data. It now carries a close across a
# gap. MEASURED before shipping, on 301 seeded bars: label low_vol either way,
# exposure scalar 1.0 either way, NO SIZE CHANGE on that day's data. The
# probability distribution does move, so that is evidence and not a proof.
#
# What else an operator will see: the entry allow list announces itself at
# startup (M109); the pre-flight states its feed coverage instead of implying it
# checked everything, and a total feed failure now names the SOURCE rather than
# the symbols (M110, M118); six dead ASX tickers are gone; the AI Advisor is
# given the next results date and, if QAT_NEWS_SOURCE says so, company news that
# two independent outlets carried (M115-M117, off by default).
#
# M120 ships M119-M120, both found during the first live ASX session.
#
# M119 is an AVAILABILITY fix, not a decision-input one. The yfinance source
# ended its stream after five empty polls, and nothing restarts an ended stream
# - MarketDataFeed's ingest loop is `async for tick in stream_ticks`, so the
# task simply completes. Yahoo publishes ASX intraday about 20 minutes late, so
# all five 60s polls from the 10:00 bell landed inside the delay window: the
# feed died at 10:04:20 waiting for data that arrived at 10:22, and the account
# sat flat and blind on an open market. Nothing halted, because MARKET DATA DOWN
# is deliberately not a kill-switch trigger and per-symbol staleness skips
# symbols that have never ticked - so the halt the old design relied on could
# not fire, which the comment in that file claimed it would. The Alpaca source
# had already been fixed for exactly these reasons and the fix was never carried
# across; this ports it. Verified against the live vendor before writing: daily
# bars were fine throughout and ASX 1m had 1,445 rows over the prior four
# sessions. The vendor was never blocking us.
#
# CHANGES A TRADING-DECISION INPUT.
#
# M120: `trading_date` was built by M111 to answer "which session is this" and
# had exactly ONE caller. Three sites still derived a calendar date from a UTC
# instant, and one of them is a SIZING input - the earnings blackout half-sizes
# a trade within N trading days of a print, and `_first_future_date` decided
# which print was still upcoming against a UTC date. MEASURED: no change today
# and none until 5 October, because in AEST the ASX session runs 00:00-06:00
# UTC and the two dates agree; the earnings calendar warms at session start,
# which is after the rollover. From 5 October, AEDT puts the first hour of every
# session on the PREVIOUS UTC date, so a print that has already gone out reads
# as upcoming and the symbol stays in a blackout it has left. The same crossing
# M111's own note predicted, in the rails M111 did not reach. A guard test now
# fails on any new `now(UTC).date()` in `src`, because this bug survived a
# milestone and a half by never failing anything when reintroduced.
#
# Also M120: the unattended end-to-end safety test built its fixture from
# `datetime.now(UTC)`, so it dated itself into the future whenever the market's
# date lagged the UTC one and no order was placed. CI passed at 23:14 UTC on
# 20 August and the same commit failed at 00:30 UTC on the 21st - green or red
# by the hour of the push, on the one test covering the unattended first fill.
#
# M122 is NOT in the deployed build and is not scheduled to be. It ships with
# whatever goes out next; the M120 install running today does not have it.
#
# CHANGES A TRADING-DECISION INPUT, eventually rather than now.
#
# M122: `closed_trades.csv` had no market, no broker and no currency column, so
# it could not distinguish the Alpaca/US period from the ASX trial that appends
# to the same file. On 21 August it held two rows, both from the US period, and
# `EdgeEstimator` filtered on STRATEGY ALONE - so at swing's twentieth closed
# trade an Alpaca loss would have been a twentieth of the win rate that sets
# POSITION SIZE. With 94 symbols now enterable, twenty trades stopped being a
# distant number. Trades are now stamped with market and currency at close,
# `closed_trades(strategy, market=...)` can scope, `EdgeEstimator` pins to
# settings.market, and `compute_stats` logs at ERROR when a total spans two
# currencies rather than returning a plausible sum of USD and AUD.
#
# MEASURED: no change to any figure today. Swing has one closed trade against
# an edge_min_trades of 20, so the estimator returned the default edge before
# this change and returns it after.
#
# The two legacy rows are LABELLED, not deleted, by scripts/migrate_ledger_eras.py
# - dry-run by default, refuses to run while the app holds the file. One of them
# is MNST at 45.9975 against an entry of 91.1838 with no strategy and no stop:
# an unadjusted split recorded as a stop-out, which the script reports and
# deliberately does not rewrite. Whether that row is a loss or an artefact is a
# judgement, and a migration has no business making it.
#
# M130 ships M123-M130, all of it built on 21 August after the close.
#
# CHANGES A TRADING-DECISION INPUT, twice. M123 and M128; the rest do not.
#
# M123: order prices are rounded onto the exchange's own increments. Nothing
# computed ticks before, and on the US side nothing had to - the tick is a cent
# at every price a megacap trades at, so AlpacaAdapter's round(x, 2) and "on a
# valid increment" were the same thing by coincidence. The ASX step between
# $0.10 and $2.00 is half a cent and the swing stop comes off ATR, so a stop on
# MGR.AX at $1.91 lands at 1.8734 - a price the exchange does not have. IBKR
# answers error 110 and the order never reaches the market. BUYS ROUND DOWN,
# SELLS ROUND UP, which is conservative on cost and on protection at once:
# because a long's protective legs are transmitted as SELLs, rounding can only
# move a stop TOWARD the market. It may tighten protection by up to a tick and
# can never loosen it, and since size is computed from the unrounded stop the
# realised risk is at most a tick smaller than sized.
#
# M128: ticks carry the BAR's timestamp instead of their arrival time, and
# staleness is measured BEYOND the feed's 1,200s structural delay. Under
# ts=now the rail could not see price age at all - it measured feed silence and
# nothing else, which is why both full ASX sessions reported zero exclusions
# while every price in them was twenty minutes old. MEASURED: the rail fired
# 1,589 times on the US feed between 31 July and 18 August and has NEVER fired
# on ASX. Expect the first ASX exclusion after this build; it is the rail
# working. Stamping bar time WITHOUT the delay allowance would have excluded
# every symbol and traded nothing at all, silently, while reporting a healthy
# feed - which is why the two land together.
#
# The rest change no trading input. M124 puts a confirmation in front of the
# dashboard force-start, defaulting to NO so Escape, Enter and closing the
# window all decline. M125 retries a refused Gateway port for about a minute
# instead of shutting down, and the pre-flight now probes the PORT rather than
# the process - a Gateway that is running but not logged in refuses its API
# port, so the process being up proves nothing. M126 turns Yahoo news on and
# SHOWS the operator the stories handed to the model; the advisory layer
# reaches no part of the trading system. M127 gives the equity curve and the
# refusal log the same era boundary M122 gave the ledger, which is what stops a
# 9.9x broker migration reading as an 896% return. M130 watches the feed's real
# lag against the 1,200s claim and reports drift WITHOUT ever adjusting the
# threshold.
#
# What an operator will see that is new: a confirmation dialog on force-start;
# "gateway port" in the pre-flight naming which of the four it found; a sources
# line under the AI Advisor's conversation; and, on the first ASX session after
# this build, possibly the first staleness exclusion this system has ever
# produced on that market.
#
# M134 ships M133-M134. NO TRADING-DECISION INPUT CHANGES: one reported figure,
# one rename, one log line, and the build tooling.
#
# M133: exposure is the market value HELD, read from IBKR's
# `GrossPositionValue`, rather than `(equity - cash) / equity` - which treats
# anything that is neither a position nor spendable cash as though it were
# invested. On 21 August that printed "Avg exposure 0.2%" for an account
# holding NOTHING, the 0.2% being `AccruedCash` of 2,087.83 sitting in the gap.
# Samples with no recorded position value are SKIPPED rather than computed the
# old way, so exposure is unavailable for existing history rather than wrong
# about it.
#
# M134: three things that looked like they worked.
# * `invoke build` was `pre=[lint, test]` with a `pass` body - it ran the
#   checks, built NOTHING, and returned 0 while dist/ kept an eight-milestone-
#   old exe. It now packages, verifies the file exists, and prints what it
#   produced. `lint`, `test` and `format` shelled out to BARE tool names that
#   are not on PATH, which is why it died on "'ruff' is not recognized"; all
#   now run as `<this interpreter> -m <tool>`, which `package` and `manual`
#   already did and explained.
# * `average_daily_volume` is a deterministic random number seeded on the
#   ticker, and `QAT_WATCHLIST_MIN_AVG_VOLUME` screens on it. Renamed
#   `synthetic_average_daily_volume`; `resolve_watchlist` warns when it drops
#   anything; and the SCREENER, which displays this figure in its results
#   table, now says at the call site that it means nothing about liquidity.
#   Not deleted - removing it would silently widen the universe.
# * `migrate_ledger_eras.py` is superseded by `retire_alpaca_era.py` and now
#   says so in its first line.
#
# M135 is operator-facing work from running the app rather than reading it, plus
# one guard that was passing while blind. NO TRADING-DECISION INPUT CHANGES.
#
# What an operator will see: single-source news reaching the AI Advisor where
# nothing reached it before; what the model was given printed in the
# conversation instead of clipped to one line; the symbol named in front of
# every question; four permanently-blank fields gone from the Dashboard; and the
# backtest equity curve plotted against dates rather than a bar count.
#
# * NEWS. The two-source rule was surfacing nothing on the ASX names being
#   asked about - `data/news.py` had already recorded why: NHF's six items came
#   from ONE outlet, and the binding limit is Yahoo's .AX coverage rather than
#   the threshold. `QAT_NEWS_MIN_SOURCES` now carries it, default 1. What that
#   costs is stated at the setting: a single planted story can reach the model.
#   What still holds is everything that never depended on counting outlets.
# * The sources block moved into the conversation, which also gave each answer
#   its OWN sources - one label meant a second question overwrote the first
#   question's. Escaped on the way in: the conversation is rich text and a
#   headline is third-party text.
# * DASHBOARD. Short market value, both margin figures and Day trades (5d)
#   removed. `ib_adapter.balances` already said the IB layer maps none of them,
#   so all four rendered a dash every session; and two are meaningless even
#   filled, this system being long-only and the day-trade count belonging to a
#   US rule that does not reach an ASX account.
# * The equity curve is plotted on its own timestamps. M55 left a note saying
#   the index existed and was discarded at the render site. It was.
# * DESIGN SYSTEM. 28 hand-written stylesheet arguments, 11 of them a pixel
#   size that is ON the type scale. `theme.text` now takes an OPTIONAL colour,
#   which is why they existed - a heading wants a size and a weight and had
#   nothing to call - and `theme.panel()` owns the bordered card.
# * ⚠️ The colour guard was passing while blind. Python 3.12 (PEP 701) made
#   f-string text arrive as FSTRING_MIDDLE, not STRING, and the scan filtered
#   on STRING - so it read every f-string as empty, which is exactly where a
#   stylesheet is written. It hid `color: white` in `dashboard.py`. Any guard
#   in this codebase written before 3.12 could have narrowed the same way.
#
# M136 - one symbol, one recommendation. The AI Advisor now shows what the
# application's OWN RAILS say about a symbol, beside what the model says, and
# both advisory screens build their context through one builder. NO
# TRADING-DECISION INPUT CHANGES: this reads the rails, it alters none.
#
# * THE DEFECT THAT SHAPED IT. The Advisor passed `positions` as
#   {symbol: quantity} and nothing else, so asked whether to SELL a holding the
#   model saw a share count and no entry price, no P&L, no R multiple, no stop
#   and no hold state. It had nothing to form a sell or hold view from. Hence
#   the verdict BRANCHES on whether the symbol is held: entry rails and sell
#   rails share almost nothing, and `position_view.py` already computed the
#   held picture for the Dashboard.
# * Every rail is ASKED of its owner - StrategyEngine.is_eligible/eligible_mass,
#   AutonomyGate.evaluate (a pure decision function, probed with a one-share
#   order), market_calendar, and a new pure `OMS.entry_permitted` extracted from
#   `submit_order`. Nothing is reimplemented, because the rails live in four
#   subsystems and a second derivation drifts.
# * ⚠️ THE RISK ENGINE IS NEVER ASKED. `evaluate_order`, `evaluate_exit` and
#   `_reject` all write `risk_decisions.csv`; a hypothetical would file risk
#   decisions for trades nobody proposed. A test spies on all three and fails on
#   the CALL. Its first version spied on `evaluate_entry`, WHICH DOES NOT EXIST,
#   so `getattr(..., None)` skipped it silently and the entry side was unguarded
#   while the docstring claimed otherwise. Found in review.
# * The Workbench passed `regime_label="unknown"` and so formed a recommendation
#   against no regime at all, while the Advisor used the live one. Both now go
#   through `build_advisory_context`.
# * The Advisor fetched news TWICE per question - once for the sources block,
#   once inside the builder. `news_for` calls the vendor live every time, so the
#   two could disagree and the operator would be shown stories the model never
#   received. M126's defect inside one screen. One fetch now.
# * `to_prompt_text` told the model each story "was carried by two or more
#   independent outlets", which went false when QAT_NEWS_MIN_SOURCES shipped at
#   1. The screen was corrected when the setting landed and the prompt was not.
#
# ⚠️ NOT YET VISIBLE ON IBKR. The verdict declines to render when day P&L is
# unknown rather than fabricating 0.0 - a fabricated 0.0 can never trip the
# always-negative pause threshold, so it would report "permitted" on an invented
# fact. But NOTHING populates `AccountBalances.last_equity` on IBKR: it is an
# Alpaca field and `_ACCOUNT_TAGS` requests no previous close, so `day_pnl_pct`
# is None on the real broker always. Sourcing it is the operator's chosen next
# step and is blocked on a running Gateway.
#
# M137 - the log stopped, and nothing said so. Found live on Monday's open.
#
# The application's log froze at 5,242,781 bytes - 99 short of the 5 MiB cap -
# at 10:06:27, five minutes into the ASX session, and stayed frozen across a
# full restart while the app went on trading, evaluating fourteen sizing
# decisions and writing every one to risk_decisions.csv. session_check went on
# reporting a stale session without saying it was stale.
#
# TWO HALVES, NEITHER WRONG ALONE. `scripts/watch_session.py` held the log open
# for its whole run, and on Windows a plain open() does not grant
# delete-sharing - so `RotatingFileHandler.doRollover`'s os.rename failed with
# WinError 32. doRollover closes the stream BEFORE the rename it fails on, so
# `stream` was left None, and `emit`'s except clause handed the record to
# `handleError`, which says nothing anywhere an operator looks.
#
# The tool whose only purpose is to watch a session is what blinded it, and it
# displayed nothing while doing so.
#
# WHAT IT COST: a wrong diagnosis. A market-data feed that had recovered on its
# own at 10:21 looked hung, because the only evidence either way was a log that
# had stopped - and the app was restarted on that mistaken reading.
#
# * `ResilientRotatingFileHandler` reopens the stream and keeps appending when a
#   rotation fails, announcing the failure in the log itself, once per 60s
#   cooldown rather than once per record. **A log that grows past its cap is a
#   far smaller problem than a log that stops.**
# * `watch_session.py` polls - open, read, close - instead of holding a handle,
#   and resets its offset when the file shrinks under it.
#
# Verified by reproducing the failure: with the stock handler the same scenario
# writes 13 lines and silently loses 28; with this one all 40 arrive.
#
# M138 - the per-order cap becomes a SHARE OF CASH, a setting, and TRIMS
# instead of refusing. ⚠️ THIS CHANGES A TRADING-DECISION INPUT. Signals that were refused
# will now place smaller orders.
#
# `max_order_notional` was a bare default argument on `OMS.__init__` -
# 50_000.0, no comment, no setting, no manual entry, no measurement. Alone
# among the risk rails it carried none of its own reasoning, and it was the only
# one that was a fixed sum rather than a fraction, so it never grew with the
# account. It and the 15% single-name cap agreed at about $333k of equity and
# nowhere else.
#
# It is now `QAT_MAX_ORDER_PCT_OF_CASH`, default 10%, range 0 to 1. Against CASH
# rather than equity by operator decision: the paper account holds a round 1M
# AUD that says nothing about what a real market would absorb, and on a live
# account cash is the figure that actually constrains a purchase, with liquidity
# biting long before the balance does. A fraction travels from paper to live;
# a dollar figure tuned at 1M does not.
#
# 0 IS ALLOWED and means no new entries - a trim to zero cannot make one whole
# share, so buys are refused while exits stay exempt. That is a usable "stop
# opening positions, let the book run off" switch. An unknown cash balance
# REFUSES rather than skipping the cap, matching the fail-closed rule that
# test_cash_check_fails_closed_without_a_price already names.
#
# On the 24 August numbers: cash 1,001,865, cap 100,187, the sizer wanted
# 125,508, so TNE.AX would have gone in at 3,067 shares rather than being
# refused 48 times. The 15% single-name cap (150,609) still does not bind.
#
# It bound for the first time on 24 August. The half-Kelly sizer asked for
# ~12.5% of ~1.0M AUD - about $125k - and the flat $50k refused the first real
# ASX entry signal this system has ever produced, 48 times in a row, one a
# minute, for the whole morning window.
#
# * BUYS TRIM. A limit that refuses makes the trade disappear; a limit that
#   trims makes it the size the limit believes in. The concentration cap has
#   worked this way since M31c. Trimming can only reduce risk - the stop is
#   per-share and unchanged - and it is logged, because the audit trail keeps
#   the sizer's untrimmed figure and the two will differ for that order.
# * EXITS ARE EXEMPT, and this was the more dangerous half. The old code
#   REFUSED a sell above the cap, so a position larger than the cap could not
#   be closed by this application at all. A trimmed exit is no better: it leaves
#   a residual the operator believes is closed. The autonomy gate already draws
#   this line - risk-reducing orders are not gated on appetite limits.
#
# Two things the suite did not catch and reading did. The existing test
# `test_order_exceeding_max_notional_is_rejected` KEPT PASSING after the
# change, because its $1 cap cannot cover one share at any price, so it took
# the residual refusal path rather than the one its name described. And the
# refusal string it emitted is no longer produced anywhere, while the new one
# was absent from the taxonomy - which would have classified it as "not
# recognised" on the Blotter and in the daily report, the M89 defect exactly.
#
# M139 - AN ORDER REACHES THE BROKER ONCE. Found live, the hard way, on the
# first afternoon this system ever transmitted anything.
#
# At 14:04:51 on 24 August the autonomy gate opened and auto-signed two pending
# orders: TNE.AX 3,076 and DXS.AX 17,067. `AutonomousExecutor.retry_pending`
# then re-signed and re-transmitted BOTH every sixty seconds, four times each,
# until the session was stopped by hand. The broker held 68,268 DXS against an
# intended 17,067 - exactly 4x - and 8,587 TNE, ~$679k of exposure, with NO
# protective stops resting and no position record in the application at all.
#
# ROOT CAUSE: two individually correct decisions combining.
#   * M31a removed `order.status = "transmitted"` from BEFORE `place_order`,
#     because a raised call left an order falsely claiming to be live.
#   * `from_ib_trade` deliberately left IBKR's working states unmapped, on the
#     stated grounds that they "leave our own already-set transmitted status
#     alone" - true when written.
# `place_order` returns `from_ib_trade(...)` and sets no status itself. With the
# pre-set gone and the states unmapped, NOBODY set it: the order came back
# reading `pending_signoff`, which is exactly what `OMS.pending_orders` filters
# on. "Check whether the fix has a sibling", one more time.
#
# TWO INDEPENDENT DEFENCES, because a single one failing silently is what this
# was:
#   * the adapter maps PendingSubmit/PreSubmitted/Submitted/ApiPending/
#     PendingCancel and now assigns UNCONDITIONALLY with a "transmitted"
#     default - mirroring alpaca_adapter, the sibling that had it right;
#   * the OMS records every order id handed to a broker and refuses a second
#     transmission whatever the status field says.
#
# ⚠️ THE LESSON THAT OUTLIVES THE BUG: the per-order cap worked perfectly. It
# trimmed 3,468 shares to 3,076 exactly as designed, then was defeated by that
# same 3,076 going out four times. A PER-ORDER limit is not a PER-POSITION
# limit, and nothing currently caps the latter - the single-name concentration
# cap lives in the sizer, upstream of transmission, so it never saw the
# duplicates either.
#
# M140 - a trade cannot close before it opens. Closes item 27, the last of the
# three order-path defects 24 August produced. RECORD-CORRECTNESS ONLY: no
# trading decision changes, and no rail decides anything differently.
#
# Seven rows reached closed_trades.csv whose closed_at preceded their opened_at
# by an hour - -$167.90 nobody lost, attributed to `swing`, in the file the
# promotion gate reads and the sizer sizes from below 20 trades.
#
# `absorbed_fills.json` restored a watermark of 10:38 into a process that
# started at 15:18, so the first absorb pass replayed four and a half hours: the
# M139 duplicate buys, the operator's MANUAL remediation sells, and the app's own
# fills. All read as foreign, because `_is_foreign_unrecorded` tests
# `_broker_order_ids` and `_orders` - both in memory, both empty after a restart.
# ORDER IDENTITY DOES NOT SURVIVE A RESTART, and that is the deeper fact.
#
# THE GUARD IS AT THE MATCH, NOT THE WATERMARK, deliberately. The wide replay is
# what M50 exists for - a stop that fired while this was down arrives no other
# way - so narrowing the window would break a feature that was working. The
# discriminator is arithmetic: in M50's case the lot was opened in a PREVIOUS
# session and its opened_at precedes the exit; in the corruption the lot was
# opened by THIS session, after the exit matched to it.
#
# NARROWED BY AN EXISTING TEST, which is worth recording. The first version
# compared timestamps alone and broke three tests in
# test_live_exit_price_correction, which absorbs an exit against an ADOPTED lot.
# An adopted lot has no strategy and its opened_at is a placeholder stamped at
# adoption, so comparing a real exit against it proves nothing - and refusing
# would discard the legitimate case of a position partially closed while down.
# The guard now fires only on a lot this app opened itself (`strategy is not
# None`). That fixture also turned out to run TWO clocks, the OMS pinned to an
# epoch and the ledger on the wall clock, so its entry was stamped eight months
# after the exit closing it; the fixture was corrected, not the guard.
#
# Also: a restored watermark more than two hours old now WARNS. The replay was
# never the defect - the silence about its width was.
#
# M141 - orders resting at the broker that the book cannot justify. Closes
# item 23, the last of 24 August's order-path defects still without a rail.
#
# On 24 August an interrupted session left sixteen orphaned GTC bracket legs
# resting against a FLAT TNE.AX - up to 12,304 shares of automatic short risk
# that buying power would not have refused, and nothing was watching for it.
# Every existing order-side check asked "is what I believe still there";
# none asked "what is there that I do not believe in". `OMS.check_resting_
# orders()` is the second question: it scans `broker.open_orders()`, nets
# each one-cancels-all group, compares the net against the position, and
# logs every unjustified leg at ERROR with the prefix `RESTING ORDER
# ORPHAN:`.
#
# ARITHMETIC, NOT IDENTITY. Order identity does not survive a restart -
# `_broker_order_ids` and `_orders` are in-memory and empty afterwards
# (version.py:501, M140's finding) - so "did this app place it" answers no
# for every order that matters, including the 24 August orphans themselves,
# which were inherited across a restart. The only durable question is
# whether the BOOK justifies what is resting, not who placed it.
#
# OCA GROUPS NET, NEVER SUM. The live book holds 3,051 TNE.AX bracketed with
# a stop for 3,051 AND a target for 3,051 - 6,102 shares of resting sell
# against a 3,051 long. Only one leg can ever fire. A rule that summed would
# flag the only position this system has ever placed correctly, on its own
# working stop, which is the most damaging possible false positive.
#
# QUARANTINE, NOT `PositionAnomalyStore`. `RestingOrderAnomalyStore` has no
# `explains()` method, and a test asserts the absence. `PositionAnomalyStore.
# explains()` suppresses a kill-switch trip inside `check_reconciliation`, so
# quarantining a FLAT symbol through it (`broker_quantity=0.0`) would have
# granted that symbol immunity from the position-reconciliation halt at
# broker=0 - exactly the rail that caught the real 24 August mismatch. Item
# 23's fix would have partly disabled item 27's: the M31a shape again, two
# individually correct decisions combining into a defect.
#
# THE STATUS WIDENING IS SPLIT OUT, BY DECISION. The netting scan needs a
# working-status set wider than `ib_translate._IB_WORKING_STATUSES` -
# ApiPending and ApiUpdate are real ib_async working states that set is
# missing - so this ships its own, `resting_orders.WORKING_STATUSES`,
# asserted against ib_async's own ActiveStates by `tests/data/broker/
# test_working_statuses.py`. `_IB_WORKING_STATUSES` itself is UNCHANGED here:
# widening the shared one moves `_position_stops`, which is a sizing input,
# and that is not a change to make inside an orphan-detection build. It
# ships separately, and is measured before and after on a watched session.
#
# CANCELLING IS OFF BY DEFAULT AND FLAT-ONLY. `resting_order_cancel_enabled`
# defaults False. Even enabled, a HELD symbol carrying excess is only ever
# reported and quarantined - choosing which OCA leg dies on a position this
# app still holds is a judgement it must not make unattended, and getting it
# wrong strips the stop from a real long. Does NOT trip the kill switch: the
# risk is symbol-local, the switch halts new flow without cancelling
# anything (24 August's second lesson - stopping the process did not stop
# the fills), and spending a rail that needs a human reset on a detector
# with no field history is how the staleness rail ended up suppressed with a
# 69-hour value.
#
# M142 - ten fixes from the first full day of watching this system trade. The
# suite was green at 2,666 throughout and caught none of them; every one came
# from a live session or from the operator reading a screen and asking why it
# looked odd.
#
# THE SECTOR RAIL HAD NEVER RUN (item 44). `signal_bridge` called
# `submit_order` with four positional arguments, so `sector_by_symbol`
# defaulted to None, and nothing anywhere set `OrderCandidate.sector` -
# `governor.py` needs BOTH, so either alone leaves it dark. The cap was 30%;
# the book closed 60% Financials. `risk_decisions.csv` had recorded
# `held_in_sector_dollars: 0.0` on every decision since the first trade this
# system ever placed. Found because the operator looked at ten symbols and
# said "there seem to be a lot of banks".
#
# NO IBKR CALL COULD TIME OUT (item 34). The adapter had eight awaits on the
# client and zero timeouts. `reqExecutionsAsync`, reached first through
# `absorb_broker_fills`, resolves only on `execDetailsEnd`; a lost one hangs
# the caller for the life of the process. That wedged reconciliation for
# 6h50m across nine new positions and said NOTHING, because a hung await
# raises nothing. Every call is now bounded, and `poll()` carries its own
# deadline as a backstop for hangs nobody has found yet.
#
# POSITIONS CARRIED NO PRICE (item 45). `ib.positions()` has no mark;
# `ib.portfolio()` does, is already populated, and costs no extra request.
# Not cosmetic: without a price the minimum-hold LOSS ESCAPE cannot be
# evaluated, so every position was conservatively held and one falling hard
# enough to escape its hold could not be detected.
#
# THE KILL SWITCH DID NOT SURVIVE A RESTART (item 32). A halt meant to hold
# until a human decided held until the next launch, then cleared silently.
# Found the embarrassing way: the handoff said it was tripped, advice was
# given on that basis, and the operator pointed at the app reporting INACTIVE.
#
# Also: the drift guard on parked orders failed open on a `nan` (item 37);
# the console called a parked order "approved" (item 38); one sign-off path
# never journalled its refusal (item 43); the Risk Console gained the
# force-check button its docstring had promised, and a confirmation before
# HALTING but never before resetting (item 36); four surfaces stopped showing
# silent UTC (item 40); `ib_async` stopped rotating a 5 MiB log three times in
# three minutes and evicting the evidence (item 35); and the equity chart's
# axis now follows its data (item 39).
#
# THREE FINDINGS WERE WRONG and are corrected in the handoff rather than
# deleted: costs ARE applied to live trades, the governor DOES evaluate the
# parked set, and a staleness rail already exists. All three were written
# from reading code structure without checking the recorded data - while the
# audit trail held the answer, as it had for item 44. Reading a call site
# tells you what COULD happen; the audit trail tells you what DID.
MILESTONE = "M142"

_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BuildInfo:
    milestone: str
    commit: str
    built_at: str
    source: str

    @property
    def is_packaged(self) -> bool:
        return self.source == "packaged"

    def one_line(self) -> str:
        return f"{self.milestone} ({self.commit}, built {self.built_at}, {self.source})"


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


def _git(*args: str) -> str | None:
    """Repository metadata, or None anywhere that is not a checkout.

    Every failure mode lands here as None rather than as an exception: no git
    on PATH, not a repository, a git that hangs. A version display is not worth
    delaying startup for, let alone failing it.
    """
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell, no user input
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_describe() -> str:
    """A tag when one exists, the short SHA otherwise.

    There are no release tags today, so this is the short SHA in practice. It
    is written this way so that starting to tag releases upgrades the display
    on its own, rather than needing this file changed to notice.
    """
    described = _git("describe", "--tags", "--always", "--dirty")
    return described or _UNKNOWN


def build_info() -> BuildInfo:
    """The running build, from the packaged stamp or from git."""
    try:
        from qat import _build_stamp  # type: ignore[attr-defined]
    except ImportError:
        pass
    else:
        return BuildInfo(
            milestone=_build_stamp.MILESTONE,
            commit=_build_stamp.COMMIT,
            built_at=_build_stamp.BUILT_AT,
            source="packaged",
        )

    if _frozen():
        # Packaged, but the stamp is missing - built by something other than
        # `invoke package`. Say so rather than falling through to git, which
        # in a frozen app would report whatever checkout happens to be beside
        # the executable, or nothing at all.
        return BuildInfo(
            milestone=MILESTONE, commit=_UNKNOWN, built_at=_UNKNOWN, source="packaged, unstamped"
        )

    return BuildInfo(
        milestone=MILESTONE,
        commit=_git_describe(),
        built_at=format_display_date(datetime.now(UTC)),
        source="source checkout",
    )


def stamp_module_source(milestone: str, commit: str, built_at: str) -> str:
    """The generated module `invoke package` writes before freezing.

    A Python module rather than a data file, so PyInstaller's import analysis
    picks it up on its own - an `--add-data` file would need the spec and the
    task to agree forever, and would fail by being silently absent.
    """
    return (
        '"""Generated by `invoke package`. Not tracked; see qat/version.py."""\n\n'
        f'MILESTONE = "{milestone}"\n'
        f'COMMIT = "{commit}"\n'
        f'BUILT_AT = "{built_at}"\n'
    )
