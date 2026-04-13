"""Unit tests for environment-backed settings loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from paris_tennis_api.config import ParisTennisSettings
from paris_tennis_api.exceptions import ValidationError
from paris_tennis_api.webapp.settings import WebAppSettings


@pytest.fixture(autouse=True)
def _disable_env_file_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable `.env` reads so each test can control env vars deterministically."""

    monkeypatch.setattr("paris_tennis_api.config.load_dotenv", lambda *_args, **_kwargs: None)


def test_paris_tennis_settings_reads_expected_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings should mirror explicit env values for deterministic runtime behavior."""

    monkeypatch.setenv("PARIS_TENNIS_EMAIL", "user@example.com")
    monkeypatch.setenv("PARIS_TENNIS_PASSWORD", "secret")
    monkeypatch.setenv("CAPTCHA_API_KEY", "captcha-key")
    monkeypatch.setenv("PARIS_TENNIS_HEADLESS", "false")
    settings = ParisTennisSettings.from_env()
    assert settings.headless is False


def test_paris_tennis_settings_requires_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Email is mandatory because login automation cannot proceed without it."""

    monkeypatch.delenv("PARIS_TENNIS_EMAIL", raising=False)
    monkeypatch.setenv("PARIS_TENNIS_PASSWORD", "secret")
    monkeypatch.setenv("CAPTCHA_API_KEY", "captcha-key")
    with pytest.raises(ValidationError):
        ParisTennisSettings.from_env()


def test_paris_tennis_settings_requires_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Password is required to avoid late failures in the browser login flow."""

    monkeypatch.setenv("PARIS_TENNIS_EMAIL", "user@example.com")
    monkeypatch.delenv("PARIS_TENNIS_PASSWORD", raising=False)
    monkeypatch.setenv("CAPTCHA_API_KEY", "captcha-key")
    with pytest.raises(ValidationError):
        ParisTennisSettings.from_env()


def test_paris_tennis_settings_requires_captcha_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Captcha key should fail fast so booking code does not start in invalid state."""

    monkeypatch.setenv("PARIS_TENNIS_EMAIL", "user@example.com")
    monkeypatch.setenv("PARIS_TENNIS_PASSWORD", "secret")
    monkeypatch.delenv("CAPTCHA_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        ParisTennisSettings.from_env()


def test_webapp_settings_create_database_parent_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Database parent directory should be auto-created to keep first boot frictionless."""

    db_path = tmp_path / "nested" / "webapp.sqlite3"
    monkeypatch.setenv("PARIS_TENNIS_WEBAPP_DB", str(db_path))
    settings = WebAppSettings.from_env()
    assert settings.database_path.parent.exists() is True


def test_webapp_settings_falls_back_to_global_captcha_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global captcha key fallback avoids duplicated env config between CLI and webapp."""

    monkeypatch.delenv("PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY", raising=False)
    monkeypatch.setenv("CAPTCHA_API_KEY", "fallback-key")
    settings = WebAppSettings.from_env()
    assert settings.captcha_api_key == "fallback-key"


def test_webapp_settings_invalid_port_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid port values should keep default 8000 instead of crashing startup."""

    monkeypatch.setenv("PARIS_TENNIS_WEBAPP_PORT", "abc")
    settings = WebAppSettings.from_env()
    assert settings.port == 8000
