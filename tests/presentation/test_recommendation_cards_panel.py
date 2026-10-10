"""Per-card sign-off UI remains advisory-only and has no bulk action."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from qat.operational.cards import ManualOrderInstruction, RecommendationCard, ReconfirmationRequired
from qat.presentation.cards_panel import RecommendationCardsPanel

NOW = datetime.fromisoformat("2026-01-06T17:30:00+11:00")
OPEN = datetime.fromisoformat("2026-01-07T10:00:00+11:00")


def sample_card(status="created") -> RecommendationCard:
    candidate = SimpleNamespace(
        symbol="BHP.AX",
        label="unvalidated strategy, no demonstrated edge",
        entry_limit_raw=Decimal("100.00"),
        structural_stop_raw=Decimal("98.00"),
        expires_at=OPEN,
        snapshot_hash="a" * 64,
        source_records=(SimpleNamespace(version=2, content_hash="b" * 64, label="OPERATIONAL"),),
        evidence=SimpleNamespace(patterns=("double_bottom",), pattern_decisions=()),
    )
    return RecommendationCard(
        "card-1",
        candidate,
        10,
        Decimal("20.00"),
        "fixed 1% risk to stop, no edge assumed",
        (),
        status,
    )


def instruction() -> ManualOrderInstruction:
    return ManualOrderInstruction(
        "card-1",
        "order-id",
        "BHP.AX",
        10,
        Decimal("100.00"),
        Decimal("98.00"),
        OPEN,
        Decimal("20.00"),
        ("Protective stop at fill", "+1R partial target"),
    )


class FakeService:
    def __init__(self, card=None) -> None:
        self.card = card or sample_card()
        self.approval_calls = []
        self.declines = []
        self.changed = False
        self.events = SimpleNamespace(events=[])

    def display(self, card_id, *, now):
        assert card_id == self.card.card_id
        return replace(self.card, status="expired") if now >= OPEN else self.card

    def preview(self, card_id, *, now):
        assert card_id == self.card.card_id
        return instruction()

    async def approve(self, card_id, operator, *, now, reconfirm=False):
        self.approval_calls.append((card_id, operator, reconfirm))
        if self.changed and not reconfirm:
            raise ReconfirmationRequired(10, 8)
        return instruction()

    def decline(self, card_id, operator, *, now):
        self.declines.append((card_id, operator))


def test_card_panel_shows_required_evidence_and_only_individual_actions(qtbot) -> None:
    panel = RecommendationCardsPanel(FakeService(), now=lambda: NOW)
    qtbot.addWidget(panel)
    panel.set_cards((sample_card(),))
    text = " ".join(label.text() for label in panel.findChildren(type(panel.warning_label)))
    assert "unvalidated strategy, no demonstrated edge" in text
    assert "double_bottom" in text
    assert "100.00" in text and "98.00" in text
    assert "10" in text and "20.00" in text
    assert "OPERATIONAL" in text and "a" * 64 in text
    assert "fixed 1% risk to stop, no edge assumed" in text
    assert list(panel.approve_buttons) == ["card-1"]
    assert list(panel.decline_buttons) == ["card-1"]
    assert "font-weight" in panel.warning_label.styleSheet()


@pytest.mark.asyncio
async def test_approve_requires_signoff_dialog_then_shows_exact_manual_order(
    qtbot, monkeypatch
) -> None:
    service = FakeService()
    panel = RecommendationCardsPanel(service, now=lambda: NOW)
    qtbot.addWidget(panel)
    panel.set_cards((service.card,))
    prompts = []
    shown = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: (prompts.append(args), QMessageBox.StandardButton.Yes)[1],
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(args))
    qtbot.mouseClick(panel.approve_buttons["card-1"], Qt.MouseButton.LeftButton)
    await asyncio.sleep(0.05)
    assert len(prompts) == 1
    assert "Protective stop" in str(prompts[0])
    assert service.approval_calls == [("card-1", "operator", False)]
    assert "BHP.AX" in str(shown) and "100.00" in str(shown) and "98.00" in str(shown)


@pytest.mark.asyncio
async def test_changed_sizing_requires_second_confirmation(qtbot, monkeypatch) -> None:
    service = FakeService()
    service.changed = True
    panel = RecommendationCardsPanel(service, now=lambda: NOW)
    qtbot.addWidget(panel)
    panel.set_cards((service.card,))
    prompts = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: (prompts.append(args), QMessageBox.StandardButton.Yes)[1],
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    qtbot.mouseClick(panel.approve_buttons["card-1"], Qt.MouseButton.LeftButton)
    await asyncio.sleep(0.05)
    assert len(prompts) == 2
    assert "10" in str(prompts[1]) and "8" in str(prompts[1])
    assert service.approval_calls[-1] == ("card-1", "operator", True)


def test_decline_and_expiry_disable_card_actions(qtbot) -> None:
    service = FakeService()
    panel = RecommendationCardsPanel(service, now=lambda: NOW)
    qtbot.addWidget(panel)
    panel.set_cards((service.card,))
    qtbot.mouseClick(panel.decline_buttons["card-1"], Qt.MouseButton.LeftButton)
    assert service.declines == [("card-1", "operator")]
    panel.now = lambda: OPEN
    panel.refresh()
    assert not panel.approve_buttons["card-1"].isEnabled()
    assert not panel.decline_buttons["card-1"].isEnabled()


def test_revoked_card_is_disabled_and_manual_exit_alerts_show_exact_details(qtbot) -> None:
    service = FakeService(sample_card(status="revoked"))
    service.events.events.append(
        SimpleNamespace(
            card_id="card-1",
            kind="exit_alert",
            detail={
                "kind": "runner_protective_stop",
                "side": "sell",
                "quantity": 5,
                "order_type": "STOP_GTC",
                "price": "98.00",
                "effective_open": None,
                "oca_group": None,
                "manual_tws_only": True,
            },
        )
    )
    panel = RecommendationCardsPanel(service, now=lambda: NOW)
    qtbot.addWidget(panel)
    panel.set_cards((service.card,))
    text = " ".join(label.text() for label in panel.findChildren(type(panel.warning_label)))
    assert "runner_protective_stop" in text
    assert "SELL 5" in text and "STOP_GTC" in text and "98.00" in text
    assert "manual TWS" in text
    assert not panel.approve_buttons["card-1"].isEnabled()
    assert not panel.decline_buttons["card-1"].isEnabled()
