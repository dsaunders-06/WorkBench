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

from datetime import date

from qat import preflight
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


def test_the_corporate_action_note_is_derived_not_asserted() -> None:
    """It said "IBKR publishes no corporate-action feed" unconditionally -
    including with broker=alpaca, where announcements ARE implemented and the
    ex-date gate works. A sentence that explains and is wrong, in the
    instrument written to catch those, and its first real run printed it.

    Derived from the capability register instead, which is what the
    application itself consults.
    """
    on_alpaca = settings_checks(_paper(broker="alpaca", market="US", market_data_source="alpaca"))
    names = [c.name for c in on_alpaca]

    assert (
        "corporate actions" not in names
        or _named(on_alpaca, "corporate actions").status is Status.OK
    ), "claimed corporate-action detection is unavailable on a broker that implements it"


def test_the_corporate_action_note_still_fires_on_ibkr() -> None:
    check = _named(settings_checks(_paper()), "corporate actions")

    assert check.status is Status.WARN
    assert "UNAVAILABLE" in check.detail or "no corporate-action feed" in check.detail


# --- M106: two settings each valid, jointly useless ------------------------


def test_a_watchlist_the_allow_list_forbids_entirely_fails() -> None:
    """Caught live on 20 August, by hand, while changing the watchlist.

    `QAT_WATCHLIST_CATEGORY=curated` gave STW/BHP/CBA/CSL while the entry allow
    list permitted RIO/APA/AMC/MGR/SGP/NHF. Each setting is individually valid.
    Together they describe a session that polls four symbols all day and is
    forbidden from trading any of them - and afterwards that is
    indistinguishable from a session where nothing signalled.

    The pre-flight checked the watchlist, and checked the feed, and never
    checked that the two lists intersect.
    """
    settings = _paper(
        watchlist_category="curated",
        watchlist_curated_asx="STW.AX,BHP.AX",
        entry_allow_list="RIO.AX,APA.AX",
    )

    check = _named(settings_checks(settings), "tradable universe")

    assert check.status is Status.FAIL
    assert "allow" in check.detail.lower()


def test_an_allow_list_that_excludes_part_of_the_watchlist_WARNS() -> None:
    """M109. This returned OK until 20 August, and OK was the wrong answer.

    A non-empty overlap only proves SOMETHING can trade. On 20 August three
    permitted names sat inside a 100-symbol watchlist, the overlap was fine,
    and six correct signals were thrown away because the three were the
    previous day's. The check has to say how much of the watchlist it is
    refusing, not just that the number is above zero.
    """
    settings = _paper(
        watchlist_category="curated",
        watchlist_curated_asx="RIO.AX,APA.AX,AMC.AX",
        entry_allow_list="RIO.AX,APA.AX",
    )

    check = _named(settings_checks(settings), "tradable universe")

    assert check.status is Status.WARN
    assert "RIO.AX" in check.detail
    assert "AMC.AX" in check.detail


def test_an_allow_list_covering_the_whole_watchlist_passes() -> None:
    """Restricted to exactly what is watched is a coherent configuration and
    must not nag - otherwise the warning becomes noise and stops being read."""
    settings = _paper(
        watchlist_category="curated",
        watchlist_curated_asx="RIO.AX,APA.AX",
        entry_allow_list="RIO.AX,APA.AX",
    )

    check = _named(settings_checks(settings), "tradable universe")

    assert check.status is Status.OK
    assert "RIO.AX" in check.detail


def test_a_permitted_symbol_that_is_not_watched_is_named() -> None:
    """The dead-setting shape: the allow list still names symbols from a
    watchlist that has since been replaced, so they can never signal."""
    settings = _paper(
        watchlist_category="curated",
        watchlist_curated_asx="RIO.AX,APA.AX",
        entry_allow_list="RIO.AX,APA.AX,BHP.AX",
    )

    check = _named(settings_checks(settings), "tradable universe")

    assert check.status is Status.WARN
    assert "BHP.AX" in check.detail


def test_no_allow_list_means_the_whole_watchlist_is_tradable() -> None:
    """None and empty mean opposite things - no restriction, not "nothing
    permitted" - and the check must not read the first as the second."""
    settings = _paper(watchlist_category="curated", watchlist_curated_asx="RIO.AX,APA.AX")

    check = _named(settings_checks(settings), "tradable universe")

    assert check.status is Status.OK


async def test_a_source_failing_on_every_symbol_is_named_as_a_SOURCE_failure() -> None:
    """20 August: yfinance answered "possibly delisted" for all 101 ASX symbols
    at once, including megacaps that had priced minutes earlier. That is a rate
    limit or an outage, not 101 delistings, and saying "no price for BHP.AX,
    CBA.AX, ..." sends the operator to check the symbols instead of the source.
    """
    from qat.preflight import feed_checks

    class _Dead:
        async def _poll_once(self, symbols: list[str]) -> list[object]:
            return []

    check = (await feed_checks(["RIO.AX", "APA.AX", "AMC.AX"], _Dead()))[0]

    assert check.status is Status.FAIL
    assert "source" in check.detail.lower()
    # The behaviour, not the wording: it must NOT enumerate the symbols, which
    # is what sends an operator to check a hundred tickers one at a time.
    assert "RIO.AX" not in check.detail
    assert "APA.AX" not in check.detail


async def test_some_symbols_missing_still_names_them() -> None:
    """A partial failure IS about those symbols, and keeps the old wording."""
    from qat.preflight import feed_checks

    class _Tick:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol
            self.price = 10.0

    class _Partial:
        async def _poll_once(self, symbols: list[str]) -> list[_Tick]:
            return [_Tick("RIO.AX")]

    check = (await feed_checks(["RIO.AX", "APA.AX"], _Partial()))[0]

    assert check.status is Status.FAIL
    assert "APA.AX" in check.detail


# --- Session hours against the broker (Stage 3) -------------------------------

_TRADING = "20260824:0959-20260824:1611;20260825:0959-20260825:1611;20260822:CLOSED"
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


def _ib_hours_for(day: date, close: str = "1600", tail_close: str = "1611") -> tuple[str, str]:
    stamp = day.strftime("%Y%m%d")
    return (
        f"{stamp}:0959-{stamp}:{tail_close}",
        f"{stamp}:0959-{stamp}:{close}",
    )


class _Details:
    """Shaped like the ib_async ContractDetails the wiring reads by getattr."""

    def __init__(self, trading: str, liquid: str) -> None:
        self.tradingHours = trading  # noqa: N803
        self.liquidHours = liquid  # noqa: N803
        self.timeZoneId = "Australia/NSW"  # noqa: N803


async def _checks_for(details: _Details) -> list[Check]:
    from qat.preflight import contract_checks

    class _IB:
        async def reqContractDetailsAsync(self, contract: object) -> list[object]:
            return [details]

    return await contract_checks(["BHP.AX"], "ASX", _IB())


async def test_contract_checks_asks_the_broker_about_session_hours() -> None:
    """The comparison is worth nothing unless something calls it. The only
    pre-existing contract_checks test takes the FAIL path, which returns before
    this code, so without this the wiring could be deleted and stay green."""
    from qat.domain.market_calendar import trading_date

    trading, liquid = _ib_hours_for(trading_date("ASX"))

    checks = await _checks_for(_Details(trading, liquid))

    hours = [c for c in checks if c.name == "session hours"]
    assert hours, [(c.name, c.status) for c in checks]
    assert hours[0].status is Status.OK
    assert _named(checks, "contracts").status is Status.OK


async def test_contract_checks_surfaces_a_session_hours_disagreement() -> None:
    """And it carries the comparison's verdict rather than a fixed line - the
    same fixture, one boundary moved, has to come back WARN quoting it."""
    from qat.domain.market_calendar import trading_date

    trading, liquid = _ib_hours_for(trading_date("ASX"), close="1530")

    checks = await _checks_for(_Details(trading, liquid))

    hours = [c for c in checks if c.name == "session hours"]
    assert any(c.status is Status.WARN and "15:30" in c.detail for c in hours), [
        (c.status, c.detail) for c in hours
    ]


async def test_the_feed_check_reads_the_yfinance_signature() -> None:
    """Found on 10 September by RUNNING the pre-flight, not by this suite.

    `feed_checks` was written against `AlpacaSource._poll_once`, which returns
    a bare `list[RawTick]`. `YFinanceSource._poll_once` returns
    `(list[RawTick], set[str])`, and yfinance is what `QAT_MARKET_DATA_SOURCE`
    selects. Iterating the 2-tuple bound `t` to the inner LIST, so `t.price`
    raised AttributeError - one line below the `except` that would have caught
    it - and killed the whole script before the broker half ran.

    Every other fake in this file returns the Alpaca shape, so the suite agreed
    with the code and the code disagreed with the only source in use.
    """
    from qat.preflight import feed_checks

    class _Tick:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol
            self.price = 10.0

    class _YFinanceShaped:
        async def _poll_once(self, symbols: list[str]) -> tuple[list[_Tick], set[str]]:
            return [_Tick(s) for s in symbols], set()

    check = (await feed_checks(["RIO.AX", "APA.AX"], _YFinanceShaped()))[0]

    assert check.status is Status.OK, check.detail


async def test_the_feed_check_names_a_missing_symbol_on_the_yfinance_signature() -> None:
    """And it still reaches the real verdict through the tuple, rather than
    merely not raising."""
    from qat.preflight import feed_checks

    class _Tick:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol
            self.price = 10.0

    class _YFinancePartial:
        async def _poll_once(self, symbols: list[str]) -> tuple[list[_Tick], set[str]]:
            return [_Tick("RIO.AX")], {"APA.AX"}

    check = (await feed_checks(["RIO.AX", "APA.AX"], _YFinancePartial()))[0]

    assert check.status is Status.FAIL
    assert "APA.AX" in check.detail
