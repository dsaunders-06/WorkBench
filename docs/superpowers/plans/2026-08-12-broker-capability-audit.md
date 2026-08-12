# W1.0 Broker Capability Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an adapter's missing broker capabilities a derived, reported fact instead of a silence, and stop `broker=ibkr` resolving to a simulator.

**Architecture:** A new `capabilities` module derives the method list from the `BrokerAdapter` Protocol itself and classifies each method as core or optional, where every optional carries a sentence naming the machinery its absence disables. A test fails if a method is added to the Protocol and classified nowhere — the M80 register pattern applied to the broker port. A script prints the matrix on demand, the way `handoff_state.py` derives the deploy gap. The resolver stops substituting `MockBroker` for a configured `ibkr`.

**Tech Stack:** Python 3.12, `inspect`, pytest, black, ruff, mypy, bandit.

## Global Constraints

- **The validation freeze applies.** Nothing here changes which trades happen or how large they are. A new module, tests, a script, and a raise on a configuration branch that is currently unreachable — `broker` defaults to `mock` and nothing in the live config sets `ibkr`.
- **Formats with `black`, not `ruff format`.** `invoke lint` shells out to a ruff that is not on PATH. Run the four through the venv python.
- **Every test that builds an OMS must pass its own `data_dir`.** No test here builds one; do not introduce one.
- Windows/PowerShell 5.1 operator terminal: `;` not `&&`.
- The venv python is `.\.venv\Scripts\python.exe`.

## Why this exists, in one paragraph

`BrokerAdapter` marks most of its surface optional and documents a fallback for
each — *"Adapters that cannot answer return an empty tuple, which reads as
'unknown' rather than 'none'"* — and every caller guards with
`getattr(self.broker, "resting_stops", None)`. That is deliberate and correct:
nothing crashes, nothing corrupts. It is also why the absence is invisible. On
an adapter without them, M31b's protection verification, M34/M48's fill
absorption and M39's corporate-action detection simply stop happening, with no
error and no log line, and 1,964 passing tests say nothing about it.

**Measured 12 August**, by introspection rather than by reading:

| Adapter | Missing |
|---|---|
| `AlpacaAdapter` | none of 12 |
| `MockBroker` | none of 12 |
| **`IBAdapter`** | **`announcements`, `recent_fills`, `resting_stop_orders`, `resting_stops`** |

## File Structure

- **Create `src/qat/data/broker/capabilities.py`** — the derivation and the
  classification. One responsibility: answer "what can this adapter do, and
  what stops working where it cannot". No I/O, no formatting.
- **Create `tests/data/broker/test_capabilities.py`** — that the classification
  is complete, and that no known adapter is missing a core capability.
- **Create `tests/presentation/test_resolve_broker.py`** — that a configured
  broker never silently becomes a different one.
- **Modify `src/qat/presentation/runtime.py:229-234`** — the `ibkr` branch.
- **Create `scripts/broker_capabilities.py`** — prints the matrix. Reporting
  only, no imports from it into `src/`.

---

### Task 1: The capability derivation

**Files:**
- Create: `src/qat/data/broker/capabilities.py`
- Test: `tests/data/broker/test_capabilities.py`

**Interfaces:**
- Consumes: `qat.data.broker.adapter.BrokerAdapter` (existing Protocol, 12 public methods).
- Produces:
  - `CORE: frozenset[str]`
  - `OPTIONAL: dict[str, str]` — method name → what is lost without it
  - `protocol_methods() -> frozenset[str]`
  - `unclassified() -> frozenset[str]`
  - `AdapterCapabilities` frozen dataclass with fields `adapter: str`,
    `implemented: frozenset[str]`, `missing_core: frozenset[str]`,
    `missing_optional: frozenset[str]`; properties `disabled -> tuple[str, ...]`
    and `can_trade -> bool`
  - `inspect_adapter(adapter: type) -> AdapterCapabilities`
  - `KNOWN_ADAPTERS() -> dict[str, type]`

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_capabilities.py`:

```python
"""The broker port's capabilities, asserted as properties rather than counts.

Deliberately no "IBAdapter is missing exactly four" assertion. This project
lost that argument four times in three days with hand-maintained counts; the
count belongs in the script's output, where it is derived every time it is
read. What is asserted here is what must stay TRUE as the count changes.
"""

from __future__ import annotations

import pytest

from qat.data.broker.capabilities import (
    CORE,
    OPTIONAL,
    KNOWN_ADAPTERS,
    inspect_adapter,
    protocol_methods,
    unclassified,
)


def test_every_protocol_method_is_classified() -> None:
    """A method added to BrokerAdapter and classified nowhere is a capability
    nobody audited. M80's register pattern: the test is the thing that stops
    the register drifting from what it registers."""
    assert unclassified() == frozenset(), (
        "these BrokerAdapter methods are neither CORE nor OPTIONAL, so nothing "
        f"says what breaks without them: {sorted(unclassified())}"
    )


def test_classification_covers_nothing_that_is_not_on_the_protocol() -> None:
    stale = (CORE | frozenset(OPTIONAL)) - protocol_methods()
    assert stale == frozenset(), f"classified but no longer on the Protocol: {sorted(stale)}"


@pytest.mark.parametrize("method", sorted(OPTIONAL))
def test_every_optional_capability_names_what_is_lost(method: str) -> None:
    """An optional capability whose absence is not described is exactly the
    silence this module exists to end."""
    consequence = OPTIONAL[method]
    assert consequence.strip(), f"{method} has no stated consequence"
    assert len(consequence) > 30, f"{method}'s consequence is too vague to act on: {consequence!r}"


@pytest.mark.parametrize("name", sorted(KNOWN_ADAPTERS()))
def test_no_known_adapter_is_missing_a_core_capability(name: str) -> None:
    """Core is the trading path itself. An adapter missing any of it cannot be
    a broker, and must never be resolvable as one."""
    caps = inspect_adapter(KNOWN_ADAPTERS()[name])
    assert caps.missing_core == frozenset(), f"{name} cannot trade: missing {sorted(caps.missing_core)}"
    assert caps.can_trade


def test_a_missing_optional_reports_its_consequence() -> None:
    """The whole point: absence must produce a sentence, not a silence."""
    caps = inspect_adapter(KNOWN_ADAPTERS()["ibkr"])
    if not caps.missing_optional:
        pytest.skip("IBAdapter now implements the whole protocol - the gap this guards is closed")
    assert len(caps.disabled) == len(caps.missing_optional)
    assert all(sentence.strip() for sentence in caps.disabled)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_capabilities.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'qat.data.broker.capabilities'`.

- [ ] **Step 3: Write the module**

Create `src/qat/data/broker/capabilities.py`:

```python
"""What each broker adapter can actually do, derived rather than listed.

`BrokerAdapter` marks most of its surface optional and documents a fallback for
each - "Adapters that cannot answer return an empty tuple, which reads as
'unknown' rather than 'none'" - and every caller guards with `getattr`. Nothing
crashes and nothing corrupts on an adapter that lacks them.

That is exactly why the absence is invisible. Without `resting_stops` the app
stops verifying its own belief about what protects the book; without
`recent_fills` a protective order firing is never absorbed as a closed trade;
without `announcements` a split on a held position is not seen before the
ex-date open. None of it errors. None of it logs. A full suite passes.

The method list is derived from the Protocol so that a method added there and
classified nowhere fails a test rather than going unaudited - M80's register
pattern, pointed at the broker port. Nothing here reads configuration, touches
a network, or instantiates an adapter: it inspects classes.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from qat.data.broker.adapter import BrokerAdapter

CORE: frozenset[str] = frozenset(
    {
        "account",
        "cancel_order",
        "get_historical",
        "get_market_data",
        "modify_order",
        "place_order",
        "positions",
    }
)
"""Without any one of these there is no trading path at all - no price, no
order, no position, no balance. An adapter missing one is not a degraded
broker, it is not a broker, and `resolve_broker` refuses it."""

OPTIONAL: dict[str, str] = {
    "balances": (
        "M21's richer balance display falls back to the three core figures from "
        "the account summary - a display degradation, and the only harmless one here"
    ),
    "recent_fills": (
        "M34/M48 broker-side fill absorption stops: a protective order firing at "
        "the broker is never recorded as a closed trade, so the ledger silently "
        "misses exits the app did not itself transmit"
    ),
    "resting_stops": (
        "M31b protection verification stops: the app can no longer check its own "
        "belief about what rests at the broker, and a stop that was cancelled or "
        "never placed reads exactly like one that is working"
    ),
    "resting_stop_orders": (
        "M39 cannot re-price a resting stop through a corporate action, because "
        "it has no order id to call modify_order on - the MNST failure, unrepaired"
    ),
    "announcements": (
        "M39 corporate-action detection stops: a split on a held position is not "
        "seen before the ex-date open, and an unadjusted stop through a split "
        "cost this account $375.23 on 11 August"
    ),
}
"""Optional by the Protocol's own design - and each entry says what stops
happening when an adapter does not implement it. A new optional method with no
consequence sentence fails `test_every_optional_capability_names_what_is_lost`,
because an absence nobody described is the silence this module exists to end."""


def protocol_methods() -> frozenset[str]:
    """The public method names on BrokerAdapter, from the Protocol itself.

    Derived rather than listed, so this cannot drift from the port it audits.
    """
    return frozenset(
        name
        for name, _ in inspect.getmembers(BrokerAdapter, inspect.isfunction)
        if not name.startswith("_")
    )


def unclassified() -> frozenset[str]:
    """Protocol methods that are neither CORE nor OPTIONAL - i.e. unaudited."""
    return protocol_methods() - CORE - frozenset(OPTIONAL)


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    adapter: str
    implemented: frozenset[str]
    missing_core: frozenset[str]
    missing_optional: frozenset[str]

    @property
    def disabled(self) -> tuple[str, ...]:
        """What stops working on this adapter, in the words of OPTIONAL."""
        return tuple(OPTIONAL[name] for name in sorted(self.missing_optional))

    @property
    def can_trade(self) -> bool:
        return not self.missing_core


def inspect_adapter(adapter: type) -> AdapterCapabilities:
    """Classify one adapter CLASS against the Protocol. Never instantiates it -
    IBAdapter's constructor alone can raise, and an audit must not need a
    broker session to run."""
    methods = protocol_methods()
    implemented = frozenset(name for name in methods if hasattr(adapter, name))
    absent = methods - implemented
    return AdapterCapabilities(
        adapter=adapter.__name__,
        implemented=implemented,
        missing_core=absent & CORE,
        missing_optional=absent & frozenset(OPTIONAL),
    )


def KNOWN_ADAPTERS() -> dict[str, type]:  # noqa: N802 - a registry, named as one
    """Every adapter that can be resolved as a broker, keyed by its config value.

    A function rather than a module constant because importing IBAdapter pulls
    in ib_async, and an import-time failure in a reporting module would take
    the application down with it.
    """
    from qat.data.broker.alpaca_adapter import AlpacaAdapter
    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.mock_broker import MockBroker

    return {"alpaca": AlpacaAdapter, "ibkr": IBAdapter, "mock": MockBroker}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_capabilities.py -v
```

Expected: PASS. `test_a_missing_optional_reports_its_consequence` must NOT skip
today — `IBAdapter` lacks four optional methods as of 12 August. A skip here
means either the adapter changed or `inspect_adapter` is looking in the wrong
place; investigate before continuing.

- [ ] **Step 5: Lint, format and type-check**

```bash
.venv/Scripts/python.exe -m black src/qat/data/broker/capabilities.py tests/data/broker/test_capabilities.py
```

```bash
.venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m mypy src ; .venv/Scripts/python.exe -m bandit -r src -q
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/broker/capabilities.py tests/data/broker/test_capabilities.py
```

```bash
git commit -m "Derive what each broker adapter cannot do, and what that costs"
```

---

### Task 2: The resolver stops substituting a simulator

**Files:**
- Modify: `src/qat/presentation/runtime.py:229-234` (the `ibkr` branch of `resolve_broker`)
- Test: `tests/presentation/test_resolve_broker.py`

**Interfaces:**
- Consumes: `AdapterCapabilities`, `inspect_adapter`, `KNOWN_ADAPTERS` from Task 1.
- Produces: `qat.presentation.runtime.BrokerNotAvailableError`.

**Context the implementer needs.** `resolve_broker`'s docstring already states
the principle: *"quietly paper-trading against a simulator while believing you
are connected to a real account would be worse than either."* The `alpaca`
branch honours it — it degrades to `MockBroker` only after a real construction
attempt failed, and says so. The `ibkr` branch does not: it logs a warning and
returns `MockBroker(seed=1)` **without trying anything**, so a configured
destination broker becomes seeded fabricated data. Inert today, because nothing
sets `ibkr`. Lethal on the morning it does.

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/test_resolve_broker.py`:

```python
"""A configured broker must never silently become a different one.

resolve_broker's own docstring says quietly trading against a simulator while
believing you are connected to a real account "would be worse than either" -
and until this test, the ibkr branch did exactly that.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.presentation.runtime import BrokerNotAvailableError, resolve_broker


def test_mock_is_returned_when_mock_is_configured() -> None:
    assert isinstance(resolve_broker(Settings(broker="mock")), MockBroker)


def test_ibkr_does_not_silently_resolve_to_a_mock() -> None:
    with pytest.raises(BrokerNotAvailableError):
        resolve_broker(Settings(broker="ibkr"))


def test_the_refusal_names_the_capabilities_ibkr_lacks() -> None:
    """Test the claim, not the arithmetic. The message asserts something about
    the adapter; if it stops being true the message must stop saying it."""
    with pytest.raises(BrokerNotAvailableError) as raised:
        resolve_broker(Settings(broker="ibkr"))
    message = str(raised.value)
    assert "resting_stops" in message
    assert "Gateway" in message
    assert "MockBroker" in message
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_resolve_broker.py -v
```

Expected: collection error — `ImportError: cannot import name 'BrokerNotAvailableError'`.

- [ ] **Step 3: Add the exception**

In `src/qat/presentation/runtime.py`, directly above `def resolve_broker`:

```python
class BrokerNotAvailableError(RuntimeError):
    """A broker was configured that cannot be built, where substituting a
    different one would be worse than not starting.

    Deliberately NOT raised for the alpaca path: a missing key there is a
    configuration problem and degrading to MockBroker with a warning keeps the
    operator in the application (spec M12). It IS raised for a broker that was
    never wired at all, because the fallback is indistinguishable from success.
    """
```

- [ ] **Step 4: Replace the `ibkr` branch**

Replace lines 229-234 of `src/qat/presentation/runtime.py` — the whole
`if settings.broker == "ibkr":` block, which currently warns and returns
`MockBroker(seed=1)` — with:

```python
    if settings.broker == "ibkr":
        from qat.data.broker.capabilities import KNOWN_ADAPTERS, inspect_adapter

        absent = sorted(inspect_adapter(KNOWN_ADAPTERS()["ibkr"]).missing_optional)
        raise BrokerNotAvailableError(
            "broker=ibkr is configured, but IBAdapter is not auto-wired here: it needs a "
            "running Gateway/TWS session, and it does not implement "
            f"{', '.join(absent) if absent else 'the full protocol yet'}. "
            "Returning MockBroker would mean trading against a simulator while believing "
            "the destination broker was connected. Set broker=mock deliberately if that is "
            "what you want."
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/presentation/test_resolve_broker.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the whole suite — this touches a startup path**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: no new failures against the 1,964 baseline. If anything fails, the
likely cause is a test constructing `Settings(broker="ibkr")` and expecting a
broker back; that expectation is the defect, and the test should be updated to
expect the refusal.

- [ ] **Step 7: Lint, format and type-check**

```bash
.venv/Scripts/python.exe -m black src/qat/presentation/runtime.py tests/presentation/test_resolve_broker.py
```

```bash
.venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m mypy src ; .venv/Scripts/python.exe -m bandit -r src -q
```

- [ ] **Step 8: Commit**

```bash
git add src/qat/presentation/runtime.py tests/presentation/test_resolve_broker.py
```

```bash
git commit -m "Refuse broker=ibkr rather than quietly substituting a simulator"
```

---

### Task 3: The matrix, printed on demand

**Files:**
- Create: `scripts/broker_capabilities.py`

**Interfaces:**
- Consumes: `CORE`, `OPTIONAL`, `KNOWN_ADAPTERS`, `inspect_adapter`,
  `protocol_methods`, `unclassified` from Task 1.
- Produces: a console report. Nothing in `src/` imports this.

**Why a script and not a document.** The count in a document rots — this project
quoted the deploy gap as five, eight, nine and twelve, and held a test count at
1,690 across three paragraphs while the suite moved on. `handoff_state.py` is
the answer that worked: derive it at the moment it is read. This is the same
answer for the broker port, and it is the checklist W1.1 measures IBKR against.

- [ ] **Step 1: Write the script**

Create `scripts/broker_capabilities.py`:

```python
"""What each broker adapter implements, and what its gaps cost - derived now.

    .\\.venv\\Scripts\\python.exe scripts/broker_capabilities.py

Reporting only. Instantiates nothing, connects to nothing, and reads no
configuration - it inspects classes, so it is safe to run at any time.

This is the checklist the IBKR spike (W1.0 -> W1.1) measures against: every
name in the "not implemented" list is a question to put to a live Gateway
before the ASX cost can be estimated.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.data.broker.capabilities import (  # noqa: E402
    CORE,
    OPTIONAL,
    KNOWN_ADAPTERS,
    inspect_adapter,
    protocol_methods,
    unclassified,
)


def main() -> int:
    methods = sorted(protocol_methods())
    adapters = KNOWN_ADAPTERS()

    print("BrokerAdapter")
    print(f"  methods         {len(methods)}  ({len(CORE)} core, {len(OPTIONAL)} optional)")
    stray = sorted(unclassified())
    print(f"  unclassified    {len(stray)}{'  ' + ', '.join(stray) if stray else ''}")
    print()

    width = max(len(name) for name in methods) + 2
    header = "".join(f"{name:<10}" for name in adapters)
    print(f"  {'method':<{width}}{header}")
    for method in methods:
        kind = "core" if method in CORE else "opt"
        row = ""
        for adapter in adapters.values():
            row += f"{'yes' if hasattr(adapter, method) else 'NO':<10}"
        print(f"  {method + ' (' + kind + ')':<{width}}{row}")
    print()

    for key, adapter in adapters.items():
        caps = inspect_adapter(adapter)
        if caps.can_trade and not caps.missing_optional:
            print(f"{caps.adapter} ({key}) - implements the whole protocol")
            continue
        print(f"{caps.adapter} ({key})")
        if caps.missing_core:
            print(f"  CANNOT TRADE - missing core: {', '.join(sorted(caps.missing_core))}")
        for name in sorted(caps.missing_optional):
            print(f"  no {name}:")
            print(f"    {OPTIONAL[name]}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it and read the output**

```bash
.venv/Scripts/python.exe scripts/broker_capabilities.py
```

Expected, as of 12 August 2026: 12 methods, 0 unclassified, `AlpacaAdapter` and
`MockBroker` implementing the whole protocol, and `IBAdapter` reporting `NO` for
`announcements`, `recent_fills`, `resting_stop_orders` and `resting_stops`, each
with its consequence printed beneath it.

**Read the consequences before continuing.** If any of them does not describe
something you would actually care about losing on the ASX, the classification in
Task 1 is wrong and this is the moment it is cheapest to fix.

- [ ] **Step 3: Lint and format**

```bash
.venv/Scripts/python.exe -m black scripts/broker_capabilities.py ; .venv/Scripts/python.exe -m ruff check .
```

- [ ] **Step 4: Commit**

```bash
git add scripts/broker_capabilities.py
```

```bash
git commit -m "Print the broker capability matrix rather than recording it"
```

---

### Task 4: Point the spec at the derivation

**Files:**
- Modify: `docs/superpowers/specs/2026-08-12-asx-transferable-validation-design.md` (the W1.0 section)

**Interfaces:**
- Consumes: the script from Task 3.
- Produces: nothing code-facing.

**Why this is a task and not an afterthought.** The spec currently states the
four missing methods as prose. Prose is what goes stale. The spec should name
the command instead, so a reader in September gets September's answer.

- [ ] **Step 1: Replace the capability-matrix bullet in the W1.0 section**

Find the bullet reading:

```markdown
* a **capability matrix** — every adapter (Alpaca, IB, Mock, and the Simulated
  one W2 adds) against every `BrokerAdapter` method;
```

Replace it with:

```markdown
* a **capability matrix**, derived on demand rather than recorded —
  `scripts/broker_capabilities.py` prints every adapter against every
  `BrokerAdapter` method, and prints what each gap costs. **Run it rather than
  quoting the figure below**, which is true on 12 August and has no way of
  staying true;
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-08-12-asx-transferable-validation-design.md
```

```bash
git commit -m "Point W1.0 at the derivation instead of a prose count"
```

---

## Verification, end to end

- [ ] **Full suite passes**

```bash
.venv/Scripts/python.exe -m pytest -q
```

- [ ] **All four quality gates clean**

```bash
.venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m black --check . ; .venv/Scripts/python.exe -m mypy src ; .venv/Scripts/python.exe -m bandit -r src -q
```

- [ ] **The audit runs and its output is read, not skimmed**

```bash
.venv/Scripts/python.exe scripts/broker_capabilities.py
```

- [ ] **The application still starts on the live configuration.** `broker` is
      `alpaca` there, so Task 2 cannot reach it — but this plan touched a
      startup path, and this project's own record is that a hash proves the
      right bytes landed and never that they run. Launch it before the next
      deploy is even considered.

## Deliberately not in this plan

- **Wiring `IBAdapter` into `resolve_broker`.** It needs a running Gateway and
  a decision about supervision; that is W1.1, after the account exists.
- **Implementing any of the four missing methods.** Their cost cannot be
  estimated until IBKR has been measured, which is the entire point of W1.1.
- **Touching the `alpaca` branch's degrade-to-mock behaviour.** It attempts a
  real construction first and warns on failure, which is a different thing from
  what the `ibkr` branch was doing, and it is the live path.
