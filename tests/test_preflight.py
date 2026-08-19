"""M103: a pre-flight that refuses to say READY about anything it did not check.

Four live runs on 19 August found four defects a green suite could not: the
capability probe was a rubber stamp, the bracket run found M96, the Task 4
check found M99, and the wiring run found M102. The pattern is not bad luck -
it is that the fakes and the broker disagree, and only one of them is real.

So this exists to spend five read-only minutes before a session rather than
discovering the fifth defect with money-shaped machinery running.

**The one design rule it enforces on itself:** a check that could not be
performed is NOT a check that passed. `UNKNOWN` blocks READY exactly as `FAIL`
does. Task 1's first run was one third of a measurement precisely because an
empty answer from an empty account was read as an answer, and a pre-flight that
reported READY while skipping half its checks would be a worse instance of the
same thing - it would be an alarm that cannot fire.
"""

from __future__ import annotations

from qat.config import Settings
from qat.preflight import Check, Status, Verdict, settings_checks, verdict_for


def _paper(**overrides: object) -> Settings:
    fields: dict[str, object] = {
        "_env_file": None,
        "broker": "ibkr",
        "market": "ASX",
        "trading_mode": "paper",
        "ibkr_port": 4002,
        "market_data_source": "yfinance",
        "execution_mode": "auto",
        "autonomous_strategies": "swing",
    }
    fields.update(overrides)
    return Settings(**fields)


def _named(checks: list[Check], name: str) -> Check:
    matches = [c for c in checks if c.name == name]
    assert matches, f"no check named {name}; got {[c.name for c in checks]}"
    return matches[0]


# --- the verdict rule ------------------------------------------------------


def test_all_clear_is_ready() -> None:
    assert (
        verdict_for([Check("a", Status.OK, "fine"), Check("b", Status.OK, "fine")]) is Verdict.READY
    )


def test_a_single_failure_blocks_ready() -> None:
    assert verdict_for([Check("a", Status.OK, ""), Check("b", Status.FAIL, "")]) is Verdict.BLOCKED


def test_an_unchecked_item_also_blocks_ready() -> None:
    """The rule this file exists to enforce. "Could not check" is not "checked
    and fine", and a pre-flight that green-lights on unperformed checks is an
    alarm that cannot fire."""
    assert (
        verdict_for([Check("a", Status.OK, ""), Check("b", Status.UNKNOWN, "")]) is Verdict.BLOCKED
    )


def test_a_warning_does_not_block() -> None:
    """A warning is a thing to know, not a thing to stop for - otherwise
    everything becomes a warning and nothing is read."""
    assert verdict_for([Check("a", Status.OK, ""), Check("b", Status.WARN, "")]) is Verdict.READY


def test_no_checks_at_all_is_not_ready() -> None:
    """An empty result is the emptiest possible unchecked state."""
    assert verdict_for([]) is Verdict.BLOCKED


# --- configuration, where a silent no-op session is born -------------------


def test_a_sound_paper_configuration_passes() -> None:
    assert verdict_for(settings_checks(_paper())) is Verdict.READY


def test_auto_execution_with_no_promoted_strategies_fails() -> None:
    """The silent no-op. `execution_mode=auto` with an empty
    `autonomous_strategies` runs a whole session, evaluates every signal, and
    executes NOTHING - and looks exactly like a session where the strategy
    found nothing. A trial that cannot trade must not be discovered afterwards
    from an empty ledger."""
    check = _named(settings_checks(_paper(autonomous_strategies="")), "autonomy")

    assert check.status is Status.FAIL
    assert "nothing" in check.detail.lower() or "no strateg" in check.detail.lower()


def test_a_live_port_in_paper_mode_fails() -> None:
    check = _named(settings_checks(_paper(ibkr_port=4001)), "trading mode")

    assert check.status is Status.FAIL


def test_asx_with_a_us_only_data_source_fails() -> None:
    """Alpaca serves US equities only. Configured for ASX it produces nothing,
    and the feed degrades to SYNTHETIC - a session trading invented prices."""
    check = _named(settings_checks(_paper(market_data_source="alpaca")), "market data")

    assert check.status is Status.FAIL


def test_synthetic_data_fails_rather_than_warns() -> None:
    """The one that would corrupt a record rather than stop it. Synthetic bars
    are not degraded data, they are invented, and a trial run on them produces
    expectancy from nothing."""
    check = _named(settings_checks(_paper(market_data_source="synthetic")), "market data")

    assert check.status is Status.FAIL


def test_recommend_only_execution_warns_rather_than_fails() -> None:
    """A legitimate choice - an operator watching and signing off - but worth
    saying out loud, because an unattended test configured this way sits and
    waits for a human who is not there."""
    check = _named(settings_checks(_paper(execution_mode="recommend")), "autonomy")

    assert check.status is Status.WARN


def test_ibkr_against_a_us_watchlist_warns() -> None:
    check = _named(settings_checks(_paper(market="US")), "market")

    assert check.status is Status.WARN


def test_every_check_carries_a_readable_detail() -> None:
    """A status with no explanation is the shape of every defect this project
    found on 11 August - a sentence that predicted or explained, and was wrong.
    An empty one cannot even be wrong."""
    for check in settings_checks(_paper()):
        assert check.detail.strip(), f"{check.name} has no detail"


# --- the live half, and its refusal to guess -------------------------------


class _FakeIB:
    def __init__(self, connected: bool = True, accounts: list[str] | None = None) -> None:
        self._connected = connected
        self._accounts = accounts if accounts is not None else ["DUQ200898"]

    def isConnected(self) -> bool:
        return self._connected

    def managedAccounts(self) -> list[str]:
        return list(self._accounts)


async def test_a_disconnected_gateway_is_unknown_not_failed() -> None:
    """ "Not connected" and "connected and wrong" are different facts. Both
    block, and conflating them would lose which one to go and fix."""
    from qat.preflight import gateway_checks

    checks = await gateway_checks(_paper(), _FakeIB(connected=False))

    assert _named(checks, "gateway").status is Status.UNKNOWN
    assert verdict_for(checks) is Verdict.BLOCKED


async def test_a_live_account_number_fails_loudly() -> None:
    from qat.preflight import gateway_checks

    checks = await gateway_checks(_paper(), _FakeIB(accounts=["U1234567"]))

    assert _named(checks, "account").status is Status.FAIL


async def test_a_paper_account_passes() -> None:
    from qat.preflight import gateway_checks

    checks = await gateway_checks(_paper(), _FakeIB())

    assert _named(checks, "account").status is Status.OK
    assert _named(checks, "gateway").status is Status.OK


async def test_a_held_position_with_no_resting_stop_blocks_the_session() -> None:
    """Starting a session over an unprotected position is how the protection
    question gets answered by a gap rather than by a check."""
    from qat.data.broker.adapter import AccountSummary, Position
    from qat.preflight import book_checks

    class _Broker:
        async def account(self) -> AccountSummary:
            return AccountSummary(net_liquidation=1000.0, cash=1000.0, buying_power=1000.0)

        async def positions(self) -> list[Position]:
            return [Position(symbol="BHP.AX", quantity=10, avg_price=60.0)]

        async def resting_stops(self) -> dict[str, float]:
            return {}

    checks = await book_checks(_Broker())

    assert _named(checks, "book").status is Status.FAIL
    assert "BHP.AX" in _named(checks, "book").detail


async def test_a_broker_that_raises_is_unknown_not_a_pass() -> None:
    from qat.preflight import book_checks

    class _Broken:
        async def account(self) -> object:
            raise RuntimeError("This event loop is already running")

        async def positions(self) -> list[object]:
            raise RuntimeError("nope")

        async def resting_stops(self) -> dict[str, float]:
            raise RuntimeError("nope")

    checks = await book_checks(_Broken())

    assert all(c.status is Status.UNKNOWN for c in checks), [(c.name, c.status) for c in checks]
    assert verdict_for(checks) is Verdict.BLOCKED


async def test_a_symbol_that_does_not_resolve_fails() -> None:
    from qat.preflight import contract_checks

    class _IB:
        async def reqContractDetailsAsync(self, contract: object) -> list[object]:
            return [] if getattr(contract, "symbol", "") == "NOPE" else [object()]

    checks = await contract_checks(["BHP.AX", "NOPE"], "ASX", _IB())

    assert _named(checks, "contracts").status is Status.FAIL
    assert "NOPE" in _named(checks, "contracts").detail


async def test_a_symbol_the_feed_cannot_price_fails() -> None:
    from qat.preflight import feed_checks

    class _Tick:
        def __init__(self, symbol: str, price: float) -> None:
            self.symbol = symbol
            self.price = price

    class _Source:
        async def _poll_once(self, symbols: list[str]) -> list[_Tick]:
            return [_Tick("BHP.AX", 63.7)]

    checks = await feed_checks(["BHP.AX", "CBA.AX"], _Source())

    assert _named(checks, "feed").status is Status.FAIL
    assert "CBA.AX" in _named(checks, "feed").detail


def test_the_report_names_what_blocked_it() -> None:
    """A verdict without its reason is the shape of an alarm nobody can act
    on. The blockers are listed, and the verdict is DERIVED from the checks
    rather than passed in beside them."""
    from qat.preflight import render

    text = render([Check("a", Status.OK, "fine"), Check("b", Status.UNKNOWN, "never asked")])

    assert "BLOCKED" in text
    assert "b (UNKNOWN)" in text
    assert "never asked" in text


def test_the_session_check_can_actually_pass_when_the_market_is_open() -> None:
    """A check that cannot pass is worse than no check, and this one could not.

    It tested `phase == "open"`. `phase` is a WITHIN-session descriptor -
    'Opening Range', 'Midday Lull' - and is None when the market is shut, so
    the comparison was never true and the pre-flight would have reported the
    market closed at midday. `is_open` is the authoritative flag.

    Found by running the pre-flight against the real calendar rather than by
    the tests, which is the same lesson as M99 and M102 arriving in the very
    instrument built to catch it.
    """
    from datetime import UTC, datetime

    from qat.preflight import session_checks

    during = datetime(2026, 8, 19, 2, 0, tzinfo=UTC)  # 12:00 Sydney, mid-session
    checks = session_checks("ASX", during)

    assert _named(checks, "session").status is Status.OK, _named(checks, "session").detail


def test_the_session_check_warns_when_the_market_is_shut() -> None:
    from datetime import UTC, datetime

    from qat.preflight import session_checks

    after = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)  # 19:00 Sydney

    assert _named(session_checks("ASX", after), "session").status is Status.WARN
