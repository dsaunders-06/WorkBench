"""The staleness bound is DERIVED from the poll cadence, not chosen.

Item 6 refused searching back through the audit CSV because the most recent
stored value was two days old and measured on a book that no longer existed. A
live value with no age bound is that same failure with a fresher face, so the
bound is asserted here against the cadence rather than written as a magic number.
"""

from __future__ import annotations

from qat.config import Settings


def test_book_risk_defaults():
    # _env_file=None: otherwise this loads the operator's live .env.
    settings = Settings(_env_file=None)
    assert settings.book_risk_poll_seconds == 60.0
    assert settings.book_risk_min_observations == 30
    # Three polls. The bound is DERIVED from the cadence, not chosen.
    assert settings.book_risk_max_age_seconds == 3 * settings.book_risk_poll_seconds
