# ASX Auctions Against Session Logic — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `MarketSession` distinguish an auction from continuous trading, refuse discretionary market orders into the ASX opening auction, and make the hand-maintained calendar constants unable to drift silently away from what IBKR reports.

**Architecture:** `market_calendar` gains a `trading_state` field alongside the existing `is_open`, driven by two per-market minute tables that are zero for US so US behaviour is bit-identical. A pure IBKR hours parser lives at the vendor boundary in `qat/data/broker/ib_hours.py`, keeping the domain module dependency-free for the replay harness. `preflight` compares the two and reports disagreements as WARN.

**Spec:** `docs/superpowers/specs/2026-08-21-asx-auctions-design.md`. **Read it first.** Its "Deliberately not in scope" section is binding.

**Measurement this rests on:** `docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md`, produced by `scripts/asx_session_probe.py` on 21 August 2026. Do not invent hours constants; every one traces there.

**Tech Stack:** Python 3.12, pytest, `ib_async`, ruff, black, mypy, bandit.

## Global Constraints

- **PowerShell for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal`**, including Python that only reads it and anything that builds `Settings()`. The Bash sandbox serves a frozen snapshot and does NOT error.
- **DO NOT PUSH.** GitHub Actions minutes are exhausted until September. The local suite is the only gate: run it in full and read the actual summary line, never a piped tail.
- **Lint with ruff, format with BLACK**, through the venv interpreter: `.venv\Scripts\python.exe -m ruff check .`, `-m black --check .`, `-m mypy src`, `-m bandit -q -r src`.
- **US behaviour must not change.** Both new minute tables are `0` for `"US"`. The 499-session replay harness and the US trial record stay comparable, and Task 2 has a test that enforces it.
- **The phase table is not touched.** `SESSION_PHASES`, `AUTONOMOUS_ELIGIBLE_PHASES` and `closes_at` keep their current values. Task 2 has a test that enforces it.
- **Every test that builds an OMS passes its own `data_dir`** — `conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store persists there.
- Run the full suite with `.venv\Scripts\python.exe -m pytest -q` and read the summary line. Current baseline: **2517 passed, 25 skipped**.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/data/broker/ib_hours.py` | **Create.** Parse IBKR's `tradingHours`/`liquidHours` strings into timezone-aware windows. Pure, no ib_async import, no I/O. |
| `tests/data/broker/test_ib_hours.py` | **Create.** Parser tests, fixtures lifted verbatim from the raw report. |
| `src/qat/domain/market_calendar.py` | **Modify.** Add `TradingState`, the two minute tables, the `trading_state` field, and its computation in `session_for`. |
| `tests/domain/test_market_calendar.py` | **Modify.** State boundary tests, the US-unchanged test, the phases-unchanged test. |
| `src/qat/domain/autonomy/gate.py` | **Modify.** One refusal for `opening_auction`. |
| `tests/safety/test_autonomy_gate.py` | **Modify.** Three gate tests. |
| `src/qat/preflight.py` | **Modify.** `compare_session_hours`, the accepted-divergence table, and capturing details in `contract_checks`. |
| `tests/test_preflight.py` | **Modify.** Comparison tests against a stub `ContractDetails`. |

Task order is bottom-up: the parser has no dependencies, the calendar depends on nothing new, the gate depends on the calendar, and preflight depends on both the parser and the calendar.

---

### Task 1: The IBKR hours parser

**Files:**
- Create: `src/qat/data/broker/ib_hours.py`
- Test: `tests/data/broker/test_ib_hours.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_ib_hours(text: str, tz: ZoneInfo) -> dict[date, tuple[tuple[datetime, datetime], ...]]`. Keys are exchange-local dates. Values are tuples of `(start, end)` timezone-aware datetimes, empty tuple for a `CLOSED` day. Unparseable input returns `{}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/data/broker/test_ib_hours.py`:

```python
"""IBKR trading-hours parsing.

Every fixture here is a string IBKR actually returned, copied from
docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md. An invented
fixture would test the parser against our idea of the format rather than
against the format.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from qat.data.broker.ib_hours import parse_ib_hours

_SYD = ZoneInfo("Australia/Sydney")

# Verbatim from the 21 August probe. A2M.AX, and identical for all fourteen.
TRADING = (
    "20260821:0959-20260821:1611;20260822:CLOSED;20260823:CLOSED;"
    "20260824:0959-20260824:1611;20260825:0959-20260825:1611;"
    "20260826:0959-20260826:1611"
)
LIQUID = (
    "20260821:0959-20260821:1600;20260822:CLOSED;20260823:CLOSED;"
    "20260824:0959-20260824:1600;20260825:0959-20260825:1600;"
    "20260826:0959-20260826:1600"
)


def test_parses_every_day_in_the_string():
    parsed = parse_ib_hours(TRADING, _SYD)
    assert sorted(parsed) == [
        date(2026, 8, 21),
        date(2026, 8, 22),
        date(2026, 8, 23),
        date(2026, 8, 24),
        date(2026, 8, 25),
        date(2026, 8, 26),
    ]


def test_a_trading_day_carries_one_timezone_aware_window():
    parsed = parse_ib_hours(TRADING, _SYD)
    assert parsed[date(2026, 8, 24)] == (
        (
            datetime(2026, 8, 24, 9, 59, tzinfo=_SYD),
            datetime(2026, 8, 24, 16, 11, tzinfo=_SYD),
        ),
    )


def test_closed_days_are_present_and_empty():
    """Absent and closed are different facts. A caller asking whether Saturday
    is a trading day must be able to tell "IBKR says closed" from "IBKR did not
    mention Saturday"."""
    parsed = parse_ib_hours(TRADING, _SYD)
    assert parsed[date(2026, 8, 22)] == ()
    assert date(2026, 8, 27) not in parsed


def test_liquid_hours_close_earlier_than_trading_hours():
    """The eleven-minute delta IS the closing auction, and it is the only
    auction constant in this design that was measured."""
    trading = parse_ib_hours(TRADING, _SYD)[date(2026, 8, 24)][0]
    liquid = parse_ib_hours(LIQUID, _SYD)[date(2026, 8, 24)][0]
    assert trading[0] == liquid[0]
    assert (trading[1] - liquid[1]).total_seconds() == 11 * 60


def test_a_day_may_carry_more_than_one_window():
    """Not seen on ASX, documented by IBKR, and a parser that dropped the
    second window would do so silently."""
    text = "20260824:0800-20260824:1200,20260824:1300-20260824:1600"
    parsed = parse_ib_hours(text, _SYD)
    assert len(parsed[date(2026, 8, 24)]) == 2


def test_a_window_may_span_midnight():
    parsed = parse_ib_hours("20260824:2200-20260825:0400", _SYD)
    start, end = parsed[date(2026, 8, 24)][0]
    assert start == datetime(2026, 8, 24, 22, 0, tzinfo=_SYD)
    assert end == datetime(2026, 8, 25, 4, 0, tzinfo=_SYD)


def test_unparseable_input_returns_empty_rather_than_raising():
    """This is read inside pre-flight. A vendor string in an unexpected shape
    must degrade to "no comparison available", never take down the checks."""
    assert parse_ib_hours("nonsense", _SYD) == {}
    assert parse_ib_hours("", _SYD) == {}
    assert parse_ib_hours("20260824:99999-20260824:1600", _SYD) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_hours.py -v`

Expected: FAIL, `ModuleNotFoundError: No module named 'qat.data.broker.ib_hours'`

- [ ] **Step 3: Write the implementation**

Create `src/qat/data/broker/ib_hours.py`:

```python
"""IBKR's trading-hours strings, parsed.

`ContractDetails.tradingHours` and `.liquidHours` are the exchange's own
statement of its session, per contract and per day, holidays and half-days
included. **`liquidHours` is continuous trading and `tradingHours` spans the
auctions**, so the difference between them is the auction windows.

Measured on 21 August 2026 (`scripts/asx_session_probe.py`), the ASX answers
with an eleven-minute tail - 1600 against 1611 - and an identical open, which
is what tells us the closing auction is derivable from this and the staggered
opening auction is not.

Lives at the vendor boundary rather than in `market_calendar` on purpose: the
domain module is imported by the replay harness and must not acquire a vendor's
string format. This module knows IBKR's shape and nothing about sessions.

Pure. No ib_async import, no I/O, no clock.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# "20260824:0959-20260824:1611" or "20260822:CLOSED", semicolon-separated,
# and a single day may carry comma-separated windows.
_CLOSED = "CLOSED"


def _parse_stamp(stamp: str, tz: ZoneInfo) -> datetime:
    day, clock = stamp.split(":")
    return datetime(
        int(day[0:4]),
        int(day[4:6]),
        int(day[6:8]),
        int(clock[0:2]),
        int(clock[2:4]),
        tzinfo=tz,
    )


def parse_ib_hours(text: str, tz: ZoneInfo) -> dict[date, tuple[tuple[datetime, datetime], ...]]:
    """Windows per exchange-local date. A CLOSED day maps to an empty tuple.

    Returns `{}` on anything it cannot read, rather than raising. This is
    consumed by pre-flight, where a vendor string in an unexpected shape must
    degrade to "no comparison available" and never take down the checks that
    surround it. A parser that raised here would convert a cosmetic surprise
    into a session that will not start.

    A CLOSED day is RECORDED rather than omitted, because "IBKR says closed"
    and "IBKR did not mention that day" are different facts and the holiday
    comparison needs to tell them apart.
    """
    if not text:
        return {}

    windows: dict[date, tuple[tuple[datetime, datetime], ...]] = {}
    try:
        for segment in text.split(";"):
            segment = segment.strip()
            if not segment:
                continue
            if segment.upper().endswith(_CLOSED):
                day = segment.split(":")[0]
                key = date(int(day[0:4]), int(day[4:6]), int(day[6:8]))
                windows[key] = ()
                continue
            for window in segment.split(","):
                start_stamp, end_stamp = window.split("-")
                start = _parse_stamp(start_stamp, tz)
                end = _parse_stamp(end_stamp, tz)
                # Keyed on the START date: a window spanning midnight belongs
                # to the session that opened it, not to the date it ends on.
                windows.setdefault(start.date(), ())
                windows[start.date()] = (*windows[start.date()], (start, end))
    except (ValueError, IndexError):
        return {}
    return windows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_hours.py -v`

Expected: PASS, 7 passed.

- [ ] **Step 5: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check src/qat/data/broker/ib_hours.py tests/data/broker/test_ib_hours.py
.venv/Scripts/python.exe -m black --check src/qat/data/broker/ib_hours.py tests/data/broker/test_ib_hours.py
git add src/qat/data/broker/ib_hours.py tests/data/broker/test_ib_hours.py
git commit -m "Parse IBKR's trading-hours strings at the vendor boundary"
```

---

### Task 2: `trading_state` on the session

**Files:**
- Modify: `src/qat/domain/market_calendar.py`
- Test: `tests/domain/test_market_calendar.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `TradingState = Literal["pre_open", "opening_auction", "continuous", "closing_auction", "closed"]`, exported from `qat.domain.market_calendar`. `MarketSession.trading_state: TradingState`, a **required** field. `_OPENING_AUCTION_MINUTES: dict[Market, int]` and `_AUCTION_TAIL_MINUTES: dict[Market, int]`, both `{"US": 0, "ASX": 10}` / `{"US": 0, "ASX": 11}`. Plus the public accessor `auction_tail_minutes(market: Market) -> int`, which is what Task 4 consumes — pre-flight must not import a private name across a module boundary.

**Deliberately untested:** the early-close case. On a half-day the tail is assumed to be the same eleven minutes after the 14:10 close, and no half-day fell inside the probe's six-day window, so there is nothing to assert it against. Task 4's check is what will surface it when one arrives. Do not invent a fixture for it.

Boundaries are half-open at the start and inclusive at the close: `[open, open+10m)` is `opening_auction`, `[open+10m, close]` is `continuous`, `(close, close+11m]` is `closing_auction`. 16:00:00 exactly stays `is_open=True`, preserving the existing `local > closes_at` comparison.

- [ ] **Step 1: Write the failing tests**

Append to `tests/domain/test_market_calendar.py`:

```python
# --- Auction states (Stage 3) -------------------------------------------------
#
# Constants measured on 21 August 2026 against the live paper Gateway; see
# docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md. 24 August 2026 is
# a Monday and IBKR reports it as a normal session.


def _syd_at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 8, 24, hh, mm, ss, tzinfo=_SYD)


@pytest.mark.parametrize(
    ("when", "expected_state", "expected_open"),
    [
        (_syd_at(9, 59), "pre_open", False),
        (_syd_at(10, 0), "opening_auction", True),
        (_syd_at(10, 9, 59), "opening_auction", True),
        (_syd_at(10, 10), "continuous", True),
        (_syd_at(12, 0), "continuous", True),
        (_syd_at(16, 0), "continuous", True),
        (_syd_at(16, 0, 1), "closing_auction", False),
        (_syd_at(16, 11), "closing_auction", False),
        (_syd_at(16, 11, 1), "closed", False),
    ],
)
def test_asx_trading_state_at_each_boundary(when, expected_state, expected_open):
    session = mc.session_for("ASX", when)
    assert session.trading_state == expected_state
    assert session.is_open is expected_open


def test_us_never_reaches_an_auction_state():
    """Both minute tables are zero for US, so this work cannot have moved the
    US trial record or the 499-session replay harness. If this test ever fails,
    the two are no longer comparable and that is the finding."""
    seen = set()
    for hour in range(0, 24):
        for minute in (0, 30):
            seen.add(mc.session_for("US", _ny(2026, 8, 24, hour, minute)).trading_state)
    assert seen <= {"pre_open", "continuous", "closed"}


def test_the_phase_boundaries_are_unchanged_by_the_auction_work():
    """The auction is modelled BESIDE the phase table, not inside it. Folding
    eleven minutes into the denominator would move every boundary in the day -
    Morning Trend would end at 12:00.4 rather than 11:58.8 - for a mechanism
    intraday volume patterns do not describe. This is the regression that would
    otherwise be invisible."""
    assert mc.session_for("ASX", _syd_at(10, 28)).phase == "Opening Volatility"
    assert mc.session_for("ASX", _syd_at(10, 29)).phase == "Morning Trend"
    assert mc.session_for("ASX", _syd_at(11, 58)).phase == "Morning Trend"
    assert mc.session_for("ASX", _syd_at(11, 59)).phase == "Midday Lull"
    assert mc.session_for("ASX", _syd_at(14, 5)).phase == "Afternoon"
    assert mc.session_for("ASX", _syd_at(15, 17)).phase == "Closing Session"
    assert mc.session_for("ASX", _syd_at(16, 0)).closes_at == _syd_at(16, 0)


def test_the_closing_auction_is_not_autonomous_eligible():
    """is_open is False through the auction, and is_autonomous_eligible is
    defined as is_open AND an eligible phase."""
    assert mc.session_for("ASX", _syd_at(16, 5)).is_autonomous_eligible is False


def test_closed_reason_names_the_auction_rather_than_saying_after_close():
    assert mc.session_for("ASX", _syd_at(16, 5)).closed_reason == "closing auction"
    assert mc.session_for("ASX", _syd_at(17, 0)).closed_reason == "after close"


def test_a_holiday_is_closed_not_pre_open():
    """Christmas Day 2026 is a Friday."""
    session = mc.session_for("ASX", datetime(2026, 12, 25, 11, 0, tzinfo=_SYD))
    assert session.trading_state == "closed"
    assert session.is_open is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/test_market_calendar.py -k "trading_state or auction or phase_boundaries" -v`

Expected: FAIL with `AttributeError: 'MarketSession' object has no attribute 'trading_state'`

- [ ] **Step 3: Add the type, the tables and the field**

In `src/qat/domain/market_calendar.py`, add `Literal` to the `typing` import if absent, then add after `AUTONOMOUS_ELIGIBLE_PHASES`:

```python
# What the exchange is DOING, as distinct from whether continuous trading is
# available. `is_open` keeps its existing meaning - continuous trading is
# available - because every caller already assumes it, and redefining it would
# change the autonomy gate, the feed and the stand-down at once.
TradingState = Literal[
    "pre_open", "opening_auction", "continuous", "closing_auction", "closed"
]

# MEASURED, 21 August 2026, against the live paper Gateway. IBKR reports the
# ASX as tradingHours 0959-1611 against liquidHours 0959-1600: an eleven-minute
# tail after continuous trading, which is the pre-CSPA and the closing auction.
# See docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md.
_AUCTION_TAIL_MINUTES: dict[Market, int] = {"US": 0, "ASX": 11}

# A JUDGEMENT, not a measurement, and the difference matters. The ASX opens in
# staggered alphabetical groups across roughly the first ten minutes, so an
# early-alphabet symbol is trading while a late one is still in its auction.
# IBKR does NOT expose this: all fourteen contracts probed across the alphabet
# returned identical hours, and the delta at the open is zero. Ten minutes is a
# deliberately conservative blanket over a window the broker cannot confirm.
#
# US is 0 on both tables, so a US session reaches only pre_open, continuous and
# closed and its behaviour is bit-identical to before this existed.
_OPENING_AUCTION_MINUTES: dict[Market, int] = {"US": 0, "ASX": 10}


def auction_tail_minutes(market: Market) -> int:
    """Minutes of auction after continuous trading ends.

    Public because pre-flight compares this against what IBKR reports, and a
    consumer reaching into `_AUCTION_TAIL_MINUTES` across a module boundary
    would be importing a private name to do it.
    """
    return _AUCTION_TAIL_MINUTES[market]
```

- [ ] **Step 4: Add the field to `MarketSession`**

In the `MarketSession` dataclass, add `trading_state` immediately after `phase`. It is REQUIRED, with no default: it is constructed in exactly four places, all in this module, and a default here would be silently wrong wherever it was omitted — the shape `ts=now` already had once.

```python
@dataclass(frozen=True, slots=True)
class MarketSession:
    market: Market
    is_open: bool
    phase: str | None
    trading_state: TradingState
    local_time: datetime
    opens_at: datetime | None
    closes_at: datetime | None
    is_early_close: bool = False
    closed_reason: str | None = None
```

- [ ] **Step 5: Set the state at all four construction sites in `session_for`**

The holiday branch and the before-open branch:

```python
    reason = closed_reason(market, day)
    if reason is not None:
        return MarketSession(
            market=market,
            is_open=False,
            phase=None,
            trading_state="closed",
            local_time=local,
            opens_at=None,
            closes_at=None,
            closed_reason=reason,
        )
```

```python
    if local < opens_at:
        return MarketSession(
            market=market,
            is_open=False,
            phase=None,
            trading_state="pre_open",
            local_time=local,
            opens_at=opens_at,
            closes_at=closes_at,
            is_early_close=is_early,
            closed_reason="before open",
        )
```

Replace the after-close branch so it distinguishes the auction from the close:

```python
    if local > closes_at:
        # The auction is a separate mechanism bolted to the end of continuous
        # trading, not a stretch of the session. `is_open` stays False through
        # it - a market order into a single-price auction fills at the auction
        # price - and only the REASON changes, so an operator reading a refusal
        # at 16:05 is told the exchange is mid-auction rather than shut.
        auction_end = closes_at + timedelta(minutes=_AUCTION_TAIL_MINUTES[market])
        in_auction = local <= auction_end
        return MarketSession(
            market=market,
            is_open=False,
            phase=None,
            trading_state="closing_auction" if in_auction else "closed",
            local_time=local,
            opens_at=opens_at,
            closes_at=closes_at,
            is_early_close=is_early,
            closed_reason="closing auction" if in_auction else "after close",
        )
```

And the open branch:

```python
    span = (closes_at - opens_at).total_seconds()
    elapsed = (local - opens_at).total_seconds() / span if span > 0 else 1.0
    auction_ends = opens_at + timedelta(minutes=_OPENING_AUCTION_MINUTES[market])
    return MarketSession(
        market=market,
        is_open=True,
        phase=session_phase(elapsed),
        # Half-open: 10:10:00 exactly is continuous, not still in the auction.
        trading_state="opening_auction" if local < auction_ends else "continuous",
        local_time=local,
        opens_at=opens_at,
        closes_at=closes_at,
        is_early_close=is_early,
    )
```

Add `timedelta` to the `datetime` import at the top of the module if it is not already there.

- [ ] **Step 6: Run the calendar tests**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/test_market_calendar.py -v`

Expected: PASS, all tests including the pre-existing ones.

- [ ] **Step 7: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: **2517+ passed, 25 skipped**, no failures. Read the summary line; do not pipe it. Any failure here is a caller that constructed a `MarketSession` positionally — fix by naming the argument, not by adding a default.

- [ ] **Step 8: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m black --check .
.venv/Scripts/python.exe -m mypy src
git add src/qat/domain/market_calendar.py tests/domain/test_market_calendar.py
git commit -m "A session knows whether it is in an auction, not just whether it is open"
```

---

### Task 3: Refuse discretionary orders into the opening auction

**Files:**
- Modify: `src/qat/domain/autonomy/gate.py`
- Test: `tests/safety/test_autonomy_gate.py`

**Interfaces:**
- Consumes: `MarketSession.trading_state` from Task 2.
- Produces: no new public names. A `GateDecision` with `allowed=False` whose `reason` contains `"opening auction"`.

- [ ] **Step 1: Write the failing tests**

That file already has `_settings()`, `_order()`, `_account()` and `_gate()` helpers and calls `gate.evaluate(order, account, now=...)`. Reuse them. The market is derived from the symbol by `market_for_symbol`, so an ASX symbol is what selects the ASX calendar.

`_order()` has no `order_type` parameter yet, and `is_protective_stop` is `order_type == "stop" and side == "sell"` (`adapter.py:64`). Add the parameter first:

```python
def _order(
    side: str = "buy",
    symbol: str = "AAPL",
    quantity: float = 10.0,
    strategy: str | None = "swing",
    reference_price: float | None = 100.0,
    status: str = "pending_signoff",
    order_type: str = "market",
) -> Order:
    return Order(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        order_id="test-order",
        status=status,  # type: ignore[arg-type]
        reference_price=reference_price,
        strategy=strategy,
        order_type=order_type,  # type: ignore[arg-type]
    )
```

Then append:

```python
# --- The opening auction (Stage 3) -------------------------------------------

# 24 August 2026 is a Monday. The ASX opening auction runs to roughly 10:10.
ASX_OPENING_AUCTION = datetime(2026, 8, 24, 10, 5, tzinfo=_SYD)
ASX_CONTINUOUS = datetime(2026, 8, 24, 10, 15, tzinfo=_SYD)


def test_a_market_sell_into_the_opening_auction_is_refused():
    """Sells return allowed BEFORE the session-phase check, which is correct -
    risk-reducing orders are not gated on appetite. But a market order into a
    single-price auction fills at the auction price, not a quoted one, which is
    the same unpriced fill this gate already refuses into a closed market."""
    decision = _gate().evaluate(
        _order(side="sell", symbol="BHP.AX", strategy=None),
        _account(),
        now=ASX_OPENING_AUCTION,
    )
    assert decision.allowed is False
    assert "opening auction" in decision.reason


def test_the_same_sell_is_allowed_once_continuous_trading_starts():
    decision = _gate().evaluate(
        _order(side="sell", symbol="BHP.AX", strategy=None),
        _account(),
        now=ASX_CONTINUOUS,
    )
    assert decision.allowed is True


def test_a_resting_protective_order_is_still_allowed_in_the_auction():
    """This is what makes the refusal cheap. A GTC stop already rests at the
    broker and participates in the auction whether or not the app will transmit
    anything, so refusing a discretionary exit removes no protection. If this
    test fails, the block was inserted ABOVE the is_protective_stop early
    return and the repair path is dead in the window it exists for - which is
    exactly the M33c defect, one boundary further in."""
    decision = _gate().evaluate(
        _order(side="sell", symbol="BHP.AX", strategy=None, order_type="stop"),
        _account(),
        now=ASX_OPENING_AUCTION,
    )
    assert decision.allowed is True


def test_the_us_open_is_unaffected():
    """US is 0 minutes on the opening-auction table, so a US sell just after
    the bell is still allowed and this work did not narrow the US record."""
    decision = _gate().evaluate(
        _order(side="sell", strategy=None), _account(), now=OPENING_BELL_US
    )
    assert decision.allowed is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/safety/test_autonomy_gate.py -k "auction" -v`

Expected: FAIL — the sell is currently allowed at 10:05, so the first test fails on `assert decision.allowed is False`.

- [ ] **Step 3: Add the refusal**

In `src/qat/domain/autonomy/gate.py`, immediately after the existing `if not session.is_open:` block and before the `# --- Sells:` comment:

```python
        # The exchange is running a single-price auction, so there is no quoted
        # price to hit. A market order placed into one fills at whatever the
        # auction strikes - the same unpriced fill the closed-market rule above
        # refuses, arriving through a door the calendar used to leave open,
        # because it reported the ASX open at 10:00 when the opening auction
        # runs to roughly 10:10.
        #
        # Deliberately BELOW the `is_protective_stop` return, which outranks
        # every rule here. A resting GTC stop is already at the broker and takes
        # part in the auction whether or not this process transmits anything, so
        # refusing a DISCRETIONARY exit removes no protection - it delays a
        # signal or time stop by minutes.
        if session.trading_state == "opening_auction":
            return block(
                "the opening auction is running - a market order into a single-price "
                "auction fills at the auction price, not a quoted one"
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/safety/test_autonomy_gate.py -v`

Expected: PASS, including every pre-existing gate test.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: **2520+ passed, 25 skipped**.

- [ ] **Step 6: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m black --check .
git add src/qat/domain/autonomy/gate.py tests/safety/test_autonomy_gate.py
git commit -m "Refuse a market order into the ASX opening auction"
```

---

### Task 4: Pre-flight compares the constants against the broker

**Files:**
- Modify: `src/qat/preflight.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: `parse_ib_hours` from Task 1; `regular_hours`, `MARKET_TIMEZONES`, `is_trading_day`, `_AUCTION_TAIL_MINUTES` from Task 2.
- Produces: `compare_session_hours(trading_hours: str, liquid_hours: str, time_zone_id: str, market: str, days: Sequence[date]) -> list[Check]`. Takes plain strings rather than a `ContractDetails` so it is pure and testable without ib_async.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_preflight.py`:

```python
# --- Session hours against the broker (Stage 3) -------------------------------

_TRADING = (
    "20260824:0959-20260824:1611;20260825:0959-20260825:1611;20260822:CLOSED"
)
_LIQUID = "20260824:0959-20260824:1600;20260825:0959-20260825:1600;20260822:CLOSED"
_DAYS = [date(2026, 8, 24), date(2026, 8, 25), date(2026, 8, 22)]


def test_agreement_reports_one_ok_line_not_four():
    """Four green lines for one round trip is noise in an instrument read at
    the open."""
    checks = preflight.compare_session_hours(_TRADING, _LIQUID, "Australia/NSW", "ASX", _DAYS)
    assert len(checks) == 1
    assert checks[0].status is preflight.Status.OK


def test_a_different_continuous_close_warns_and_quotes_both():
    checks = preflight.compare_session_hours(
        _TRADING, _LIQUID.replace("1600", "1530"), "Australia/NSW", "ASX", _DAYS
    )
    assert any(c.status is preflight.Status.WARN and "15:30" in c.detail for c in checks)


def test_a_different_auction_tail_warns():
    """The eleven minutes is the one measured auction constant. If IBKR stops
    saying eleven, the model is wrong and this is the only thing that would
    say so."""
    checks = preflight.compare_session_hours(
        _TRADING.replace("1611", "1620"), _LIQUID, "Australia/NSW", "ASX", _DAYS
    )
    assert any(c.status is preflight.Status.WARN and "auction" in c.detail for c in checks)


def test_a_day_ibkr_calls_closed_that_the_calendar_calls_open_warns():
    """This is the valuable one: asx_holidays(), _EARLY_CLOSE_TIMES and
    EXTRA_CLOSURES are all hand-maintained, and this is the first thing that
    contradicts them out of the exchange's own mouth."""
    checks = preflight.compare_session_hours(
        "20260824:CLOSED", "20260824:CLOSED", "Australia/NSW", "ASX", [date(2026, 8, 24)]
    )
    assert any(c.status is preflight.Status.WARN and "2026-08-24" in c.detail for c in checks)


def test_the_accepted_open_divergence_stays_silent():
    """IBKR reports 0959 for every ASX contract; the app says 10:00. Recorded
    as accepted on 21 August 2026. A check that warns on every run is a check
    people stop reading."""
    checks = preflight.compare_session_hours(_TRADING, _LIQUID, "Australia/NSW", "ASX", _DAYS)
    assert all("09:59" not in c.detail for c in checks)


def test_an_unaccepted_open_difference_does_warn():
    """The allowlist is one entry, not a tolerance band. A band would swallow
    the next disagreement too."""
    checks = preflight.compare_session_hours(
        _TRADING.replace("0959", "0930"),
        _LIQUID.replace("0959", "0930"),
        "Australia/NSW",
        "ASX",
        _DAYS,
    )
    assert any(c.status is preflight.Status.WARN and "09:30" in c.detail for c in checks)


def test_an_unparseable_string_warns_and_does_not_block_ready():
    """A deliberate departure from this module's UNKNOWN rule; see the comment
    at the call site. Every other check asks whether something the session
    DEPENDS ON is true. This one asks whether a constant still agrees with the
    broker, and the calendar is authoritative at runtime either way."""
    checks = preflight.compare_session_hours("nonsense", "nonsense", "", "ASX", _DAYS)
    assert checks
    assert all(c.status is preflight.Status.WARN for c in checks)
    assert preflight.verdict_for(checks) is preflight.Verdict.READY
```

Add `from datetime import date` to that file's imports if it is not already present.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_preflight.py -k "session_hours or divergence or accepted or auction or unparseable or agreement" -v`

Expected: FAIL, `AttributeError: module 'qat.preflight' has no attribute 'compare_session_hours'`

- [ ] **Step 3: Write the implementation**

In `src/qat/preflight.py`, add the imports and the accepted-divergence table near the top, after the existing imports:

```python
from datetime import date, time

from qat.data.broker.ib_hours import parse_ib_hours
from qat.domain.market_calendar import (
    MARKET_TIMEZONES,
    auction_tail_minutes,
    is_trading_day,
    regular_hours,
)

# (market, boundary) -> (app value, IBKR value, when measured, why accepted)
#
# A disagreement recorded here has been LOOKED AT and accepted, which is why
# each entry carries the date it was measured and the reason: an undated
# exception is indistinguishable from one nobody has re-examined.
#
# An allowlist of exactly one, NOT a tolerance band - a band would swallow the
# next disagreement too.
_ACCEPTED_HOURS_DIVERGENCES: dict[tuple[str, str], tuple[time, time, str, str]] = {
    ("ASX", "open"): (
        time(10, 0),
        time(9, 59),
        "2026-08-21",
        "IBKR reports 0959 for every ASX contract probed; 10:00 is when ASX "
        "continuous trading starts, so this reads as broker-side rounding. See "
        "docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md",
    ),
}
```

Then the comparison function:

```python
def compare_session_hours(
    trading_hours: str,
    liquid_hours: str,
    time_zone_id: str,
    market: str,
    days: Sequence[date],
) -> list[Check]:
    """Does the hand-maintained calendar still agree with the exchange?

    `_REGULAR_HOURS`, `asx_holidays()`, `_EARLY_CLOSE_TIMES`, `EXTRA_CLOSURES`
    and `_AUCTION_TAIL_MINUTES` are all maintained by hand. IBKR states the
    same facts per contract and per day, and this is the only thing that would
    notice if the two drifted apart. On 21 August a hand-maintained constant in
    `handoff_state.py` was found wrong for a day for want of exactly this.

    **WARN, never FAIL, and never UNKNOWN - a deliberate departure from this
    module's rule that a check which could not be performed is not a check that
    passed.** Every other check here asks whether something the session DEPENDS
    ON is true, so an unanswerable one should stop the session. This one asks
    whether a constant still matches the broker; the calendar is authoritative
    at runtime either way, so nothing about the session degrades when the
    comparison cannot be made. UNKNOWN would let an odd vendor string block
    trading over a disagreement that is cosmetic by construction.
    """
    tz = MARKET_TIMEZONES[market]  # type: ignore[index]
    trading = parse_ib_hours(trading_hours, tz)
    liquid = parse_ib_hours(liquid_hours, tz)
    if not trading or not liquid:
        return [
            Check(
                "session hours",
                Status.WARN,
                "IBKR returned trading hours this cannot read, so the calendar "
                "constants were not compared against the exchange this session",
            )
        ]

    open_time, close_time = regular_hours(market)  # type: ignore[arg-type]
    tail = auction_tail_minutes(market)  # type: ignore[arg-type]
    warnings: list[Check] = []

    for day in sorted(days):
        windows = liquid.get(day)
        if windows is None:
            continue
        if not windows:
            if is_trading_day(market, day):  # type: ignore[arg-type]
                warnings.append(
                    Check(
                        "session hours",
                        Status.WARN,
                        f"IBKR reports {day.isoformat()} CLOSED; the calendar calls it a "
                        "trading day. The holiday table is hand-maintained and this is "
                        "the exchange contradicting it",
                    )
                )
            continue
        if not is_trading_day(market, day):  # type: ignore[arg-type]
            warnings.append(
                Check(
                    "session hours",
                    Status.WARN,
                    f"IBKR reports {day.isoformat()} as trading; the calendar calls it "
                    "closed",
                )
            )
            continue

        start, end = windows[0]
        if start.time() != open_time and not _accepted(market, "open", open_time, start.time()):
            warnings.append(
                Check(
                    "session hours",
                    Status.WARN,
                    f"{day.isoformat()} opens at {start.time():%H:%M} on IBKR, "
                    f"{open_time:%H:%M} in the calendar",
                )
            )
        if end.time() != close_time and not _accepted(market, "close", close_time, end.time()):
            warnings.append(
                Check(
                    "session hours",
                    Status.WARN,
                    f"{day.isoformat()} closes at {end.time():%H:%M} on IBKR, "
                    f"{close_time:%H:%M} in the calendar",
                )
            )

        trading_windows = trading.get(day)
        if trading_windows:
            measured = round((trading_windows[0][1] - end).total_seconds() / 60)
            if measured != tail:
                warnings.append(
                    Check(
                        "session hours",
                        Status.WARN,
                        f"{day.isoformat()} auction tail is {measured} minute(s) on IBKR, "
                        f"{tail} in the model",
                    )
                )

    if time_zone_id and ZoneInfo(_IB_ZONE_ALIASES.get(time_zone_id, time_zone_id)) != tz:
        warnings.append(
            Check(
                "session hours",
                Status.WARN,
                f"IBKR reports timezone {time_zone_id}, the calendar uses {tz}",
            )
        )

    if warnings:
        return warnings
    return [
        Check(
            "session hours",
            Status.OK,
            f"{market} hours, auction tail and trading days all match IBKR "
            f"across {len(days)} day(s)",
        )
    ]


def _accepted(market: str, boundary: str, app_value: time, ib_value: time) -> bool:
    entry = _ACCEPTED_HOURS_DIVERGENCES.get((market, boundary))
    return entry is not None and entry[0] == app_value and entry[1] == ib_value
```

Add near the other module constants:

```python
# IBKR names some zones by their legacy aliases. Australia/NSW and
# Australia/Sydney are the same zone; the label differing is not a finding.
_IB_ZONE_ALIASES: dict[str, str] = {"Australia/NSW": "Australia/Sydney"}
```

Add `from zoneinfo import ZoneInfo` to the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_preflight.py -v`

Expected: PASS, including every pre-existing pre-flight test.

- [ ] **Step 5: Wire it into `contract_checks`**

In `contract_checks`, keep the first resolved `ContractDetails` and append the comparison, so the check costs no extra round trip:

```python
    unresolved: list[str] = []
    first: object | None = None
    for symbol in symbols:
        try:
            details = await request(to_ib_contract(symbol, market))
        except Exception:  # noqa: BLE001
            unresolved.append(symbol)
            continue
        if not details:
            unresolved.append(symbol)
        elif first is None:
            first = details[0]
```

and before the final `return`, after the `unresolved` branch:

```python
    checks = [Check("contracts", Status.OK, f"all {len(symbols)} resolve on {market}")]
    if first is not None:
        today = trading_date(market)  # type: ignore[arg-type]
        checks.extend(
            compare_session_hours(
                str(getattr(first, "tradingHours", "")),
                str(getattr(first, "liquidHours", "")),
                str(getattr(first, "timeZoneId", "")),
                market,
                [today],
            )
        )
    return checks
```

Add `trading_date` to the `market_calendar` import.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: **2527+ passed, 25 skipped**.

- [ ] **Step 7: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m black --check .
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/python.exe -m bandit -q -r src
git add src/qat/preflight.py tests/test_preflight.py
git commit -m "Pre-flight asks IBKR whether the calendar constants are still true"
```

---

### Task 5: Verify against the live Gateway, and record it

**Files:**
- Modify: `docs/HANDOFF.md`
- Modify: `src/qat/version.py` (milestone note)

This task is a MEASUREMENT, not a code change. Tasks 1–4 are green against fakes; this is the half only a Gateway can answer, and this project's record says the fakes and the broker have disagreed four times.

- [ ] **Step 1: Run the pre-flight against the live paper Gateway**

The runner is `scripts/preflight.py` — there is no `python -m qat.preflight`. It is read-only, places nothing and exits non-zero when blocked. Run it **under PowerShell**, because it builds `Settings()` and therefore loads `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env` whether or not it mentions it:

```
.venv\Scripts\python.exe scripts/preflight.py
```

Expected: a `session hours` line reading `OK`, naming the ASX hours, tail and trading days. **If it WARNs, that is a finding, not a failure** — record what IBKR said against what the calendar says before changing either. The whole point of this check is that it can disagree with us.

- [ ] **Step 2: Re-run the probe and confirm the raw report is unchanged**

Run: `.venv\Scripts\python.exe scripts/asx_session_probe.py --out docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md`

Then: `git diff --stat docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md`

Expected: only the probe timestamp line differs. Any change to the hours themselves means the exchange moved and the constants need revisiting.

- [ ] **Step 3: Update the milestone and the handoff**

Set `MILESTONE` in `src/qat/version.py` to the next unused number (M135 was taken on the evening of 21 August by the AI-advisor and design-system work, so this is M136 unless something else has shipped since — check the constant rather than trusting this line) and describe this work in one line, following the shape of the existing milestone notes in that file.

In `docs/HANDOFF.md`, mark outstanding item 9 as done in the same style as items 8, 10, 12 and 14 — struck through, with what shipped and what the original said. State explicitly that the minimum parcel and T+2 were deferred as live-only by operator decision on 21 August, and carry the paper-fidelity residual across: if IBKR paper fills a sub-$500 order the live exchange would refuse, the paper record is optimistic by exactly the trades that could not have happened. **Do not let that residual die with the item** — an unrecorded deferral reads later as an oversight.

- [ ] **Step 4: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m black --check .
git add -A
git commit -m "ASX auctions are modelled and the calendar is checked against the exchange"
```

**Do not push.** Actions minutes are exhausted until September.

---

## What this plan deliberately does NOT do

- **No deploy.** Building and installing is a separate, operator-gated step, and never mid-session.
- **No change to `_REGULAR_HOURS`, `SESSION_PHASES`, `AUTONOMOUS_ELIGIBLE_PHASES` or `closes_at`.**
- **No per-symbol staggered-open model.** Not derivable from IBKR; settled by measurement, not opinion.
- **No minimum parcel and no T+2.** Operator decision, 21 August: live-only concerns.
- **No order-routing change.** Every order is a market order (M44); this refuses one in a window rather than changing what is sent.
