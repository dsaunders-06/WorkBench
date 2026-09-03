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


def test_the_age_bound_must_outlive_its_poll_interval():
    """⚠️ The "three polls" relationship was documented and unenforced.

    `book_risk_max_age_seconds` and `book_risk_poll_seconds` are independent
    fields, and the defaults test above reads both defaults - so it asserts
    `180 == 3 * 60` and cannot fail. Raise the poll interval past the bound and
    every reading is stale on arrival: all four Risk Console tiles and the
    model's `book_now` go dark permanently, with nothing logged.
    """
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="at least twice"):
        Settings(_env_file=None, book_risk_poll_seconds=200.0)

    # Exactly twice is the boundary and is allowed.
    settings = Settings(_env_file=None, book_risk_poll_seconds=90.0)
    assert settings.book_risk_max_age_seconds == 180.0
