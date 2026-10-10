"""Individual advisory recommendation cards with Phase 1 sign-off dialogs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qat.operational.cards import (
    CardService,
    ManualOrderInstruction,
    RecommendationCard,
    ReconfirmationRequired,
)
from qat.presentation import theme
from qat.presentation.signoff import confirm_order_action

logger = logging.getLogger(__name__)
_OPERATOR = "operator"


class RecommendationCardsPanel(QWidget):
    def __init__(
        self, service: CardService | None = None, *, now: Callable[[], datetime] | None = None
    ) -> None:
        super().__init__()
        self.service = service
        self.now = now or (lambda: datetime.now().astimezone())
        self._cards: tuple[RecommendationCard, ...] = ()
        self.approve_buttons: dict[str, QPushButton] = {}
        self.decline_buttons: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        self.warning_label = QLabel("unvalidated strategy, no demonstrated edge")
        self.warning_label.setStyleSheet(theme.text(theme.WARNING, size=theme.SUBHEAD, bold=True))
        layout.addWidget(self.warning_label)
        self.notice = QLabel("No finalised operational recommendation cards loaded.")
        layout.addWidget(self.notice)
        self.card_area = QWidget()
        self.card_layout = QVBoxLayout(self.card_area)
        layout.addWidget(self.card_area)
        layout.addStretch()

    def set_cards(self, cards: tuple[RecommendationCard, ...]) -> None:
        self._cards = cards
        self.refresh()

    def refresh(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.approve_buttons.clear()
        self.decline_buttons.clear()
        self.notice.setVisible(not self._cards)
        for original in self._cards:
            card = (
                self.service.display(original.card_id, now=self.now())
                if self.service is not None
                else original
            )
            group = QGroupBox(f"{card.candidate.symbol} — {card.status}")
            content = QVBoxLayout(group)
            warning = QLabel(card.candidate.label)
            warning.setStyleSheet(theme.text(theme.WARNING, size=theme.SUBHEAD, bold=True))
            content.addWidget(warning)
            patterns = ", ".join(str(pattern) for pattern in card.candidate.evidence.patterns)
            content.addWidget(QLabel(f"Pattern evidence: {patterns or 'unavailable'}"))
            content.addWidget(
                QLabel(
                    f"Entry limit: {card.candidate.entry_limit_raw}  |  "
                    f"Structural stop: {card.candidate.structural_stop_raw}  |  "
                    f"Quantity: {card.quantity}  |  Risk: {card.risk}"
                )
            )
            content.addWidget(QLabel(f"Sizing: {card.sizing_basis}"))
            content.addWidget(QLabel(f"Expires: {card.candidate.expires_at.isoformat()}"))
            content.addWidget(
                QLabel(
                    f"OPERATIONAL snapshot: {card.candidate.snapshot_hash}  |  "
                    "Sources: "
                    + ", ".join(
                        f"v{record.version}:{record.content_hash}"
                        for record in card.candidate.source_records
                    )
                )
            )
            if card.reasons:
                content.addWidget(QLabel("Risk warnings: " + "; ".join(card.reasons)))
            event_store = getattr(self.service, "events", None)
            for event in getattr(event_store, "events", ()):
                if event.card_id != card.card_id or event.kind != "exit_alert":
                    continue
                detail = event.detail
                alert_text = (
                    f"ALERT — manual TWS only: {detail['kind']} | "
                    f"{str(detail['side']).upper()} {detail['quantity']} "
                    f"{card.candidate.symbol} | {detail['order_type']} | "
                    f"price {detail['price']} | open {detail['effective_open']} | "
                    f"OCA {detail['oca_group']}"
                )
                label = QLabel(alert_text)
                label.setWordWrap(True)
                content.addWidget(label)
            approve = QPushButton("Approve")
            decline = QPushButton("Decline")
            enabled = card.status == "created" and card.quantity >= 2 and self.service is not None
            approve.setEnabled(enabled)
            decline.setEnabled(card.status == "created" and self.service is not None)
            approve.clicked.connect(
                lambda _checked=False, key=card.card_id: self._start_approve(key)
            )
            decline.clicked.connect(lambda _checked=False, key=card.card_id: self._decline(key))
            content.addWidget(approve)
            content.addWidget(decline)
            self.approve_buttons[card.card_id] = approve
            self.decline_buttons[card.card_id] = decline
            self.card_layout.addWidget(group)

    def _start_approve(self, card_id: str) -> None:
        asyncio.ensure_future(self._approve(card_id))

    @staticmethod
    def _details(instruction: ManualOrderInstruction) -> str:
        return (
            f"BUY {instruction.quantity} {instruction.symbol} in the next ASX opening "
            f"auction at or below {instruction.entry_limit}.\n"
            f"Opening-auction expiry: {instruction.auction_open.isoformat()}\n"
            f"Protective stop: {instruction.structural_stop}\n"
            f"Risk: {instruction.risk}\n"
            f"Client order ID: {instruction.order_id}\n\n"
            "Approved exit plan:\n" + "\n".join(instruction.exit_plan)
        )

    async def _approve(self, card_id: str) -> None:
        service = self.service
        if service is None:
            return
        try:
            preview = service.preview(card_id, now=self.now())
            if not confirm_order_action(
                self,
                "Approve this advisory card and its full exit plan?\n\n"
                + self._details(preview)
                + "\n\nNo order will be transmitted. Enter manually in TWS.",
            ):
                return
            try:
                instruction = await service.approve(card_id, _OPERATOR, now=self.now())
            except ReconfirmationRequired as changed:
                if not confirm_order_action(
                    self,
                    f"Fresh account state changed quantity from {changed.previous} to "
                    f"{changed.current}, and risk from {changed.previous_risk} to "
                    f"{changed.current_risk}. Re-confirm this card and its exit plan?",
                ):
                    return
                instruction = await service.approve(
                    card_id, _OPERATOR, now=self.now(), reconfirm=True
                )
            QMessageBox.information(
                self,
                "Manual TWS entry — no transmission",
                self._details(instruction),
            )
        except (ValueError, OSError) as error:
            logger.warning("Card approval refused: %s", error)
            QMessageBox.warning(self, "Card unavailable", str(error))
        self.refresh()

    def _decline(self, card_id: str) -> None:
        service = self.service
        if service is None:
            return
        try:
            service.decline(card_id, _OPERATOR, now=self.now())
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Card unavailable", str(error))
        self.refresh()
