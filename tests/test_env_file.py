"""qat.env_file.update_env_file (spec M10): the .env merge/write helper the
Settings screen's Save button uses for non-secret configuration."""

from __future__ import annotations

from pathlib import Path

from qat.env_file import update_env_file


def test_creates_new_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / ".env"

    update_env_file({"QAT_MARKET": "US"}, path=path)

    assert path.read_text(encoding="utf-8") == "QAT_MARKET=US\n"


def test_updates_matching_key_in_place_and_preserves_other_lines(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# comment\nQAT_TRADING_MODE=paper\nQAT_LOG_LEVEL=INFO\n", encoding="utf-8")

    update_env_file({"QAT_LOG_LEVEL": "DEBUG"}, path=path)

    content = path.read_text(encoding="utf-8")
    assert "# comment" in content
    assert "QAT_TRADING_MODE=paper" in content
    assert "QAT_LOG_LEVEL=DEBUG" in content
    assert "QAT_LOG_LEVEL=INFO" not in content


def test_appends_new_keys_that_were_not_already_present(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("QAT_TRADING_MODE=paper\n", encoding="utf-8")

    update_env_file({"QAT_MARKET": "ASX"}, path=path)

    content = path.read_text(encoding="utf-8")
    assert "QAT_TRADING_MODE=paper" in content
    assert "QAT_MARKET=ASX" in content


def test_never_touches_commented_out_keys(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# QAT_MARKET=US\n", encoding="utf-8")

    update_env_file({"QAT_MARKET": "ASX"}, path=path)

    content = path.read_text(encoding="utf-8")
    assert "# QAT_MARKET=US" in content
    assert "QAT_MARKET=ASX" in content
