"""Where settings and records live, and how they got there (spec M22).

The bug behind this: both the .env and the data directory were resolved
relative to the process working directory, so the same installation read a
different configuration depending on how it was started - and an edit to one
copy had no effect on the other, while looking from the outside as though it
had worked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qat.config import Settings
from qat.env_file import update_env_file
from qat.migration import migrate_legacy_layout
from qat.paths import APP_DIRNAME, HOME_ENV_VAR, app_dir, data_dir, env_path


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    target = tmp_path / "home"
    monkeypatch.setenv(HOME_ENV_VAR, str(target))
    # conftest pins QAT_DATA_DIR for the whole session; these tests are about
    # what the DEFAULT resolves to, so the override has to come off.
    monkeypatch.delenv("QAT_DATA_DIR", raising=False)
    return target


# --- resolution --------------------------------------------------------------


def test_the_app_directory_is_absolute(home):
    assert app_dir().is_absolute()
    assert env_path() == home / ".env"
    assert data_dir() == home / "data"


def test_the_app_directory_does_not_depend_on_the_working_directory(home, tmp_path, monkeypatch):
    """The whole point. Launched from two places, the same install must read
    the same configuration."""
    first = app_dir()
    monkeypatch.chdir(tmp_path)
    second = app_dir()

    assert first == second


def test_without_an_override_it_lands_under_the_user_profile(monkeypatch):
    monkeypatch.delenv(HOME_ENV_VAR, raising=False)

    resolved = app_dir()

    assert resolved.name == APP_DIRNAME
    assert resolved.is_absolute()


def test_settings_default_to_the_app_data_directory(home):
    settings = Settings(_env_file=None)

    assert Path(settings.data_dir) == data_dir()


def test_the_env_writer_defaults_to_the_app_directory(home):
    update_env_file({"QAT_MARKET": "US"})

    assert env_path().is_file()
    assert "QAT_MARKET=US" in env_path().read_text(encoding="utf-8")


def test_the_env_writer_creates_the_directory_if_it_is_missing(home):
    assert not home.exists()

    update_env_file({"QAT_MARKET": "US"})

    assert env_path().is_file()


# --- migration ---------------------------------------------------------------


def _legacy(root: Path) -> Path:
    """A pre-M22 layout: a .env and a data directory beside the executable."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".env").write_text("QAT_MARKET=US\nQAT_WATCHLIST_MAX_SYMBOLS=12\n", encoding="utf-8")
    data = root / "data"
    (data / "logs").mkdir(parents=True)
    (data / "closed_trades.csv").write_text("symbol,pnl\nAAPL,12.5\n", encoding="utf-8")
    (data / "decision_journal.csv").write_text("order_id\n1\n", encoding="utf-8")
    (data / "logs" / "qat.log").write_text('{"message":"hi"}\n', encoding="utf-8")
    return root


def test_a_legacy_layout_is_brought_across(home, tmp_path):
    origin = _legacy(tmp_path / "old")

    result = migrate_legacy_layout(origin)

    assert result.did_anything
    assert env_path().read_text(encoding="utf-8").startswith("QAT_MARKET=US")
    assert (data_dir() / "closed_trades.csv").is_file()
    assert (data_dir() / "logs" / "qat.log").is_file()
    assert set(result.files_copied) == {
        "closed_trades.csv",
        "decision_journal.csv",
        str(Path("logs") / "qat.log"),
    }


def test_the_originals_are_copied_not_moved(home, tmp_path):
    """This runs automatically at startup without asking. Removing a file the
    operator did not know was about to be touched is data loss with a helpful
    name."""
    origin = _legacy(tmp_path / "old")

    migrate_legacy_layout(origin)

    assert (origin / ".env").is_file()
    assert (origin / "data" / "closed_trades.csv").is_file()


def test_an_existing_destination_file_is_never_overwritten(home, tmp_path):
    """If the destination has it, that is the live copy and this is a stray."""
    origin = _legacy(tmp_path / "old")
    data_dir().mkdir(parents=True)
    (data_dir() / "closed_trades.csv").write_text("KEEP ME\n", encoding="utf-8")

    result = migrate_legacy_layout(origin)

    assert (data_dir() / "closed_trades.csv").read_text(encoding="utf-8") == "KEEP ME\n"
    assert "closed_trades.csv" in result.skipped_existing


def test_an_existing_env_is_never_overwritten(home, tmp_path):
    origin = _legacy(tmp_path / "old")
    home.mkdir(parents=True)
    env_path().write_text("QAT_MARKET=ASX\n", encoding="utf-8")

    result = migrate_legacy_layout(origin)

    assert env_path().read_text(encoding="utf-8") == "QAT_MARKET=ASX\n"
    assert result.env_migrated_from is None


def test_nothing_to_migrate_is_reported_as_such(home, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = migrate_legacy_layout(empty)

    assert result.did_anything is False
    assert "No migration needed" in result.summary_line()


def test_migrating_from_the_app_directory_itself_is_a_no_op(home):
    home.mkdir(parents=True)
    env_path().write_text("QAT_MARKET=US\n", encoding="utf-8")

    result = migrate_legacy_layout(home)

    assert result.did_anything is False


def test_a_second_run_migrates_nothing_further(home, tmp_path):
    origin = _legacy(tmp_path / "old")
    migrate_legacy_layout(origin)

    second = migrate_legacy_layout(origin)

    assert second.files_copied == []
    assert second.env_migrated_from is None


def test_the_summary_names_the_destination(home, tmp_path):
    origin = _legacy(tmp_path / "old")

    summary = migrate_legacy_layout(origin).summary_line()

    assert str(app_dir()) in summary
    assert "settings from" in summary


def test_migrated_settings_are_actually_read_back(home, tmp_path):
    """The migration is worthless if the values do not then load."""
    origin = _legacy(tmp_path / "old")
    migrate_legacy_layout(origin)

    settings = Settings()

    assert settings.watchlist_max_symbols == 12


def test_the_home_override_wins_over_the_platform_default(tmp_path, monkeypatch):
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path / "portable"))

    assert app_dir() == tmp_path / "portable"


def test_a_user_relative_override_is_expanded(monkeypatch):
    monkeypatch.setenv(HOME_ENV_VAR, "~/qat-portable")

    assert "~" not in str(app_dir())
    assert app_dir().is_absolute()


def test_the_test_suite_itself_is_isolated():
    """conftest points QAT_HOME at a temporary directory; without it this
    suite would read and write the operator's real settings."""
    assert os.environ.get(HOME_ENV_VAR)
