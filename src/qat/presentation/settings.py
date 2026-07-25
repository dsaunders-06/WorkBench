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
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qat import env_file, security
from qat.domain.ai_advisory.llm_engine import LocalEngine, normalize_openai_base_url
from qat.presentation.runtime import Runtime

logger = logging.getLogger(__name__)

_PROVIDER_LABELS = {"anthropic": "Anthropic", "local": "Local (LM Studio)", "demo": "Demo"}
_PROVIDER_VALUES = {label: value for value, label in _PROVIDER_LABELS.items()}
_GENERAL_ORDER = ("anthropic", "local", "demo")
_SENSITIVE_ORDER = ("local", "anthropic", "demo")
_MARKETS = ("US", "ASX")
_CATEGORIES = ("curated", "etf", "megacap")


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

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._on_save_clicked)
        layout.addWidget(self.save_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def _refresh_sensitive_warning(self) -> None:
        is_anthropic = self.sensitive_provider.currentText() == _PROVIDER_LABELS["anthropic"]
        self.sensitive_warning.setVisible(is_anthropic)

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
        }
        env_file.update_env_file(updates)

        api_key = self.anthropic_key_input.text().strip()
        if api_key:
            security.set_secret("ANTHROPIC_API_KEY", api_key)
            self.anthropic_key_input.clear()

        self.status_label.setText("Saved. Restart the application for changes to take effect.")
