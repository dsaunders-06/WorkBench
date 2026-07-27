"""Settings (spec §K/M10): AI provider selection and market/watchlist
configuration - the two things M9 explicitly deferred as placeholders.

Every field here is restart-required, not live-applied: Save writes to .env
(non-secret fields, via qat.env_file.update_env_file) and the OS keyring (the
Anthropic key, via qat.security.set_secret - never into .env, matching
.env.example's existing "secrets go in the keyring, not here" convention).
The whole engine graph (Runtime.build_demo) is built once at startup around
these values, so nothing on this screen reconfigures the already-running
app - that would mean live-rewiring the market data feed, regime engine, and
every screen that references the watchlist mid-session, a much larger and
riskier change than a restart.
"""

from __future__ import annotations

import asyncio
import logging

import requests
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qat import env_file, security
from qat.config import Settings
from qat.domain.ai_advisory.llm_engine import LocalEngine, normalize_openai_base_url
from qat.paths import app_dir, env_path
from qat.presentation.runtime import Runtime

logger = logging.getLogger(__name__)

_PROVIDER_LABELS = {"anthropic": "Anthropic", "local": "Local (LM Studio)", "demo": "Demo"}
_PROVIDER_VALUES = {label: value for value, label in _PROVIDER_LABELS.items()}
_GENERAL_ORDER = ("anthropic", "local", "demo")
_SENSITIVE_ORDER = ("local", "anthropic", "demo")
_MARKETS = ("US", "ASX")
_CATEGORIES = ("curated", "etf", "megacap")
_BROKER_LABELS = {
    "mock": "Simulated (built-in)",
    "alpaca": "Alpaca paper account",
    "ibkr": "Interactive Brokers",
}
_BROKER_VALUES = {label: value for value, label in _BROKER_LABELS.items()}
_BROKERS = ("mock", "alpaca", "ibkr")
# Recommend is listed first so it is the top item as well as the default value -
# the safe option should also be the one a careless click lands on.
_EXECUTION_MODE_LABELS = {
    "recommend": "Recommend (human signs off every order)",
    "auto": "Auto-trade (no per-order confirmation)",
}
_EXECUTION_MODE_VALUES = {label: value for value, label in _EXECUTION_MODE_LABELS.items()}
_DATA_SOURCE_LABELS = {
    "synthetic": "Simulated (random walk)",
    "yfinance": "Real market data (Yahoo, free/delayed)",
    "alpaca": "Real market data (Alpaca, US only)",
}
_DATA_SOURCE_VALUES = {label: value for value, label in _DATA_SOURCE_LABELS.items()}
_ALPACA_FEED_LABELS = {
    "iex": "IEX - real time, single exchange (any account)",
    "sip": "SIP - full consolidated tape (paid subscription)",
    "delayed_sip": "Delayed SIP - consolidated, 15 min behind (free)",
}
_ALPACA_FEED_VALUES = {label: value for value, label in _ALPACA_FEED_LABELS.items()}
_FUNDAMENTALS_LABELS = {
    "mock": "Simulated (every figure invented)",
    "yfinance": "Real company fundamentals (Yahoo)",
}
_FUNDAMENTALS_VALUES = {label: value for value, label in _FUNDAMENTALS_LABELS.items()}


class SettingsScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        settings = runtime.settings

        layout = QVBoxLayout(self)

        ai_group = QGroupBox("AI Provider")
        ai_form = QFormLayout(ai_group)

        self.general_provider = QComboBox()
        for value in _GENERAL_ORDER:
            self.general_provider.addItem(_PROVIDER_LABELS[value])
        self.general_provider.setCurrentText(_PROVIDER_LABELS[settings.general_request_provider])
        ai_form.addRow("General requests:", self.general_provider)

        self.sensitive_provider = QComboBox()
        for value in _SENSITIVE_ORDER:
            self.sensitive_provider.addItem(_PROVIDER_LABELS[value])
        self.sensitive_provider.setCurrentText(
            _PROVIDER_LABELS[settings.sensitive_request_provider]
        )
        self.sensitive_provider.currentTextChanged.connect(self._refresh_sensitive_warning)
        ai_form.addRow("Position-sensitive requests:", self.sensitive_provider)

        self.sensitive_warning = QLabel(
            "⚠ Position and portfolio data will be sent to Anthropic's cloud API "
            "for these requests."
        )
        self.sensitive_warning.setStyleSheet("color: #b71c1c;")
        self.sensitive_warning.setWordWrap(True)
        ai_form.addRow(self.sensitive_warning)
        self._refresh_sensitive_warning()

        self.anthropic_key_input = QLineEdit()
        self.anthropic_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key_input.setPlaceholderText("(leave blank to keep the existing key)")
        ai_form.addRow("Anthropic API key:", self.anthropic_key_input)

        self.local_base_url_input = QLineEdit(settings.local_llm_base_url)
        ai_form.addRow("LM Studio base URL:", self.local_base_url_input)

        self.local_model_input = QLineEdit(settings.local_llm_model)
        ai_form.addRow("LM Studio model name:", self.local_model_input)

        test_row = QHBoxLayout()
        self.test_connection_button = QPushButton("Test Connection")
        self.test_connection_button.clicked.connect(self._on_test_connection_clicked)
        self.test_connection_result = QLabel("")
        test_row.addWidget(self.test_connection_button)
        test_row.addWidget(self.test_connection_result)
        test_row.addStretch(1)
        ai_form.addRow(test_row)

        layout.addWidget(ai_group)

        market_group = QGroupBox("Market && Watchlist")
        market_form = QFormLayout(market_group)

        self.market_combo = QComboBox()
        for market in _MARKETS:
            self.market_combo.addItem(market)
        self.market_combo.setCurrentText(settings.market)
        self.market_combo.currentTextChanged.connect(self._refresh_broker_warning)
        market_form.addRow("Market:", self.market_combo)

        self.category_combo = QComboBox()
        for category in _CATEGORIES:
            self.category_combo.addItem(category)
        self.category_combo.setCurrentText(settings.watchlist_category)
        market_form.addRow("Watchlist category:", self.category_combo)

        self.curated_us_input = QLineEdit(settings.watchlist_curated_us)
        market_form.addRow("US curated tickers:", self.curated_us_input)

        self.curated_asx_input = QLineEdit(settings.watchlist_curated_asx)
        market_form.addRow("ASX curated tickers:", self.curated_asx_input)

        self.max_symbols_input = QSpinBox()
        self.max_symbols_input.setRange(1, 200)
        self.max_symbols_input.setValue(settings.watchlist_max_symbols)
        market_form.addRow("Max symbols:", self.max_symbols_input)

        self.min_volume_input = QSpinBox()
        self.min_volume_input.setRange(0, 1_000_000_000)
        self.min_volume_input.setSingleStep(10_000)
        self.min_volume_input.setValue(settings.watchlist_min_avg_volume)
        market_form.addRow("Min avg. daily volume:", self.min_volume_input)

        layout.addWidget(market_group)

        broker_group = QGroupBox("Broker && Cash")
        broker_form = QFormLayout(broker_group)

        self.broker_combo = QComboBox()
        for value in _BROKERS:
            self.broker_combo.addItem(_BROKER_LABELS[value])
        self.broker_combo.setCurrentText(_BROKER_LABELS[settings.broker])
        self.broker_combo.currentTextChanged.connect(self._refresh_broker_warning)
        broker_form.addRow("Broker:", self.broker_combo)

        self.broker_warning = QLabel(
            "⚠ Alpaca trades US equities only - it cannot trade an ASX watchlist. "
            "Switch Market to US to use it."
        )
        self.broker_warning.setStyleSheet("color: #b71c1c;")
        self.broker_warning.setWordWrap(True)
        broker_form.addRow(self.broker_warning)

        self.alpaca_key_input = QLineEdit()
        self.alpaca_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.alpaca_key_input.setPlaceholderText("(leave blank to keep the existing key)")
        broker_form.addRow("Alpaca API key:", self.alpaca_key_input)

        self.alpaca_secret_input = QLineEdit()
        self.alpaca_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.alpaca_secret_input.setPlaceholderText("(leave blank to keep the existing secret)")
        broker_form.addRow("Alpaca secret key:", self.alpaca_secret_input)

        broker_test_row = QHBoxLayout()
        self.broker_test_button = QPushButton("Test Broker Connection")
        self.broker_test_button.clicked.connect(self._on_test_broker_clicked)
        self.broker_test_result = QLabel("")
        self.broker_test_result.setWordWrap(True)
        broker_test_row.addWidget(self.broker_test_button)
        broker_test_row.addWidget(self.broker_test_result)
        broker_test_row.addStretch(1)
        broker_form.addRow(broker_test_row)

        self.min_cash_reserve_input = QDoubleSpinBox()
        self.min_cash_reserve_input.setRange(0.01, 1_000_000.0)
        self.min_cash_reserve_input.setDecimals(2)
        self.min_cash_reserve_input.setPrefix("$")
        self.min_cash_reserve_input.setValue(settings.min_cash_reserve)
        broker_form.addRow("Minimum cash reserve:", self.min_cash_reserve_input)

        cash_note = QLabel(
            "A buy is capped so it can never spend below this reserve, and can never exceed "
            "available cash - the account cannot be leveraged. The minimum is $0.01: this "
            "rule cannot be switched off."
        )
        cash_note.setStyleSheet("color: gray;")
        cash_note.setWordWrap(True)
        broker_form.addRow(cash_note)

        layout.addWidget(broker_group)
        self._refresh_broker_warning()

        layout.addWidget(self._build_data_group(settings))
        layout.addWidget(self._build_execution_group(settings))

        # Where these settings actually live (M22). It used to depend on the
        # working directory, which meant an operator editing one .env could be
        # looking at a different one from the app - and had no way to tell.
        self.config_location = QLabel(f"Settings and records are stored in {app_dir()}")
        self.config_location.setStyleSheet("color: gray;")
        self.config_location.setWordWrap(True)
        self.config_location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.config_location)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._on_save_clicked)
        layout.addWidget(self.save_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def _build_data_group(self, settings: Settings) -> QGroupBox:
        """Market data source (spec M14).

        Placed directly above Execution Mode on purpose: these two settings are
        only meaningful together. Auto-trading against simulated prices is a
        loop that trades noise, and the pairing makes that visible rather than
        leaving it two screens apart.
        """
        group = QGroupBox("Market Data")
        form = QFormLayout(group)

        self.data_source_combo = QComboBox()
        for label in _DATA_SOURCE_LABELS.values():
            self.data_source_combo.addItem(label)
        self.data_source_combo.setCurrentText(_DATA_SOURCE_LABELS[settings.market_data_source])
        self.data_source_combo.currentTextChanged.connect(self._refresh_data_warning)
        form.addRow("Price source:", self.data_source_combo)

        self.data_warning = QLabel(
            "<b>Simulated prices.</b> Every price, indicator, signal and backtest is computed "
            "from a seeded random walk, not from any market. Nothing observed in this mode "
            "tells you how a strategy would behave on real data."
        )
        self.data_warning.setStyleSheet(
            "color: #78350f; background: #fef3c7; border: 1px solid #b45309; padding: 6px;"
        )
        self.data_warning.setWordWrap(True)
        form.addRow(self.data_warning)

        real_note = QLabel(
            "Yahoo data is free, unofficial and typically delayed ~15 minutes. It is "
            "rate-limited and can return nothing without warning - the app degrades to "
            "simulated data with a logged warning rather than stopping."
        )
        real_note.setStyleSheet("color: gray;")
        real_note.setWordWrap(True)
        form.addRow(real_note)

        self.alpaca_feed_combo = QComboBox()
        for label in _ALPACA_FEED_LABELS.values():
            self.alpaca_feed_combo.addItem(label)
        self.alpaca_feed_combo.setCurrentText(_ALPACA_FEED_LABELS[settings.alpaca_data_feed])
        self.alpaca_feed_combo.currentTextChanged.connect(self._refresh_data_warning)
        # Kept so the row - label included - can be hidden as a unit. Hiding only
        # the combo leaves a stranded "Alpaca feed:" label next to empty space.
        self._data_form = form
        form.addRow("Alpaca feed:", self.alpaca_feed_combo)

        self.alpaca_feed_note = QLabel(
            "Alpaca uses the same API keys as the broker (Settings -> Broker) and serves US "
            "equities only. <b>IEX is a single exchange</b> carrying a small share of "
            "consolidated volume, so quotes for less liquid names can be sparse or lag the "
            "tape. SIP is the full consolidated tape but needs a paid Algo Trader Plus "
            "subscription - without one, those requests fail and the app falls back to "
            "simulated data with a logged warning."
        )
        self.alpaca_feed_note.setStyleSheet("color: gray;")
        self.alpaca_feed_note.setWordWrap(True)
        form.addRow(self.alpaca_feed_note)

        self.fundamentals_combo = QComboBox()
        for label in _FUNDAMENTALS_LABELS.values():
            self.fundamentals_combo.addItem(label)
        self.fundamentals_combo.setCurrentText(_FUNDAMENTALS_LABELS[settings.fundamentals_source])
        self.fundamentals_combo.currentTextChanged.connect(self._refresh_data_warning)
        form.addRow("Company fundamentals:", self.fundamentals_combo)

        self.fundamentals_warning = QLabel(
            "<b>Simulated fundamentals.</b> Every EPS growth, PEG, ROE and dividend figure is "
            "generated, not reported. Nine of the fifteen strategies select on these, so on "
            "this setting their picks carry no information about the companies."
        )
        self.fundamentals_warning.setStyleSheet(
            "color: #78350f; background: #fef3c7; border: 1px solid #b45309; padding: 6px;"
        )
        self.fundamentals_warning.setWordWrap(True)
        form.addRow(self.fundamentals_warning)

        self.fundamentals_note = QLabel(
            "Real fundamentals are pulled from Yahoo and cached for "
            f"{settings.fundamentals_cache_days:g} days. Figures a company does not publish - "
            "and an index ETF has no earnings or return on equity at all - are left empty, and "
            "a strategy that needs one abstains on that symbol rather than guessing. "
            "<b>Expect noticeably fewer signals</b> than on simulated data."
        )
        self.fundamentals_note.setStyleSheet("color: gray;")
        self.fundamentals_note.setWordWrap(True)
        form.addRow(self.fundamentals_note)

        self._refresh_data_warning()
        return group

    def _refresh_data_warning(self) -> None:
        selected = _DATA_SOURCE_VALUES[self.data_source_combo.currentText()]
        self.data_warning.setVisible(selected == "synthetic")
        # The feed picker only means anything for Alpaca, and showing it
        # otherwise implies it affects Yahoo or the random walk.
        is_alpaca = selected == "alpaca"
        self._data_form.setRowVisible(self.alpaca_feed_combo, is_alpaca)
        self.alpaca_feed_note.setVisible(is_alpaca)

        is_mock_fundamentals = _FUNDAMENTALS_VALUES[self.fundamentals_combo.currentText()] == "mock"
        self.fundamentals_warning.setVisible(is_mock_fundamentals)
        self.fundamentals_note.setVisible(not is_mock_fundamentals)

    def _build_execution_group(self, settings: Settings) -> QGroupBox:
        """Execution mode (spec M13).

        Deliberately its own visually distinct group at the bottom of the
        screen rather than one more checkbox among the others: an unattended
        execution switch that reads like a preference gets flipped like one.
        Turning it on additionally requires the confirmation dialog in
        _confirm_autonomy, which spells out what the rails do and do not do.
        """
        group = QGroupBox("Execution Mode")
        form = QFormLayout(group)

        self.execution_mode_combo = QComboBox()
        for label in _EXECUTION_MODE_LABELS.values():
            self.execution_mode_combo.addItem(label)
        self.execution_mode_combo.setCurrentText(_EXECUTION_MODE_LABELS[settings.execution_mode])
        self.execution_mode_combo.currentTextChanged.connect(self._on_execution_mode_changed)
        form.addRow("Mode:", self.execution_mode_combo)

        mode_note = QLabel(
            "<b>Recommend</b> (default): every order waits in the Order Blotter for your "
            "sign-off, with the reasoning behind it.<br>"
            "<b>Auto-trade</b>: qualifying orders are signed off without confirmation. "
            "Paper accounts only."
        )
        mode_note.setStyleSheet("color: gray;")
        mode_note.setWordWrap(True)
        form.addRow(mode_note)

        # A checkable dropdown rather than the free-text field this replaced
        # (M20). Autonomy is per strategy and can cover several, so a plain
        # single-select dropdown would not express it - but a typed list could
        # silently grant nothing at all: "trend-following" instead of
        # "trend_following" parsed cleanly, matched no strategy, and left the
        # operator believing a strategy was cleared when it was not.
        self.autonomous_strategies_combo = QComboBox()
        # Editable with a read-only line edit, which is the only way a combo can
        # display text that is not one of its items. A closed non-editable combo
        # always shows its CURRENT item, so it read "trend_following" - the
        # first entry - while swing was the one actually ticked. Nothing was
        # wrong with the saved state, but the control asserted the opposite of
        # it, which on an autonomy setting is the worst place to be vague.
        # The line edit is constructed here rather than read back off the combo:
        # QComboBox.lineEdit() is Optional, and this one is never absent.
        self._strategy_display = QLineEdit()
        self._strategy_display.setReadOnly(True)
        self._strategy_display.setPlaceholderText("none selected")
        self.autonomous_strategies_combo.setEditable(True)
        self.autonomous_strategies_combo.setLineEdit(self._strategy_display)
        # Held as a typed attribute rather than read back off the combo:
        # QComboBox.model() returns the abstract base, which has no item().
        self._strategy_model = QStandardItemModel(self)
        self.autonomous_strategies_combo.setModel(self._strategy_model)
        cleared = set(settings.autonomous_strategies_tuple)
        for strategy in self.runtime.available_strategies:
            item = QStandardItem(strategy.name)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setData(
                Qt.CheckState.Checked if strategy.name in cleared else Qt.CheckState.Unchecked,
                Qt.ItemDataRole.CheckStateRole,
            )
            self._strategy_model.appendRow(item)
        self._strategy_model.itemChanged.connect(self._refresh_selected_strategies)
        form.addRow("Strategies cleared to auto-trade:", self.autonomous_strategies_combo)

        self.selected_strategies_label = QLabel("")
        self.selected_strategies_label.setWordWrap(True)
        form.addRow(self.selected_strategies_label)
        self._refresh_selected_strategies()

        strategies_note = QLabel(
            "Autonomy is granted per strategy, never to all of them at once. A strategy not "
            "listed here still produces recommendations for your sign-off."
        )
        strategies_note.setStyleSheet("color: gray;")
        strategies_note.setWordWrap(True)
        form.addRow(strategies_note)

        self.autonomy_warning = QLabel(
            "<b>AUTO-TRADE PLACES REAL PAPER ORDERS WITH NO PER-ORDER CONFIRMATION.</b><br>"
            "Orders are still checked by the risk engine, the no-leverage cash rule and the "
            "kill-switch, and are only placed while the market is open in an eligible session "
            "phase. Those rails limit the damage; they do not make the strategy correct. "
            "Review the decision journal regularly."
        )
        self.autonomy_warning.setStyleSheet(
            "color: #7f1d1d; background: #fee2e2; border: 1px solid #b91c1c; padding: 6px;"
        )
        self.autonomy_warning.setWordWrap(True)
        form.addRow(self.autonomy_warning)

        self._refresh_autonomy_warning()
        return group

    def selected_strategies(self) -> list[str]:
        return [
            self._strategy_model.item(row).text()
            for row in range(self._strategy_model.rowCount())
            if self._strategy_model.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _refresh_selected_strategies(self) -> None:
        """Keeps the summary honest, and keeps the combo from showing whichever
        item happens to be current as though it were the whole answer."""
        chosen = self.selected_strategies()
        if chosen:
            self.selected_strategies_label.setText(f"Cleared: {', '.join(chosen)}")
            self.selected_strategies_label.setStyleSheet("color: #7f1d1d; font-weight: bold;")
        else:
            self.selected_strategies_label.setText("Cleared: none - every order waits for you.")
            self.selected_strategies_label.setStyleSheet("color: gray;")
        # Written straight to the line edit. setCurrentText() on a combo only
        # takes effect when the text matches an existing item, so the summary
        # was silently discarded and the stale current item stayed on show.
        self._strategy_display.setText(", ".join(chosen) if chosen else "")

    def _refresh_autonomy_warning(self) -> None:
        self.autonomy_warning.setVisible(self._selected_execution_mode() == "auto")

    def _selected_execution_mode(self) -> str:
        return _EXECUTION_MODE_VALUES[self.execution_mode_combo.currentText()]

    def _on_execution_mode_changed(self) -> None:
        if self._selected_execution_mode() == "auto" and not self._confirm_autonomy():
            self.execution_mode_combo.setCurrentText(_EXECUTION_MODE_LABELS["recommend"])
        self._refresh_autonomy_warning()

    def _confirm_autonomy(self) -> bool:
        """A separate, explicit confirmation - not just the combo box changing.

        Returns True only on an affirmative answer; the default button is No,
        so an accidental Enter keypress declines.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Enable autonomous trading?")
        box.setText("Enable auto-trade?")
        box.setInformativeText(
            "The application will place orders on your paper account without asking you "
            "first, whenever an order from a promoted strategy passes every rail.\n\n"
            "What still applies:\n"
            "  - the risk engine sizes and can reject every order\n"
            "  - a buy can never exceed available cash less your reserve\n"
            "  - the kill-switch halts everything when it trips\n"
            "  - orders are only placed while the market is open, outside the opening "
            "and midday windows\n"
            "  - only strategies you list are eligible\n\n"
            "What does not:\n"
            "  - nobody reviews the individual trade before it is placed\n"
            "  - these rails bound the loss; they do not make the strategy profitable\n\n"
            "Every decision, taken or blocked, is written to the decision journal."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _refresh_sensitive_warning(self) -> None:
        is_anthropic = self.sensitive_provider.currentText() == _PROVIDER_LABELS["anthropic"]
        self.sensitive_warning.setVisible(is_anthropic)

    def _refresh_broker_warning(self) -> None:
        is_alpaca = self.broker_combo.currentText() == _BROKER_LABELS["alpaca"]
        is_asx = self.market_combo.currentText() == "ASX"
        self.broker_warning.setVisible(is_alpaca and is_asx)

    def _on_test_broker_clicked(self) -> None:
        asyncio.ensure_future(self._test_broker())

    async def _test_broker(self) -> None:
        self.broker_test_button.setEnabled(False)
        self.broker_test_result.setText("Checking...")
        self.broker_test_result.setStyleSheet("")
        broker = _BROKER_VALUES[self.broker_combo.currentText()]
        # Persist any freshly typed keys first, since the adapter reads them
        # from the keyring rather than from these fields.
        self._save_broker_secrets()
        try:
            ok, message = await asyncio.to_thread(self._check_broker, broker)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("Broker connection test failed")
            ok, message = False, str(exc)
        finally:
            self.broker_test_button.setEnabled(True)
        self.broker_test_result.setText(("✓ " if ok else "✗ ") + message)
        self.broker_test_result.setStyleSheet(f"color: {'#1b5e20' if ok else '#b71c1c'};")

    def _check_broker(self, broker: str) -> tuple[bool, str]:
        if broker != "alpaca":
            return True, f"{_BROKER_LABELS[broker]} needs no connection test"
        from qat.data.broker.alpaca_adapter import AlpacaAdapter

        adapter = AlpacaAdapter(settings=self.runtime.settings)
        account = asyncio.run(adapter.account())
        return True, (
            f"connected to Alpaca {'paper' if adapter.paper else 'LIVE'} - "
            f"cash ${account.cash:,.2f}, equity ${account.net_liquidation:,.2f}"
        )

    def _save_broker_secrets(self) -> None:
        api_key = self.alpaca_key_input.text().strip()
        if api_key:
            security.set_secret("ALPACA_API_KEY", api_key)
            self.alpaca_key_input.clear()
        secret_key = self.alpaca_secret_input.text().strip()
        if secret_key:
            security.set_secret("ALPACA_SECRET_KEY", secret_key)
            self.alpaca_secret_input.clear()

    def _on_test_connection_clicked(self) -> None:
        asyncio.ensure_future(self._test_connection())

    async def _test_connection(self) -> None:
        self.test_connection_button.setEnabled(False)
        self.test_connection_result.setText("Checking...")
        self.test_connection_result.setStyleSheet("")
        base_url = self.local_base_url_input.text().strip()
        model = self.local_model_input.text().strip()
        try:
            ok, message = await asyncio.to_thread(self._check_connection, base_url, model)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("Local LLM connection test failed")
            ok, message = False, str(exc)
        finally:
            self.test_connection_button.setEnabled(True)
        self.test_connection_result.setText(("✓ " if ok else "✗ ") + message)
        self.test_connection_result.setStyleSheet(f"color: {'#1b5e20' if ok else '#b71c1c'};")

    @staticmethod
    def _check_connection(base_url: str, model: str) -> tuple[bool, str]:
        """Runs a real (tiny) completion rather than only pinging /models.

        /models answers happily even when the base URL is missing its /v1
        segment or the model name is wrong, so a reachability-only check
        reported success for configurations that then failed on every actual
        request - exactly the failure this test is meant to catch.
        """
        normalized = normalize_openai_base_url(base_url)
        engine = LocalEngine(base_url=normalized, model=model or None)
        try:
            engine._post(
                {
                    "model": engine.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "stream": False,
                }
            )
        except requests.RequestException as exc:
            return False, f"cannot reach {normalized}: {exc}"
        except Exception as exc:  # noqa: BLE001 - reported verbatim to the user
            return False, f"{normalized} rejected the request: {exc}"
        return True, f"completions OK at {normalized} (model {engine.model!r})"

    def _on_save_clicked(self) -> None:
        updates = {
            "QAT_GENERAL_REQUEST_PROVIDER": _PROVIDER_VALUES[self.general_provider.currentText()],
            "QAT_SENSITIVE_REQUEST_PROVIDER": _PROVIDER_VALUES[
                self.sensitive_provider.currentText()
            ],
            "QAT_LOCAL_LLM_BASE_URL": self.local_base_url_input.text().strip(),
            "QAT_LOCAL_LLM_MODEL": self.local_model_input.text().strip(),
            "QAT_MARKET": self.market_combo.currentText(),
            "QAT_WATCHLIST_CATEGORY": self.category_combo.currentText(),
            "QAT_WATCHLIST_CURATED_US": self.curated_us_input.text().strip(),
            "QAT_WATCHLIST_CURATED_ASX": self.curated_asx_input.text().strip(),
            "QAT_WATCHLIST_MAX_SYMBOLS": str(self.max_symbols_input.value()),
            "QAT_WATCHLIST_MIN_AVG_VOLUME": str(self.min_volume_input.value()),
            "QAT_BROKER": _BROKER_VALUES[self.broker_combo.currentText()],
            "QAT_MIN_CASH_RESERVE": f"{self.min_cash_reserve_input.value():.2f}",
            "QAT_MARKET_DATA_SOURCE": _DATA_SOURCE_VALUES[self.data_source_combo.currentText()],
            "QAT_ALPACA_DATA_FEED": _ALPACA_FEED_VALUES[self.alpaca_feed_combo.currentText()],
            "QAT_FUNDAMENTALS_SOURCE": _FUNDAMENTALS_VALUES[self.fundamentals_combo.currentText()],
            "QAT_EXECUTION_MODE": self._selected_execution_mode(),
            "QAT_AUTONOMOUS_STRATEGIES": ",".join(self.selected_strategies()),
        }
        # The same absolute path Settings reads from (M22). Left relative, Save
        # wrote a .env beside whatever directory the app was launched from,
        # which the next launch might never look at.
        env_file.update_env_file(updates, path=env_path())

        api_key = self.anthropic_key_input.text().strip()
        if api_key:
            security.set_secret("ANTHROPIC_API_KEY", api_key)
            self.anthropic_key_input.clear()
        self._save_broker_secrets()

        self.status_label.setText("Saved. Restart the application for changes to take effect.")
