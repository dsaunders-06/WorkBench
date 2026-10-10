"""Offline checks for the SUN consolidation probe analysis."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase3_sun_derivation.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase3_sun_derivation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bar(volume: str, close: str = "23.452") -> dict[str, object]:
    fields = {
        key: {"python_type": "float", "repr": value}
        for key, value in {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
        }.items()
    }
    fields["date"] = {"python_type": "date", "repr": "datetime.date(2025, 2, 14)"}
    return {"fields": fields}


def test_uses_code_direction_and_exact_shortest_float_decimal(tmp_path: Path) -> None:
    source = tmp_path / "recorded.json"
    source.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "symbol": "SUN.AX",
                        "series": "TRADES",
                        "use_rth": False,
                        "error": None,
                        "bars": [_bar("2658069.5589")],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = _module().analyse(source)
    assert result["bar_count"] == 1
    assert result["whole_share_count"] == 1
    assert result["adjusted_fractional_volume_count"] == 1
    assert result["bars"][0]["derived_raw_volume"] == "3123099"
    assert result["bars"][0]["derived_raw_ohlc"]["close"] == "19.9599972"
    assert result["off_grid_bar_count"] == 1


def test_fractional_inverse_remains_fractional(tmp_path: Path) -> None:
    source = tmp_path / "recorded.json"
    source.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "symbol": "SUN.AX",
                        "series": "TRADES",
                        "use_rth": False,
                        "error": None,
                        "bars": [_bar("1.0")],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = _module().analyse(source)
    assert result["whole_share_count"] == 0
    assert result["bars"][0]["derived_raw_volume"] == "10000/8511"
