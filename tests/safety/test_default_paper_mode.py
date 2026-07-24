"""Safety test 5 of 5 (spec §M/§O): default config is paper mode.

This must never regress - it is the first line of defence against
accidentally shipping a live-trading default.
"""

from __future__ import annotations

from qat.config import Settings


def test_default_trading_mode_is_paper():
    assert Settings(_env_file=None).trading_mode == "paper"
