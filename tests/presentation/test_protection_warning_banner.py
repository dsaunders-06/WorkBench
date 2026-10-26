"""A stop warning remains visible on the dashboard between daily alerts."""

from datetime import datetime

from qat.config import Settings
from qat.data.broker.adapter import RestingStopOrder
from qat.data.broker.gtc_expiry import GtcExpiryStore
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime


def test_unknown_age_manual_stop_is_prominent_on_dashboard(qtbot, tmp_path) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    store.record(
        [RestingStopOrder("BHP.AX", "999", 50.0, 10)],
        observed_at=datetime.fromisoformat("2026-10-22T10:30:00+11:00"),
    )
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    screen = DashboardScreen(Runtime.build_demo(settings=settings))
    qtbot.addWidget(screen)
    screen._refresh_protection_expiry()

    assert not screen.protection_expiry_banner.isHidden()
    assert "BHP.AX" in screen.protection_expiry_banner.text()
    assert "PROTECTION ALERT" in screen.protection_expiry_banner.text()
