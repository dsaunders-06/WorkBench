"""The regime matrix, on a screen at last.

Every piece of the 8 September spec was unit-tested and none of it had ever
run: the spec's own progress note ended *"NOT YET WIRED TO A SCREEN. Nothing
calls `build_macro_matrix_prompt` yet, so none of this has run against a live
model."* These tests cover the wiring - what is fetched, what is computed
before the model is asked, and what is rendered when a piece is missing.

⚠️ ADVISORY, and asserted rather than assumed. Operator instruction, 8
September 2026: *"This sits outside of the authority of autonomy, resultant
action must be human driven only for now."* The panel computes an exposure
target and nothing reads it but a person.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.macro_fred import MacroObservation
from qat.domain.ai_advisory.schema import MacroMatrixNarrative
from qat.domain.events import RegimeEvent
from qat.domain.macro_analysis.matrix import MatrixRefusal, RegimeDecision
from qat.presentation.regime_monitor import RegimeMonitorScreen
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel

_SERIES = "CFNAIMA3"


class _Bars:
    """Enough benchmark history for a baseline volatility to exist.

    ⚠️ 300 rows, not 120. `MIN_BARS_FOR_BASELINE_VOL` is 273 because the
    baseline window EXCLUDES the realised one, and a shorter fixture would make
    every test below pass through the refusal branch - green, and testing
    nothing about a decision.
    """

    def __init__(self, n: int = 300) -> None:
        self.n = n

    async def get_daily_bars(self, symbol: str, n_bars: int = 300) -> pd.DataFrame:
        closes = [100.0 * (1.0004**i) for i in range(self.n)]
        return pd.DataFrame({"close": closes})


class _Growth:
    """A CFNAI-MA3 history that reads as strong and accelerating."""

    def __init__(self, values: list[float] | None = None) -> None:
        self.values = values or [0.10, 0.18, 0.31]
        self.asked: list[str] = []

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        self.asked.append(series_id)
        now = datetime.now(UTC)
        return [
            MacroObservation(
                series=series_id,
                ts=now - timedelta(days=30 * (len(self.values) - 1 - i)),
                value=value,
            )
            for i, value in enumerate(self.values)
        ]


class _RaisingGrowth:
    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        raise RuntimeError("FRED is unreachable")


class _Position:
    def __init__(self, symbol: str, quantity: float) -> None:
        self.symbol = symbol
        self.quantity = quantity


class _Snapshot:
    def __init__(self, positions: list[_Position]) -> None:
        self.positions = positions


class _Poller:
    def __init__(self, positions: list[_Position] | None = None, fail: bool = False) -> None:
        self._positions = positions or []
        self._fail = fail

    async def snapshot(self) -> _Snapshot:
        if self._fail:
            raise RuntimeError("the broker is down")
        return _Snapshot(self._positions)


class _AIService:
    def __init__(self, narrative: MacroMatrixNarrative | None = None, fail: bool = False) -> None:
        self.narrative = narrative
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def get_macro_matrix_narrative(self, decision, *, positions=None, friction=None):
        self.calls.append({"decision": decision, "positions": positions, "friction": friction})
        if self.fail:
            raise RuntimeError("the model timed out")
        assert self.narrative is not None
        return self.narrative


def _narrative(**overrides) -> MacroMatrixNarrative:
    payload = {
        "regime": "bull",
        "condition": "Realised volatility sits well below its baseline.",
        "action": "Lift exposure toward the target.",
        "justification": "A calm, growing tape rewards being invested.",
        "change_pct": 3.2,
        "target_pct": 86.5,
        "caveats": [],
    }
    payload.update(overrides)
    return MacroMatrixNarrative.model_validate(payload)


def _screen(qtbot, tmp_path, *, growth=None, poller=None, ai=None, series=_SERIES):
    runtime = Runtime.build_demo(
        settings=Settings(
            _env_file=None,
            data_dir=str(tmp_path),
            ui_level=UiLevel.PROFESSIONAL.label.lower(),
            deployed_strategies="swing",
            macro_growth_series=series,
        )
    )
    runtime.history_source = _Bars()
    runtime.macro_source = growth if growth is not None else _Growth()
    runtime.account_poller = poller if poller is not None else _Poller()
    runtime.ai_service = ai if ai is not None else _AIService(_narrative())
    screen = RegimeMonitorScreen(runtime)
    qtbot.addWidget(screen)
    return screen


@pytest.mark.asyncio
async def test_a_complete_reading_renders_the_regime_and_the_target(qtbot, tmp_path) -> None:
    screen = _screen(qtbot, tmp_path)

    await screen._analyse_matrix()

    text = screen.matrix_decision_label.text()
    assert "Bull Market" in text
    assert "Baseline (BM) 83.3%" in text, "the baseline was not derived from the risk budget"
    assert "scaling unit (SB) 0.20" in text
    assert "target" in text


@pytest.mark.asyncio
async def test_the_growth_series_the_operator_configured_is_the_one_fetched(
    qtbot, tmp_path
) -> None:
    """⚠️ Not a hardcoded series. The whole 8 September decision was WHICH
    series to read, and a panel that ignored the setting would have made that
    decision meaningless."""
    growth = _Growth()
    screen = _screen(qtbot, tmp_path, growth=growth)

    await screen._analyse_matrix()

    assert growth.asked == [_SERIES]


@pytest.mark.asyncio
async def test_an_unfetchable_growth_series_refuses_rather_than_reads_a_regime(
    qtbot, tmp_path
) -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. All seven regimes key on growth. A
    matrix that answered anyway would be describing a market it had not
    measured, and "we cannot tell" is not "sideways"."""
    screen = _screen(qtbot, tmp_path, growth=_RaisingGrowth())

    await screen._analyse_matrix()

    text = screen.matrix_decision_label.text()
    assert "NO REGIME" in text
    assert "growth" in text
    assert "%" not in text, "a refusal put an exposure percentage on screen"


@pytest.mark.asyncio
async def test_an_unconfigured_series_also_refuses(qtbot, tmp_path) -> None:
    screen = _screen(qtbot, tmp_path, series="")

    await screen._analyse_matrix()

    assert "NO REGIME" in screen.matrix_decision_label.text()


@pytest.mark.asyncio
async def test_the_computed_reading_survives_a_model_that_fails(qtbot, tmp_path) -> None:
    """⚠️ The deterministic half is the half with authority, and it is rendered
    BEFORE the model is awaited. A model timeout must not take the arithmetic
    off the screen with it."""
    screen = _screen(qtbot, tmp_path, ai=_AIService(fail=True))

    await screen._analyse_matrix()

    assert "Bull Market" in screen.matrix_decision_label.text()
    assert "unavailable" in screen.matrix_ai_output.toPlainText()


@pytest.mark.asyncio
async def test_the_rendered_figures_come_from_the_decision_not_the_reply(qtbot, tmp_path) -> None:
    """⚠️ The service corrects a model that returned different numbers. Reading
    the reply's figures here would undo that correction one layer later."""
    ai = _AIService(_narrative(change_pct=99.0, target_pct=12.0))
    screen = _screen(qtbot, tmp_path, ai=ai)

    await screen._analyse_matrix()

    rendered = screen.matrix_ai_output.toPlainText()
    assert "99.0" not in rendered
    assert "12.0%" not in rendered
    decision = ai.calls[0]["decision"]
    assert isinstance(decision, RegimeDecision)
    assert f"{decision.target_weight:.1%}" in rendered


@pytest.mark.asyncio
async def test_a_failed_account_read_is_not_reported_as_a_flat_book(qtbot, tmp_path) -> None:
    """⚠️ `None` IS NOT `{}`. An empty dict means "measured, and flat", and the
    prompt writes advice for a flat account from it. `advisory_account.py`
    records the day that substitution put "given no current positions" in front
    of an operator who held three."""
    ai = _AIService(_narrative())
    screen = _screen(qtbot, tmp_path, poller=_Poller(fail=True), ai=ai)

    await screen._analyse_matrix()

    assert ai.calls[0]["positions"] is None


@pytest.mark.asyncio
async def test_a_held_book_reaches_the_narrative(qtbot, tmp_path) -> None:
    ai = _AIService(_narrative())
    screen = _screen(qtbot, tmp_path, poller=_Poller([_Position("BHP.AX", 120.0)]), ai=ai)

    await screen._analyse_matrix()

    assert ai.calls[0]["positions"] == {"BHP.AX": 120.0}


@pytest.mark.asyncio
async def test_without_a_fitted_engine_there_is_no_comparison_to_report(qtbot, tmp_path) -> None:
    """⚠️ Manufacturing "the engines agree" out of ONE reading is the
    fabricated-all-clear shape. Before the HMM has published anything there is
    nothing to compare."""
    ai = _AIService(_narrative())
    screen = _screen(qtbot, tmp_path, ai=ai)

    await screen._analyse_matrix()

    assert ai.calls[0]["friction"] is None
    assert "unavailable" in screen.matrix_friction_label.text()


@pytest.mark.asyncio
async def test_a_disagreeing_execution_engine_is_reported_on_its_own_line(qtbot, tmp_path) -> None:
    """The friction reading is a computed fact and gets its own line, not a
    sentence somewhere inside the model's paragraph."""
    ai = _AIService(_narrative())
    screen = _screen(qtbot, tmp_path, ai=ai)
    await screen._on_regime(
        RegimeEvent(
            label="bear",
            probs={"bear": 0.8},
            exposure_scalar=0.5,
            ts=datetime.now(UTC),
        )
    )

    await screen._analyse_matrix()

    assert "FRICTION" in screen.matrix_friction_label.text()
    assert ai.calls[0]["friction"] is not None


@pytest.mark.asyncio
async def test_an_agreeing_execution_engine_says_so_without_alarm(qtbot, tmp_path) -> None:
    """⚠️ An alert that fires when the engines AGREE is ignored within a week,
    and then the real divergence passes unread."""
    screen = _screen(qtbot, tmp_path)
    await screen._on_regime(
        RegimeEvent(
            label="bull",
            probs={"bull": 0.8},
            exposure_scalar=1.0,
            ts=datetime.now(UTC),
        )
    )

    await screen._analyse_matrix()

    assert "FRICTION" not in screen.matrix_friction_label.text()
    assert "agree" in screen.matrix_friction_label.text()


@pytest.mark.asyncio
async def test_an_unknown_regime_label_yields_no_comparison(qtbot, tmp_path) -> None:
    """A label the enum does not recognise is a parsing accident, and mapping
    it to the nearest regime would invent agreement or friction from one."""
    screen = _screen(qtbot, tmp_path)
    screen._current_label = "melt_up"
    screen._regime_scalar = 1.0

    assert screen._execution_regime() is None


@pytest.mark.asyncio
async def test_short_history_refuses_before_anything_is_fetched(qtbot, tmp_path) -> None:
    """No benchmark history means no signal, and no signal means no growth
    fetch either - a refusal should not spend a network call."""
    growth = _Growth()
    screen = _screen(qtbot, tmp_path, growth=growth)
    screen.runtime.history_source = _Bars(n=10)

    await screen._analyse_matrix()

    assert "not enough benchmark history" in screen.matrix_decision_label.text()
    assert growth.asked == []


def test_the_panel_is_hidden_for_a_beginner(qtbot, tmp_path) -> None:
    """Level-gated exactly like the macro panel beside it."""
    runtime = Runtime.build_demo(
        settings=Settings(
            _env_file=None,
            data_dir=str(tmp_path),
            ui_level=UiLevel.GUIDED.label.lower(),
            deployed_strategies="swing",
        )
    )
    screen = RegimeMonitorScreen(runtime)
    qtbot.addWidget(screen)
    screen.show()

    assert not screen.matrix_panel.isVisible()
    assert not screen.macro_panel.isVisible()


@pytest.mark.asyncio
async def test_the_regime_is_held_rather_than_flipped_by_one_contrary_reading(
    qtbot, tmp_path
) -> None:
    """⚠️ The hysteresis gate belongs to the SCREEN, not to a click. `decide` is
    pure, so a rebuilt gate would re-report every reading as the first one and
    the smoothing would do nothing at all."""
    screen = _screen(qtbot, tmp_path)
    await screen._analyse_matrix()
    assert "Bull Market" in screen.matrix_decision_label.text()

    screen.runtime.macro_source = _Growth([-0.20, -0.50, -0.85])
    await screen._analyse_matrix()

    text = screen.matrix_decision_label.text()
    assert "Bull Market" in text, "one contrary reading changed the reported regime"
    assert isinstance(screen._matrix_gate.settle(MatrixRefusal(missing=("x",))), MatrixRefusal)


@pytest.mark.asyncio
async def test_the_measured_inputs_are_shown_beside_the_regime(qtbot, tmp_path) -> None:
    """⚠️ Every Phase 1 classifier was computed and displayed nowhere. A panel
    that states a regime without the readings it came from cannot be argued
    with."""
    screen = _screen(qtbot, tmp_path)

    await screen._analyse_matrix()

    conditions = screen.matrix_conditions_label.text()
    assert "Realised vol" in conditions
    assert "curve" in conditions
    assert "spreads" in conditions


@pytest.mark.asyncio
async def test_a_refusal_still_shows_what_WAS_measured(qtbot, tmp_path) -> None:
    """⚠️ A refusal names the missing input. Without this it names nothing
    else, and an operator cannot tell a matrix short one series from one that
    measured nothing at all."""
    screen = _screen(qtbot, tmp_path, growth=_RaisingGrowth())

    await screen._analyse_matrix()

    assert "NO REGIME" in screen.matrix_decision_label.text()
    assert "Realised vol" in screen.matrix_conditions_label.text()
