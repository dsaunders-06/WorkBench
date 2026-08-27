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
#
# M143 - two found by looking at the M142 screens, minutes after deploying it.
#
# TODAY'S P/L RENDERED NOTHING WHILE THE RAILS HAD A FIGURE (item 46). Two
# day-P&L computations existed and the panel used the dead one.
# `EquityMonitor.day_pnl_pct()` measures against a persisted
# `day_start_equity`, works, and is what `AutonomyGate` gates on - the journal
# recorded 0.0031 the same session the panel showed "-".
# `AccountBalances.day_pnl` measures against `last_equity`, an Alpaca-era
# "previous close" that `from_ib_account_values` never sets. The panel now
# falls back to the day-start basis and NAMES which basis it used, because the
# two are different measures and showing one under the other's label would be
# a smaller version of the same failure.
#
# And the equity chart's constructor still claimed "Date" (item 39's other
# half). M142 relabelled inside `_render_result` only, so a chart that had not
# re-rendered since the deploy still said so - which is exactly what the
# operator saw and reported.
#
# AND THE AI SYMBOL VERDICT COULD NEVER RENDER ON IBKR (item 47). Asked
# whether the AI work was finished, it was not: `_build_verdict` requires
# `day_pnl_pct`, which derives from `last_equity` - an Alpaca-era "previous
# close" that `from_ib_account_values` never sets - so on this broker the
# value is ALWAYS None and the verdict has been silently absent since item 16
# shipped, across two live sessions. It now falls back to `EquityMonitor`'s
# figure, the one `AutonomyGate` already gates on.
#
# The FIRST version of that fix shipped the bug the guard exists to prevent,
# and an existing test caught it: `EquityMonitor.day_pnl_pct()` returns 0.0
# rather than None when it has no state - right for the gate, fatal for a
# verdict, because a fabricated 0.0 can never trip an always-negative
# threshold. The monitor's figure is now used only when it genuinely has a
# basis.
#
# M144 - company results, when the next ones are due, and every human-facing
# time in AEST. All three came from one operator question: "I'm not seeing any
# trading results information - this was available in the very first iteration".
#
# REPORTED RESULTS WERE FETCHED AND THROWN AWAY (item 48).
# `FundamentalSnapshot` carried only ratios - ROE, ROIC, EPS growth, yields -
# so the advisory context could reason about a P/E and never about "revenue up
# 8%, profit down 3%". `yfinance_fundamentals` already pulled the whole income
# statement and took only EBIT and the tax rate from it. Now carried raw WITH
# the period end-date, because a growth figure whose period is unknown cannot
# be checked. Live: ANZ revenue 22.31bn +9.6% with net income 5.89bn DOWN 9.9%.
#
# THE EARNINGS CALENDAR NEVER ANSWERED FOR ASX (item 49). `_fetch` asked
# `Ticker.calendar`, which returns `{'Earnings Date': []}` for every ASX symbol
# while `get_earnings_dates()` answers fine. So the rail abstained on a fact
# the vendor could supply, and every consumer correctly said "unknown".
# The ORIGINAL ShareTrader app used `get_earnings_dates()` - which is exactly
# why the operator remembered seeing this and this iteration did not have it.
#
# AND yfinance stamps ASX announcements in America/New_York. Taking `.date()`
# off that yields the NEW YORK day: 21:00 in New York is the NEXT day in
# Sydney. That date sets the earnings blackout the risk engine sizes against,
# so it was a sizing error waiting to happen, not a display one.
#
# Every human-facing time now renders in the market's zone and NAMES it - the
# Performance tab's closed-trade times were raw UTC with no zone at all.
#
# M145 - item 34's ROOT CAUSE, after two days of it being attributed to the
# wrong call. Found by reading the audit trail the app had already written,
# which is the habit items 41, 42 and 43 were written without.
#
# TWO CALLERS, ONE SHARED FUTURE KEY, IDENTICAL TIMERS.
# `reqAllOpenOrdersAsync` keys its future on the LITERAL string "openOrders",
# and `Wrapper.startReq` overwrites that key without resolving or cancelling
# what was there. `openOrderEnd` resolves whichever future survived, so of N
# concurrent readers exactly one is answered and the rest await a future
# nobody will ever complete. `reqExecutionsAsync` - the call this was blamed
# on - uses `client.getReqId()` and is unique per request, so it was never a
# candidate.
#
# `reconciliation_poll_seconds` and `protection_sweep_seconds` are BOTH 300.0
# and both engines start in the same second, so the two readers are
# phase-locked and collide on EVERY tick for the life of the process. That is
# what the old hypothesis could never explain: why the startup scan always
# succeeded. The orchestrator awaits each engine's `start()` in turn, so
# nothing overlaps at launch - and everything after it does.
#
# The lock is taken BEFORE `request()` is called, and that ordering is the fix:
# the method is a plain `def` that registers its future when CALLED, not when
# awaited, so a lock inside the timeout helper would serialise nothing.
#
# The existing timeout tests could not have caught it. Their fakes are
# `async def`, whose body runs at await rather than at call - a fake with the
# wrong call semantics tests the fake.
#
# AND check 5 of `session_check.ps1` now reports FRESHNESS. It read a
# reassuring green all day on 25 August while the rail was dead: the scan ran
# ONCE, at 09:09:52, and nothing told that apart from running every poll.
#
# THE BUILD STAMP RENDERS IN AEST (item 50). It read "built 25/08/2026 12:01
# UTC" among Settings fields that are session-local. The DATE is taken from the
# converted value too - a 14:30 UTC build is already the next day in Sydney.
#
# M146 - the regime HMM fits on a SCALE-NEUTRAL matrix (Phase 2.0, milestone A).
#
# GaussianHMM initialises its state means with cluster.KMeans on the RAW matrix
# and KMeans is Euclidean, so the widest-spread column decided where the states
# were first placed. Nothing standardised the features. Measured on the real
# 300-bar window the engine fits, with real breadth:
#
#     log_return 0.2%   realized_vol 1.2%   vix_level 85.0%
#     yield_curve_slope 8.6%   credit_spread 2.1%   breadth 3.0%
#     widest share   raw 85.0%  ->  standardised 16.7%
#
# So the regime that sets position size was being initialised almost entirely
# off one US series, by accident of scale rather than by design.
#
# THE LABEL DOES NOT MOVE, and that is the evidence this ships on. Both arms run
# through the real fusion path - RegimeFusion.compute, HysteresisGate,
# exposure_scalar_for - on the same matrix:
#
#     before (raw fit)      label=bull  scalar=1.00
#     after  (standardised) label=bull  scalar=1.00
#
# The raw posteriors differ ([1,0,0,0] vs [0,1,0,0]) and that difference means
# NOTHING - hmmlearn numbers states arbitrarily. The first version of the
# comparison printed only those posteriors and was rejected in review for
# exactly that: it invited being read as "the state changed".
#
# A COLLAPSED STATE NOW FAILS THE FIT BY NAME (DegenerateRegimeFitError), raised
# before self._model is assigned so a failed fit leaves the previous model
# untouched. Without it, hmmlearn leaves a never-visited state's transmat_ row
# at zero and raises "transmat_ rows must sum to 1" later, from predict(), far
# from the cause.
#
# AND THE TEST FIXTURES NOW CONTAIN REGIMES. _daily_bars was a single random
# walk and _macro_history was i.i.d. noise - there were never four regimes in
# that data, and a 4-state fit on it was fitting noise that the raw VIX scale
# happened to carve into four arbitrary clusters. That is why standardising
# broke two passing tests: they had been passing for the wrong reason.
#
# State characterisation deliberately still reads the RAW matrix, so
# StateSignature.mean_return keeps meaning a return rather than a z-score.
#
# M147 - the absorb path records the WHOLE exit, at the RIGHT price, in ONE row.
#
# On 26 August a LOV.AX take-profit filled 3,217 shares in 183 executions. The
# app absorbed 374 and tripped the kill switch on tracked=2843 broker=0. The
# absorbed total equalled the LARGEST SINGLE EXECUTION, which is the signature.
#
# BrokerFill.quantity and BrokerFill.price are BOTH the order's cumulative
# figures - _unabsorbed_part's own docstring names them as Alpaca's filled_qty
# and filled_avg_price, and its delta arithmetic is cumulative-average
# arithmetic. from_ib_fill was supplying execution.shares and execution.price,
# which are PER-EXECUTION, because IBKR returns one Fill per execution where
# Alpaca returns one order object per order. Every layer was individually
# correct and they disagreed about what the numbers MEANT.
#
# I fixed the quantity and missed the sibling. The review caught it, and the
# reason it was invisible is worth keeping: every fixture used a CONSTANT
# price, exactly as single-execution fixtures had hidden the quantity bug.
# A wrong price does not lose shares - it silently misstates realised P&L in
# the file the promotion gate reads.
#
# Three parts: cumQty so no execution is lost; avgPrice so P&L survives an
# order filling across a price range; and a per-order collapse within a pass,
# so one exit is ONE closed-trade row rather than up to 183. The last is not
# cosmetic - the gate counts rows toward 20 and 30, so an exit that books
# itself 183 times clears the gate on its own.
#
# Alpaca is unaffected: one order object per order means the collapse finds one
# entry per key.
#
# Verified against the REAL 183 executions, not a fixture: collapse to 1 fill
# event, 2,843 recovered, ledger 3,217 of 3,217. The price tests were confirmed
# to fail pre-fix at exactly the predicted blended averages, 30.0 against 28.75
# and 33.29 against 30.0.
#
# M148 - the app stops counting its own entries twice, and the console button
# stops lying about the halt.
#
# ITEM 56. On 26 August, twenty seconds after the kill switch was reset, two
# entries went out (WOW.AX 1098, SEK.AX 2978), each transmitted exactly once and
# correctly bracketed. 107 seconds later the app absorbed both as foreign and
# the book doubled - tracked=2196/5956 against broker=1098/2978 - and the switch
# tripped again.
#
# The cause is documented at the line that causes it. IB.placeOrder returns
# before TWS acknowledges, so permId is 0, and from_ib_trade correctly declines
# to write a junk id and leaves the app's own UUID. Nothing ever revisited it,
# so _broker_order_ids held a UUID while the execution arrived keyed on the
# permId. It is not a race: EVERY "Order signed off and transmitted" line in the
# whole log history, back to 1 August and across both brokers, carries a UUID.
#
# ⚠️ AND IT HAD BEEN FIRING SINCE AT LEAST 25 AUGUST, INVISIBLY. Fourteen
# absorbs of that day's own nine entries at 17:56:43, with ZERO reconciliation
# mismatches logged, because the poll was wedged - 3 scans that day against 78
# on the 26th. Item 34's fix did not cause this; it made a months-old defect
# visible. A rail whose failure mode is silence is worse than no rail.
#
# Two layers, because one is not enough. place_order now waits, briefly and
# boundedly, for the permId TWS is about to send - applied to ALL THREE
# placement paths, plain, _place_bracket and _place_oca, because the orders that
# caused this were brackets. And when the wait loses to a slow acknowledgement,
# _adopt_from_broker publishes BrokerOrderIdResolvedEvent and the OMS registers
# it, following the direction the adapter already uses for KillSwitchEvent.
#
# A permId that never arrives still keeps the app's own id - writing 0 would
# collide every unacknowledged order - but now says so at WARNING. Silence is
# what let this run since August.
#
# ⚠️ THE FIRST REGRESSION GUARD WAS WRITTEN AT THE WRONG LAYER, twice defended,
# and replaced. It built its OMS over MockBroker and never constructed an
# IBAdapter, so no path from it reached either fix; two implementers traced that
# independently rather than forcing it green. The guard now drives the OMS
# through a real IBAdapter over a fake TWS whose permId arrives late, and was
# FALSIFIED: with ibkr_permid_wait_seconds=0 it reproduces the 26 August
# double-count exactly.
#
# ITEM 57. The Risk Console's kill-switch button refreshed only at construction
# and after its own click, so a trip from reconciliation left it stale. The
# handler reads the TRUE state, not the label, and resets with no confirmation -
# so a button reading "click to halt trading" would have RESUMED order flow. The
# operator saw the banner disagree and declined to click. The label is now
# derived from the 2s timer that already runs, because a derived label cannot go
# stale where another listener could be missed - which is exactly how the
# outbound half of this same bug was fixed and the inbound half was not.
# M149 - both advisory screens see the same account, and the macro exposure
# proposal is anchored to a scale.
#
# ITEM 61. The operator ran a backtest and walk-forward on SUN.AX and read an AI
# note opening "Given no current positions and lacking portfolio risk metrics"
# while the account held 3,192 SUN.AX. The Workbench passed NONE of positions,
# risk_metrics, verdict or position to build_advisory_context; each defaults to
# an empty dict, so nothing errored and the model was simply told the account
# was flat.
#
# It is the SIBLING of a fix already made in that very call. The comment three
# lines above the gap reads: "The defect this closes: it passed 'unknown' and
# formed a recommendation against no regime at all, while the Advisor formed one
# against the live regime for the same company." The regime half was found in
# M126; the account half was never checked.
#
# Fixed by removing the opportunity rather than by adding four arguments. The
# gathering was PRIVATE to the Advisor, which is exactly why the Workbench could
# not use it - so _build_verdict, _risk_metrics, _position_dict,
# _corporate_action_notes and _bars_for all move to advisory_account.py behind
# one gather() returning AccountFacts. Neither screen assembles a subset any
# more because neither assembles anything.
#
# ⚠️ THE MOVE WAS VERIFIED BY AST, NOT BY READING IT - and the first copy was
# WRONG. _corporate_action_notes was rewritten from memory instead of copied,
# changing the branch condition, the else text, and dropping the sentence "New
# entries in this symbol are refused." The existing rendering test caught all
# three, which is why every moved function was then compared as a normalised
# syntax tree rather than by eye.
#
# An unplanned gain: the Workbench's own pending_action read feeds its DISPLAY,
# so until now its PROMPT carried no corporate action at all. Both screens do.
#
# The new guard reads the two CALL SITES from source with ast. The existing test
# compares what the BUILDER fetches, and its sibling's docstring already said
# supplied fields default to empty and prove nothing - so the suite knew and
# checked nothing. A behavioural test would pass here too: a stub runtime hands
# both call sites the same empty account.
#
# ITEM 62. The Regime Monitor showed "Exposure hint 1.00" one line above
# "Proposed exposure scalar: 0.40" on a Risk-On day. The model had never seen
# the 1.00: exposure_hint is a property, the screen renders it, and to_dict() -
# the only part of the signal reaching the prompt - did not carry it. The prompt
# named no scale either, and the schema constrains the field to nothing tighter
# than ge=0.0, le=1.0.
#
# 0.40 is not a value that read can produce. MACRO_REGIME_EXPOSURE_HINT runs
# 1.0/0.85/0.6/0.3; 0.40 exists only in _EXPOSURE_SCALARS, where it means
# high_vol - a table owned by the component that is deliberately the sole writer
# of RiskEngine.regime_scalar. That table is deliberately NOT named in the
# prompt: showing a second scale invites exactly this crossover.
#
# ⚠️ This does NOT establish the 0.40 was wrong. A model can argue for
# defensiveness at bull=0.47. What is established is that the proposal was
# uninformed and unconstrained. Whether an anchored prompt yields a different
# number is the read-back check and has NOT been run.
#
# NOT item 61 twice: get_macro_assessment passes positions={} on purpose, for
# LLM routing, and says so. Two empty dicts in two screens, one a defect and one
# correct - which is why "the context looks thin" is not by itself a finding.
# M150 - the ledger header catches up with its schema, and a transmitted order
# counts as committed exposure.
#
# ITEM 63. _record wrote a header only when the file was NEW, then appended
# under the current _FIELDS forever, so every field added after creation was
# WRITTEN into rows and never NAMED. Live: closed_trades.csv header 30 over rows
# of 32 and 31; equity_curve.csv header 4 over rows of 5 and 4.
#
# The cost was EdgeEstimator, which filters closed_trades on a strict
# trade.market == market. Every restored row carried market=None, so it matched
# nothing at 6 trades and would have matched nothing at 200 - the sizer stuck on
# invented constants permanently while reporting "default" for a reason
# unrelated to sample size.
#
# repair_csv_header reads rows POSITIONALLY, never through DictReader: under a
# stale header the surplus lands in the restkey and a DictWriter-driven rewrite
# DROPS it, turning mislabelling into data loss. Only the header line changes.
# Atomic via os.replace. A correct header is left untouched. Safe only because
# _FIELDS has only ever grown by appending, so a short row is a prefix - a row
# WIDER than the schema raises rather than remapping.
#
# ⚠️ equity_curve.csv was CHECKED rather than assumed clean and had the same
# defect: M133's position_value written on every sample, readable on none.
#
# ⚠️ The first dry run went through the Bash tool and was worthless - a frozen
# July snapshot of %LOCALAPPDATA%, served silently, reporting 301 rows for a
# 2,894-row file. The PowerShell re-run is where the numbers came from, and it
# revealed the MIXED row widths the stale read had hidden.
#
# ITEM 58. pending_orders matched only "pending_signoff". In auto mode sign-off
# takes milliseconds, so between sign-off and the broker reporting the position
# an order was in NEITHER held NOR pending. On 26 August WOW.AX signed at
# 15:15:24.870 and SEK.AX was sized 173ms later, both against a book of NINE;
# the book reached ELEVEN against a cap of 10. governor.py:304 refuses at >=, so
# returning to ten was still AT the cap - which cost 27 August 1,036 refusals.
#
# ⚠️ THE FIRST FIX BROKE A SAFETY RAIL AND tests/safety CAUGHT IT. Widening
# pending_orders also widened the protective-stop duplicate guard that reads it,
# and a signed-off protective stop is transmitted and RESTING - so it became
# permanently "already pending" and a position whose stop was cancelled could
# never re-arm. Two accessors now, and the docstrings say they must not merge:
# awaiting_signoff() asks whether a decision was made, pending_orders() asks what
# exposure is committed.
# M151 - the known blind window stops drowning the log.
#
# ITEM 54. Measured on the 27 August log rather than estimated: 685 of the 710
# lines in the blind window (10:00:05-10:20:32) were the per-symbol "possibly
# delisted" storm. 96%. They buried the RHC.AX BROKER-SIDE FILL under about
# three hundred of them - the one line of the day needing action within hours,
# because IBKR execution retention is same-day only.
#
# BlindWindowFilter drops that ONE message and only while the feed says it is
# blind. Eleven lines survive the window and they are the ones that matter: the
# aggregate "95 Failed downloads", "Retrying with backoff", MARKET DATA DOWN,
# and the recovery.
#
# ⚠️ Matched on the TEXT, never the logger. Suppressing yfinance wholesale would
# have hidden the real HTTP Error 401: Invalid Crumb at 10:26:52 - inside the
# very window where the feed is already struggling. And outside the window the
# same message passes through untouched, because there it is a genuinely
# delisted symbol: COL.AX and GQG.AX logged exactly that on 26 August with a
# healthy feed.
#
# NOISY_LIBRARY_LOGGERS could not do this: it raises a logger to WARNING and
# yfinance logs these at ERROR.
#
# Blind is set from the FIRST empty poll, not at the failure threshold - the
# storm starts at poll one and four polls of 95 is most of it already spent by
# the time the threshold is crossed. What is dropped is COUNTED and printed
# beside the recovery line that explains it.
# M152 - the rail that declares a quarantine now lifts it.
#
# ITEM 59. clear() had ONE caller in the codebase - an operator button - and
# _reconcile_resting_orders declared inside `for divergence in divergences:`, so
# a clean scan cleared nothing. Two quarantines outlived their cause by 26 hours
# and a restart on 27 August and would have silently blocked SEK.AX and WOW.AX
# from re-entry.
#
# Auto-clear after CLEAN_SCANS_BEFORE_CLEAR = 3 consecutive clean scans, with
# the operator button kept so a release need not wait fifteen minutes.
#
# Defensible here specifically because it is not "the symptom went away": it is
# the SAME rail, over the SAME input, running the SAME derivation and reporting
# the negation - a stronger warrant than a human clicking without re-deriving
# anything, which until now was the only way.
#
# Hysteresis because a divergence can flap; declare() resets the run so the
# counter is of CONSECUTIVE scans. Scoped to symbols the scan could actually
# SEE - counting an unscanned symbol as clean would lift on absence of evidence,
# the shape of items 34 and 37.
#
# ⚠️ THE FALSIFICATION FOUND A HOLE IN THE TESTS. Six store-level tests stayed
# GREEN when saw_clean_scan was deleted from the reconciler, because nothing
# drove the reconciler - item 56's first regression guard again, a guard at a
# layer no path from the defect reaches. The wiring test added afterwards DOES
# go red when the call is removed.
#
# Also carries item 64's pin (tests only, no runtime change): the open items
# now assert their own defect is still present, so a fix cannot outlive its
# heading. Twelve did in two days.
MILESTONE = "M152"

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
