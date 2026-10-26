"""GTC renewal is retired from the live broker adapter."""

from qat.data.broker import gtc_expiry
from qat.data.broker.ib_adapter import IBAdapter


def test_live_adapter_has_no_gtc_renewal_entry_points() -> None:
    assert not hasattr(IBAdapter, "plan_gtc_renewal")
    assert not hasattr(IBAdapter, "apply_approved_gtc_renewal")


def test_expiry_journal_has_no_renewal_plan_or_writer() -> None:
    assert not hasattr(gtc_expiry, "GtcRenewalPlan")
    assert not hasattr(gtc_expiry, "GtcRenewalJournal")
