# ASX auctions against session logic — design

**Stage 3 of `docs/superpowers/plans/2026-08-19-ibkr-move.md`**, the last of its
four sub-items. Tick sizes shipped as M123. The minimum marketable parcel and
T+2 were deliberately deferred by the operator on 21 August as live-only
concerns with no bite in a paper account; that reasoning is recorded in
"Deliberately not in scope" below rather than lost.

**Measured, not recalled:** `docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md`,
produced by `scripts/asx_session_probe.py` against the live paper Gateway on
21 August 2026. Every constant in this design traces to that file or is marked
as a judgement.

---

## The problem

`market_calendar.session_for` models a trading day as one continuous window
with proportional phases inside it. The ASX is not shaped that way: it opens
through a staggered single-price auction and closes with a separate one after
continuous trading ends. The application therefore believes continuous trading
is available at moments when the exchange is running an auction.

Where that reaches behaviour today: `autonomy/gate.py` returns `allowed` for
every sell before it consults the session phase, so a market exit transmitted
at 10:02 is transmitted into an auction. The gate already refuses this exact
thing in the closed-market case, and says why —

> *"A market sell transmitted into a closed market is an unpriced fill at the
> open, and stays blocked."*

— so the reasoning is present and correct. What is wrong is the calendar
underneath it, which reports 10:00 as continuous trading.

## What the measurement settled

Fourteen contracts spanning A2M to XRO, one per first letter across the
alphabet, because the ASX staggers its open alphabetically and a clustered
sample could not see the thing being measured.

1. **IBKR does not report a staggered open.** All fourteen returned identical
   hours. A per-symbol group model cannot be derived from broker data, so this
   design does not attempt one. **The fork was closed by evidence.**
2. **The closing auction is derivable.** `tradingHours` runs to 16:11 while
   `liquidHours` stops at 16:00. The eleven-minute delta is the pre-CSPA and
   closing auction as the exchange states them.
3. **The opening auction is invisible to IBKR.** Both strings start at 0959;
   the delta at the open is zero. Any opening-auction window is a judgement,
   and is marked as one at its definition.
4. **The app and the broker disagree about the open.** `_REGULAR_HOURS["ASX"]`
   says 10:00; IBKR says 09:59. See "The accepted divergence".

## Goal

Make the session model tell the truth about ASX auctions, and make the
hand-maintained calendar constants unable to drift silently away from what the
exchange says.

**Not** execution protection. Blocking a market sell out of an auction defends
against an unpredictable single-price fill, which IBKR paper does not
reproduce. In a paper account the value is in the two things that do carry:
the divergence check, which works identically in both environments, and the
fidelity of the record — paper is where the promotion gate's evidence is
produced, so a trade booked in a window that could not have filled
continuously is a trade the evidence base should not contain.

---

## Component 1 — the session model

`TradingState = Literal["pre_open", "opening_auction", "continuous", "closing_auction", "closed"]`

`MarketSession` gains a required `trading_state: TradingState`. It is
constructed in exactly four places, all inside `market_calendar.py`, so the
field is required rather than defaulted — a default here would be wrong
whenever it was omitted, which is the trap this file already fell into with
`ts=now`.

**`is_open` keeps its present meaning exactly: continuous trading is
available.** Every existing caller assumes that, and redefining it would
change the autonomy gate, the feed and the stand-down at once.

| Window (exchange local) | `is_open` | `trading_state` |
|---|---|---|
| before open | False | `pre_open` |
| `[open, open+10m)` | True | `opening_auction` |
| `[open+10m, close]` | True | `continuous` |
| `(close, close+11m]` | False | `closing_auction` |
| after close+11m | False | `closed` |

**Boundaries are half-open at the start and inclusive at the close**, which is
not a detail to leave to the implementer. 10:10:00 exactly is `continuous`, not
`opening_auction`. 16:00:00 exactly is `continuous` and `is_open` is True,
preserving the existing `local > closes_at` comparison rather than quietly
shortening the session by a second. 16:11:00 exactly is still
`closing_auction`.

Two per-market tables, both keyed on `Market` so a third market is added
deliberately rather than inherited:

```python
_OPENING_AUCTION_MINUTES: dict[Market, int] = {"US": 0, "ASX": 10}
_AUCTION_TAIL_MINUTES: dict[Market, int] = {"US": 0, "ASX": 11}
```

**US is zero on both, so US behaviour is unchanged.** `pre_open`,
`continuous` and `closed` are the only states a US session can reach, and the
499-session replay harness and the US trial record stay comparable.

`closes_at` stays the continuous close and **the phase table is not touched.**
The phase fractions describe intraday *volume* patterns within continuous
trading; folding an eleven-minute auction into the denominator would move
every boundary in the day — Morning Trend would end at 12:00.4 rather than
11:58.8 — for a mechanism those patterns do not describe. The auction is
modelled beside the phase table, not inside it.

**Unverified:** on an early-close day the tail is assumed to be the same
eleven minutes after the early close. No half-day fell inside the probe's
six-day window. The preflight check below is what will surface this when one
occurs, rather than it being assumed correct forever.

## Component 2 — the gate

In `autonomy/gate.py`, immediately after the existing `if not session.is_open`
block, before the unconditional sell allowance:

```python
if session.trading_state == "opening_auction":
    return block("the opening auction is running - a market order placed into a "
                 "single-price auction fills at the auction price, not a quoted one")
```

Placed after the `is_protective_stop` early return, which already sits ahead of
every other rule, so **resting protective orders are unaffected**. This matters
more than the block itself: a GTC stop already lives at the broker and
participates in the auction whether or not the app will transmit anything, so
what is refused is a discretionary market exit — a signal or time stop firing
at 10:05 waits until 10:10 — while actual downside protection is untouched.

Buys need no change: the opening auction window sits strictly inside Opening
Volatility, which already blocks entries until 10:28.8.

At the close nothing changes behaviourally — `is_open` is already False from
16:00 — but `closed_reason` stops saying "after close" during an auction and
names the auction instead.

## Component 3 — the parser

`qat/data/broker/ib_hours.py`, at the vendor boundary rather than in the domain,
so `market_calendar` stays dependency-free for the backtester.

```python
def parse_ib_hours(text: str, tz: ZoneInfo) -> dict[date, tuple[tuple[datetime, datetime], ...]]
```

Handles the `YYYYMMDD:HHMM-YYYYMMDD:HHMM` form, `YYYYMMDD:CLOSED`, multiple
semicolon-separated segments, and a day carrying more than one window.
Timezone-aware output, because a naive datetime here would reproduce M128's
shape one boundary further out.

Fixtures are the literal strings in the raw report, so they are measured rather
than invented.

## Component 4 — the preflight check

`preflight.contract_checks` already calls `reqContractDetailsAsync` for every
symbol and discards everything but whether it resolved. It captures the first
resolved `ContractDetails` and hands it to a **pure** comparison function, so
the check costs no extra round trip and is testable without a client:

```python
def compare_session_hours(details, market: Market, day: date) -> list[Check]
```

Four comparisons, each reporting the actual strings on disagreement:

| Compared | Against | Why it matters |
|---|---|---|
| `liquidHours` window | `regular_hours(market)` | the continuous session the phases divide |
| `tradingHours` minus `liquidHours` | `_AUCTION_TAIL_MINUTES` | the only measured auction constant |
| `timeZoneId` | `MARKET_TIMEZONES` | IBKR says `Australia/NSW`, the app says `Australia/Sydney` — same zone, different label |
| `CLOSED` days | `is_trading_day` | validates the hand-maintained ASX holiday table against the exchange |

The last is likely the most valuable: `asx_holidays()`, `_EARLY_CLOSE_TIMES`
and `EXTRA_CLOSURES` are all hand-maintained, and this is the first thing that
would contradict them out of the exchange's own mouth.

**Statuses, so this is not left to judgement at implementation time.** All four
disagreements report `WARN`, never `FAIL`. Preflight `FAIL` is reserved for
things that stop a session being run, and none of these do: the app can trade a
session perfectly well while disagreeing with IBKR about a label or a minute.
Agreement emits **one** `OK` line naming what matched, not four — four green
lines for one round trip is noise in an instrument read at the open.

**A missing or unparseable hours string is `WARN`, and this is a deliberate
departure from the rule in this module's docstring** — *"a check that could not
be performed is not a check that passed"* — under which `UNKNOWN` blocks READY
exactly as `FAIL` does. The departure is justified by what this check's subject
is. Every other check in `preflight` asks whether something the session depends
on is true; if it cannot ask, the session should not start. This one asks
whether a hand-maintained constant still agrees with the broker. The calendar
is authoritative at runtime either way, so nothing about the session degrades
when the comparison cannot be made. `UNKNOWN` here would mean a Gateway that
returned an odd hours string could block trading over a disagreement that is
cosmetic by construction.

The reasoning is recorded at the call site, because a departure from a
module-level invariant that is not written down next to it reads as an
oversight to the next person and gets "fixed".

## The accepted divergence

The measured 09:59-against-10:00 difference would otherwise make this check
warn on every run, and a check that always warns is a check people stop
reading. It is recorded as a single accepted entry — market, boundary, both
values, the date measured, and the probe cited — and the check stays silent on
it while speaking on everything else.

**An allowlist of exactly one, not a tolerance band.** A band would swallow the
next disagreement too.

It lives beside `compare_session_hours` in `preflight.py`, not in
`market_calendar`, because it is a fact about *this broker's reporting* rather
than about the exchange, and the domain module must not acquire opinions about
vendors:

```python
# (market, boundary) -> (app value, IBKR value, when measured, why accepted)
_ACCEPTED_HOURS_DIVERGENCES: dict[tuple[Market, str], tuple[time, time, str, str]] = {
    ("ASX", "open"): (
        time(10, 0), time(9, 59), "2026-08-21",
        "IBKR reports 0959 for every ASX contract probed; 10:00 is when ASX "
        "continuous trading starts. Reads as broker-side rounding. See "
        "docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md",
    ),
}
```

Any entry here is a claim that something measured was looked at and accepted,
so each carries the date it was measured and the reason — an undated exception
is indistinguishable from one nobody has re-examined.

`_REGULAR_HOURS["ASX"]` is deliberately **not** changed to 09:59: 10:00 is when
ASX continuous trading starts, and 09:59 reads as broker-side rounding. That is
a judgement, recorded as one at the constant, and the check makes it visible
rather than burying it.

## Testing

* **Parser** — fixtures lifted verbatim from the raw report: a normal week, the
  weekend `CLOSED` entries, and a malformed string returning empty rather than
  raising, since a probe-shaped failure must not take down preflight.
* **Calendar** — one test per state boundary at the exchange's local time,
  including both sides of each edge; a test that every US session reaches only
  `pre_open`, `continuous` or `closed`; and a test that the phase boundaries are
  **unchanged** by this work, which is the regression that would otherwise be
  invisible.
* **Gate** — a market sell at 10:05 is refused and names the auction; the same
  sell at 10:15 is allowed; a protective stop at 10:05 is allowed.
* **Preflight** — `compare_session_hours` against a stubbed `ContractDetails`:
  agreement is silent, each of the four disagreements reports, and the accepted
  divergence stays silent.

Every test that builds an OMS passes its own `data_dir`, per the standing
constraint.

## Deliberately not in scope

* **The staggered open per symbol.** Not derivable from IBKR, and the ten-minute
  blanket is deliberately conservative rather than precise.
* **The $500 minimum marketable parcel and T+2.** Operator decision, 21 August:
  both are live-only concerns with no bite in a paper account. One residual is
  recorded for whoever picks it up — if IBKR paper fills a sub-$500 order that
  the live exchange would refuse, the paper record is optimistic by exactly the
  trades that could not have happened.
* **Deriving the whole calendar from the broker.** Considered and rejected for
  now: it would put a broker dependency inside a domain module the replay
  harness depends on. The check is the cheaper half of the same benefit, and if
  it fires often the case for deriving gets made by evidence.
* **Changing `_REGULAR_HOURS` to match IBKR's 09:59.** See above.
* **Anything touching order routing.** Every order is a market order (M44); this
  design refuses one in a window rather than changing what is sent.
