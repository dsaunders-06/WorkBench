# Absent-Price Refusal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse an entry on a symbol whose most recent price does not belong to the current trading session, and report the condition before any entry is attempted — so the blind window is closed by an assertion rather than by the entry gate happening to open eight minutes later.

**Architecture:** `AutonomyGate` gains a `last_print_source` callable and refuses BUYS whose latest print is absent or pre-session, following the pattern its own `scorecard_source` already establishes. `MarketDataFeed` exposes `last_print_at` and reports absent symbols with a count. The gate enforces; the rail reports.

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-absent-price-refusal-design.md` (commit `41f04ef`).

## Global Constraints

- **The FULL suite, not the targeted one**, plus ruff, black, `mypy src`, bandit — every task.
- **PowerShell** for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal`, including Python that only reads it or builds `Settings()`.
- **Use the edit tool, which errors on a failed match.** A `str.replace` in a heredoc silently no-opped six times in one week.
- **BUYS ONLY.** Sells and protective stops return allowed earlier in `evaluate` and must stay that way. Refusing an exit because the feed is quiet strands a position in exactly the conditions where getting out matters.
- **Compare on `mc.trading_date(market, …)`, never a calendar or UTC date.** A UTC date is the bug M120 fixed in the unattended fixture.
- **A `None` source means today's behaviour** — the gate does not refuse. Compatibility for every existing call site and the backtester, pinned by a wiring test.
- Next milestone number: **M158**.
- ⚠️ **Implementation is intended for an OPEN MARKET session**, not a late night. The item was deferred on 25 August for exactly this reason and this is the entry path.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/qat/domain/autonomy/gate.py` | The entry decision | Add `last_print_source` param (line 68-84); add the refusal in the buys section (after line 160) |
| `src/qat/data/market_data.py` | The feed and its staleness rail | Add `last_print_at()`; replace the `last is None: continue` branch (line 291) with counted reporting |
| `src/qat/domain/evaluation/refusals.py` | Refusal reason → family + label | One new entry beside `("stale", …)` at line 128 |
| `src/qat/presentation/runtime.py` | Wiring | Assign the source after the feed exists (see Task 3 — ordering matters) |
| `tests/domain/autonomy/test_absent_price_refusal.py` | Gate behaviour, the control, the planted sell | Create |
| `tests/data/test_absent_symbol_reporting.py` | The rail's count and its silence cases | Create |

---

### Task 1: The gate refuses a buy with no price this session

**Files:**
- Create: `tests/domain/autonomy/test_absent_price_refusal.py`
- Modify: `src/qat/domain/autonomy/gate.py`
- Modify: `src/qat/domain/evaluation/refusals.py:128`

**Interfaces:**
- Produces: `AutonomyGate(settings, kill_switch, clock=None, scorecard_source=None, last_print_source: Callable[[str], datetime | None] | None = None)`, relied on by Task 3.

- [ ] **Step 1: Write the failing tests**

⚠️ **Copy the existing gate fixture rather than inventing one.** `tests/domain/autonomy/` holds only the drift-guard test — the gate fixtures are in **`tests/safety/test_autonomous_executor.py`** (see `_build` at line 90, which constructs `AutonomyGate(settings, switch, clock=lambda: now)` against a pinned `OPEN_US`) and `tests/domain/oms/test_oms_clock.py`.

⚠️ **Pin the clock and use an ASX symbol.** `_build`'s `OPEN_US` is a US session time; this item is about the ASX, and `market_for_symbol` derives the market from the symbol. A fixture that pins a US open while asserting Sydney trading dates would pass or fail by time of day — the M120 trap in a new place. Build `gate_factory(last_print_source=...)` to construct `AutonomyGate(settings, kill_switch, clock=lambda: OPEN_TODAY, last_print_source=...)` and give every order an `.AX` symbol.

Then write these six cases:

```python
def test_a_buy_with_no_price_this_session_is_refused(gate_factory) -> None:
    """The symbol has never printed. ABSENT, not stale - the staleness rail
    skips it entirely (`if last is None: continue`), so nothing else refuses."""
    gate = gate_factory(last_print_source=lambda _s: None)
    decision = gate.evaluate(buy_order("BHP.AX"), account, now=OPEN_TODAY)
    assert decision.allowed is False
    assert "no price at all this session" in decision.reason
    assert "stale" not in decision.reason


def test_a_buy_priced_only_before_this_session_is_refused(gate_factory) -> None:
    """Yesterday's close served as if current. The staleness rail WOULD catch
    this - on its next periodic pass. The signal is computed on tick arrival,
    and this closes that race."""
    gate = gate_factory(last_print_source=lambda _s: YESTERDAY_1559_SYDNEY)
    decision = gate.evaluate(buy_order("BHP.AX"), account, now=OPEN_TODAY)
    assert decision.allowed is False
    assert "previous session" in decision.reason


def test_a_buy_priced_this_session_is_not_refused_for_this_reason(gate_factory) -> None:
    """⚠️ THE CONTROL. Without it, a gate that refuses EVERYTHING passes both
    tests above."""
    gate = gate_factory(last_print_source=lambda _s: TODAY_1001_SYDNEY)
    decision = gate.evaluate(buy_order("BHP.AX"), account, now=OPEN_TODAY)
    assert "session" not in decision.reason or decision.allowed, decision.reason


def test_a_sell_is_never_refused_for_an_absent_price(gate_factory) -> None:
    """⚠️ PLANTED. Refusing an exit because the feed is quiet strands a position
    in exactly the conditions where getting out matters - strictly worse than
    the hazard being prevented."""
    gate = gate_factory(last_print_source=lambda _s: None)
    decision = gate.evaluate(sell_order("BHP.AX"), account, now=OPEN_TODAY)
    assert decision.allowed is True


def test_a_protective_stop_is_never_refused_for_an_absent_price(gate_factory) -> None:
    """Rests GTC and executes nothing until its level trades. It returns allowed
    above even the market-closed check, and must keep doing so."""
    gate = gate_factory(last_print_source=lambda _s: None)
    decision = gate.evaluate(protective_stop("BHP.AX"), account, now=OPEN_TODAY)
    assert decision.allowed is True


def test_the_trading_date_boundary_is_the_exchange_session_not_a_utc_date(gate_factory) -> None:
    """⚠️ BOTH SIDES. A print at 23:59 Sydney yesterday refuses; 00:01 Sydney
    today does not. A calendar-date or UTC-date implementation fails this, and
    a UTC date is the exact bug M120 fixed in the unattended fixture."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    syd = ZoneInfo("Australia/Sydney")
    before = datetime(2026, 8, 30, 23, 59, tzinfo=syd)
    after = datetime(2026, 8, 31, 0, 1, tzinfo=syd)

    refused = gate_factory(last_print_source=lambda _s: before).evaluate(
        buy_order("BHP.AX"), account, now=OPEN_31ST
    )
    allowed = gate_factory(last_print_source=lambda _s: after).evaluate(
        buy_order("BHP.AX"), account, now=OPEN_31ST
    )
    assert refused.allowed is False
    assert "previous session" in refused.reason
    assert "previous session" not in allowed.reason
```

Define `OPEN_TODAY` and `OPEN_31ST` as times inside the ASX continuous session on their respective dates, and `buy_order` / `sell_order` / `protective_stop` from the existing fixture's order builder.

- [ ] **Step 2: Run them and confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/autonomy/test_absent_price_refusal.py -v
```

Expected: the two refusal tests and the boundary test FAIL (the gate allows, because no such check exists). ⚠️ **The control, the sell and the protective stop must PASS already** — they assert today's behaviour, and that is what makes the failures meaningful.

- [ ] **Step 3: Add the parameter**

In `src/qat/domain/autonomy/gate.py`, extend `__init__`:

```python
        scorecard_source: Callable[[str], StrategyScorecard | None] | None = None,
        last_print_source: Callable[[str], datetime | None] | None = None,
    ) -> None:
```

and store it with the reasoning:

```python
        # The symbol's most recent PRINT time, or None if it has never printed
        # (item 33). A callable for the same reason `scorecard_source` is one:
        # the gate stays a pure decision function and can be exercised without
        # a feed. None disables the check, which keeps every existing call site
        # and the backtester unchanged - and is why a WIRING test exists.
        self.last_print_source = last_print_source
```

- [ ] **Step 4: Add the refusal in the buys section**

In `evaluate`, immediately after the `--- Buys: every gate ---` banner at line 160 and before the `is_autonomous_eligible` check:

```python
        # ⚠️ ABSENCE IS NOT STALENESS (item 33). The staleness rail skips a
        # symbol it has never seen - `if last is None: continue` - so nothing
        # else refuses this. And a PRE-SESSION print is caught by that rail only
        # on its next periodic pass, while the signal that produced this order
        # was computed on tick arrival. This closes that race by asserting at
        # the point of decision.
        #
        # Below the sell and protective-stop exemptions on purpose: refusing an
        # EXIT because the feed is quiet would strand a position in exactly the
        # conditions where getting out matters.
        if self.last_print_source is not None:
            last_print = self.last_print_source(order.symbol)
            if last_print is None:
                return block(
                    f"{order.symbol} has no price at all this session, so there is nothing "
                    "current to size against - ABSENT, not stale"
                )
            if mc.trading_date(market, last_print) < mc.trading_date(market, now):
                return block(
                    f"{order.symbol}'s last price is from a previous session "
                    f"({last_print:%Y-%m-%d %H:%M %Z}), so it is not current"
                )
```

⚠️ `now` may be `None` when no clock is set and none was passed; `mc.trading_date` accepts `None` and uses the wall clock, which matches how `mc.session_for(market, now)` is already called above.

- [ ] **Step 5: Add the refusal reasons to `refusals.py`**

Beside `("stale", RefusalFamily.STATE, "Stale market data")` at line 128:

```python
    # Item 33. DISTINCT from "stale" on purpose: a symbol that has never printed
    # is ABSENT, and the staleness rail cannot see it at all. One label, because
    # the Blotter groups by cause and both causes are "no current price".
    ("no price at all this session", RefusalFamily.STATE, "No price this session"),
    ("last price is from a previous session", RefusalFamily.STATE, "No price this session"),
```

- [ ] **Step 6: Run the tests and confirm all six pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/autonomy/test_absent_price_refusal.py -v
```

- [ ] **Step 7: Run the FULL suite and the three static checks**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

⚠️ **Expect failures here even if Task 1 is correct.** Existing gate tests that construct `AutonomyGate` without a source are unaffected (the check is disabled), but any test that DOES pass one, or any end-to-end test whose feed has not printed, will now refuse. Read each failure before changing it: a test that starts failing because the rail now works is telling you the rail works.

- [ ] **Step 8: Commit**

```bash
git add tests/domain/autonomy/test_absent_price_refusal.py src/qat/domain/autonomy/gate.py src/qat/domain/evaluation/refusals.py
```

```bash
git commit -m "M158: absence is its own refusal, asserted at the point of decision"
```

---

### Task 2: The feed exposes and reports absence

**Files:**
- Create: `tests/data/test_absent_symbol_reporting.py`
- Modify: `src/qat/data/market_data.py` — add `last_print_at`, replace the `last is None` branch at line 291

**Interfaces:**
- Produces: `MarketDataFeed.last_print_at(symbol: str) -> datetime | None`, used by Task 3.

- [ ] **Step 1: Write the failing tests**

```python
"""Absence reported as a COUNT, and silent where a count would be noise."""

from __future__ import annotations

import logging

import pytest

from qat.data.market_data import MarketDataFeed
from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent


def _feed(symbols):
    class _Source:
        async def get_quotes(self, syms):  # pragma: no cover - never driven here
            return {}

    return MarketDataFeed(EventBus(), _Source(), symbols)


def test_last_print_at_reports_none_for_a_symbol_that_never_printed() -> None:
    feed = _feed(["AAA", "BBB"])
    assert feed.last_print_at("AAA") is None


def test_last_print_at_reports_the_print_time_once_seen() -> None:
    from datetime import UTC, datetime

    feed = _feed(["AAA"])
    seen = datetime(2026, 8, 31, 0, 5, tzinfo=UTC)
    feed._last_seen["AAA"] = seen
    assert feed.last_print_at("AAA") == seen


@pytest.mark.asyncio
async def test_absent_symbols_are_reported_with_a_count(caplog) -> None:
    """⚠️ A COUNT, not an adjective (M154). M151 asserted a suppression that
    never reached the log - 678 claimed against 774 still present."""
    from datetime import UTC, datetime

    feed = _feed(["AAA", "BBB", "CCC"])
    feed._last_seen["AAA"] = datetime.now(UTC)

    with caplog.at_level(logging.WARNING):
        await feed._check_staleness_once()

    line = next((m for m in caplog.messages if "have not printed" in m), None)
    assert line is not None, "absence was not reported at all"
    assert "2 of 3" in line


@pytest.mark.asyncio
async def test_nothing_is_reported_before_the_first_tick(caplog) -> None:
    """⚠️ THE NOISE CASE, and the reason the trigger is not "the session has
    opened": MarketDataFeed holds no market and no session and cannot express
    that. At the bell and on every outside-hours launch NOTHING has printed, and
    "94 of 94 absent" every pass would be noise, not a signal."""
    feed = _feed(["AAA", "BBB", "CCC"])

    with caplog.at_level(logging.WARNING):
        await feed._check_staleness_once()

    assert not [m for m in caplog.messages if "have not printed" in m]


@pytest.mark.asyncio
async def test_absence_is_reported_once_not_every_pass(caplog) -> None:
    from datetime import UTC, datetime

    feed = _feed(["AAA", "BBB"])
    feed._last_seen["AAA"] = datetime.now(UTC)

    with caplog.at_level(logging.WARNING):
        await feed._check_staleness_once()
        await feed._check_staleness_once()

    assert len([m for m in caplog.messages if "have not printed" in m]) == 1


@pytest.mark.asyncio
async def test_absence_never_publishes_a_stale_event() -> None:
    """⚠️ DataStaleEvent means "last printed N seconds ago", which is FALSE for a
    symbol that never printed. Routing absence through it would make the log lie
    in the exact way item 33 exists to stop."""
    from datetime import UTC, datetime

    feed = _feed(["AAA", "BBB"])
    feed._last_seen["AAA"] = datetime.now(UTC)
    seen: list[DataStaleEvent] = []
    feed.bus.subscribe(DataStaleEvent, lambda e: seen.append(e))

    await feed._check_staleness_once()

    assert not [e for e in seen if e.symbol == "BBB"]
```

- [ ] **Step 2: Run them and confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_absent_symbol_reporting.py -v
```

Expected: the two `last_print_at` tests FAIL with `AttributeError`; the count test FAILS on "absence was not reported at all"; the three silence tests PASS already, because nothing reports anything yet. **Those three are regression guards, not new behaviour, and saying so is more honest than counting them as wins.**

- [ ] **Step 3: Add the accessor**

In `src/qat/data/market_data.py`, as a public method on `MarketDataFeed`:

```python
    def last_print_at(self, symbol: str) -> datetime | None:
        """When this symbol's most recent print was stamped, or None if it has
        never printed since `start()` (item 33).

        `start()` clears `_last_seen`, so after the overnight stand-down every
        symbol reads None until it prints again - which is correct: nothing from
        before the restart is a current price.
        """
        return self._last_seen.get(symbol)
```

- [ ] **Step 4: Report absence with a count**

Add an instance attribute in `__init__`, beside `self._last_seen`:

```python
        # Item 33. Reported once on transition rather than every pass.
        self._absence_reported = False
```

Then replace the silent skip at line 291. The loop keeps its `continue`; the counting happens around it:

```python
        absent = [s for s in self.symbols if self._last_seen.get(s) is None]
        # ⚠️ Only once SOMETHING has printed. MarketDataFeed knows no market and
        # no session, so it cannot say "the session has opened" - and it does not
        # need to. "The feed is working and these symbols are not in it" is the
        # condition that matters, and before the first tick there is no line at
        # all rather than a false "94 of 94 absent" at every bell.
        if absent and len(absent) < len(self.symbols) and not self._absence_reported:
            self._absence_reported = True
            logger.warning(
                "%d of %d watched symbol(s) have not printed at all this session, so they are "
                "ABSENT rather than stale and the staleness rail cannot see them - it skips a "
                "symbol it has never seen. They cannot be entered: %s",
                len(absent),
                len(self.symbols),
                ", ".join(sorted(absent)[:10]) + (" ..." if len(absent) > 10 else ""),
            )
```

Place it immediately before `for symbol in self.symbols:`. Reset `self._absence_reported = False` in `start()`, beside `self._last_seen.clear()`.

- [ ] **Step 5: Run the tests and confirm all six pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_absent_symbol_reporting.py -v
```

- [ ] **Step 6: Run the FULL suite and the three static checks**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 7: Commit**

```bash
git add tests/data/test_absent_symbol_reporting.py src/qat/data/market_data.py
```

```bash
git commit -m "M158: the rail now says which symbols it cannot see"
```

---

### Task 3: Wire it, and prove the wiring

⚠️ **ORDERING PROBLEM, found while planning — read this before editing.** `runtime.py` builds `AutonomyGate` at **line 639** and `MarketDataFeed` at **line 691**. The gate is constructed *before* the feed exists, so the source cannot be passed as a constructor argument.

**Assign it after the feed is built.** Do not reorder the constructions — `autonomous_executor` at line 640 takes the gate immediately, and moving either risks a dependency nobody checked. Do not use a closure over a not-yet-assigned name either; it works by late binding and reads like a bug.

**Files:**
- Modify: `src/qat/presentation/runtime.py` — after the `MarketDataFeed(...)` assignment
- Modify: `tests/domain/autonomy/test_absent_price_refusal.py` — add the wiring test

- [ ] **Step 1: Write the failing wiring test**

Append to `tests/domain/autonomy/test_absent_price_refusal.py`:

```python
def test_runtime_wires_the_gate_to_the_feed() -> None:
    """⚠️ A GUARD THAT IS NEVER WIRED IS INERT, which is items 59 and 67 and
    M156 - where reference_price was carried onto the record, persisted, read
    back, and then never reached the lot because one signature was not changed.

    Read from source rather than by building a runtime: constructing one needs a
    broker, a feed and a Gateway. What is pinned is that the assignment EXISTS.
    """
    from pathlib import Path

    import qat

    source = (Path(qat.__file__).parent / "presentation" / "runtime.py").read_text(
        encoding="utf-8"
    )

    assert "autonomy_gate.last_print_source = market_data_feed.last_print_at" in source, (
        "the gate is built before the feed exists, so the source must be ASSIGNED after "
        "the feed is constructed - without it the refusal never fires and every test "
        "above still passes"
    )
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/autonomy/test_absent_price_refusal.py::test_runtime_wires_the_gate_to_the_feed -v
```

Expected: FAIL with the message above.

- [ ] **Step 3: Wire it**

In `src/qat/presentation/runtime.py`, immediately after the `market_data_feed = MarketDataFeed(...)` block closes:

```python
        # Item 33. Assigned rather than passed to the constructor because the
        # gate is built above, before this feed exists, and reordering the two
        # would move `autonomous_executor`'s dependency for no benefit. Without
        # this line the refusal is inert and every unit test still passes -
        # which is why a wiring test pins it.
        autonomy_gate.last_print_source = market_data_feed.last_print_at
```

- [ ] **Step 4: Run the wiring test and the whole gate file**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/autonomy/test_absent_price_refusal.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Prove the wiring test fails when the wiring is removed**

⚠️ **A test never seen to fail is not evidence.** Comment out the assignment, run the wiring test, confirm it fails naming the assignment, then restore it and confirm `git diff` on `runtime.py` is empty.

- [ ] **Step 6: Run the FULL suite and the three static checks**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 7: Commit**

```bash
git add src/qat/presentation/runtime.py tests/domain/autonomy/test_absent_price_refusal.py
```

```bash
git commit -m "M158: wire the gate to the feed, and pin the wiring"
```

---

### Task 4: Record it and bump the milestone

**Files:**
- Modify: `docs/HANDOFF.md` — item 33
- Modify: `src/qat/version.py` — `MILESTONE` at line 1167 and a narrative entry above it

- [ ] **Step 1: Close item 33 in `docs/HANDOFF.md`**

Replace the item's closing paragraphs with what was built, and carry across the two corrections the spec found: the item OVERSTATED the bell hazard (signals are tick-driven, so a symbol with no tick cannot signal) and UNDERSTATED the real one (a periodic pass against a tick-driven signal is a RACE, not a coincidence). Record that `MarketDataFeedEvent` reaches only `main_window.py` and that no entry decision gates on feed health — true, found here, and deliberately left out of scope.

- [ ] **Step 2: Add the M158 entry to `src/qat/version.py` and bump the constant**

```python
MILESTONE = "M158"
```

- [ ] **Step 3: Confirm the milestone reports M158**

```bash
.venv/Scripts/python.exe -c "from qat.version import MILESTONE; print(MILESTONE)"
```

Expected: `M158`.

- [ ] **Step 4: Run the FULL suite and all four checks**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 5: Commit**

```bash
git add docs/HANDOFF.md src/qat/version.py
```

```bash
git commit -m "M158: record item 33, and the two things it had wrong"
```

## Deploy and the watched session

**Needs the operator.** Dry run `scripts\deploy.ps1`, ask, then `-Apply`.

⚠️ **THE READ-BACK IS AT A REAL BELL, and this is the point of the whole item.** Expect, in order:

1. At launch, `_last_seen` is empty, so **every symbol reads absent and every buy is refused** until the feed delivers. **That is correct, not a fault** — it is the assertion working. It should be visible as refusals on the Blotter under "No price this session".
2. As the feed comes up around 10:21, the absence line should fire **once** with a real count, and that count should **fall** as symbols print.
3. By the time the entry gate opens at 10:29, absence refusals should have stopped for symbols that are printing.

⚠️ **If NO absence refusal ever appears, the feature is not working** — at the bell nothing has printed, so refusals are guaranteed if the wiring is live. Silence means inert, which is M151's shape.

⚠️ **And watch for the opposite failure:** absence refusals continuing past ~10:30 on symbols that ARE printing would mean the trading-date comparison is wrong, and would refuse every entry for the session.

## What this does NOT prove

- **That the race was ever hit in production.** It was found by reading, not from a session that lost money to it. The assertion is cheap and the failure it prevents is silent, which is the argument for it.
- **That yfinance is the right price source.** Item 33 calls IBKR the deeper fix; that is separate work.
- **That feed-wide health should gate entries.** `MarketDataFeedEvent` reaching only a display is recorded as a finding and deliberately not acted on here.
