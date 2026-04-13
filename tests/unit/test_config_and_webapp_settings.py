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

    monkeypatch.setattr(
        "paris_tennis_api.config.load_dotenv", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "paris_tennis_api.webapp.settings.load_dotenv", lambda *_args, **_kwargs: None
    )


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


def test_webapp_settings_uses_legacy_webapp_captcha_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy env aliases should keep old deployments working after config refactors."""

    monkeypatch.delenv("PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY", raising=False)
    monkeypatch.delenv("CAPTCHA_API_KEY", raising=False)
    monkeypatch.setenv("PARIS_TENNIS_CAPTCHA_API_KEY", "legacy-key")
    settings = WebAppSettings.from_env()
    assert settings.captcha_api_key == "legacy-key"


def test_webapp_settings_strips_whitespace_captcha_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only captcha values must normalize to empty so UI state is accurate."""

    monkeypatch.delenv("PARIS_TENNIS_CAPTCHA_API_KEY", raising=False)
    monkeypatch.delenv("CAPTCHA_API_KEY", raising=False)
    monkeypatch.setenv("PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY", "  \n\t")
    settings = WebAppSettings.from_env()
    assert settings.captcha_api_key == ""


def test_webapp_settings_invalid_port_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid port values should keep default 8000 instead of crashing startup."""

    monkeypatch.setenv("PARIS_TENNIS_WEBAPP_PORT", "abc")
    settings = WebAppSettings.from_env()
    assert settings.port == 8000


def test_webapp_settings_loads_dotenv_from_project_root_when_cwd_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dotenv path should stay repository-anchored so startup is independent from CWD."""

    observed_dotenv_paths: list[Path] = []

    def _capture_load_dotenv(
        dotenv_path: str | Path, *_args: object, **_kwargs: object
    ) -> None:
        observed_dotenv_paths.append(Path(dotenv_path))

    monkeypatch.setattr(
        "paris_tennis_api.webapp.settings.load_dotenv",
        _capture_load_dotenv,
    )
    monkeypatch.chdir(tmp_path)
    WebAppSettings.from_env()
    assert observed_dotenv_paths[0] == Path(__file__).resolve().parents[2] / ".env"


def test_webapp_settings_default_database_path_is_project_anchored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default DB location should not drift when service processes start from other CWDs."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PARIS_TENNIS_WEBAPP_DB", raising=False)
    settings = WebAppSettings.from_env()
    assert settings.database_path == (
        Path(__file__).resolve().parents[2] / "data" / "paris_tennis_webapp.sqlite3"
    )


def test_webapp_settings_reads_catalog_ttl_seconds_env_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators should be able to tune the catalog TTL via env without a code change."""

    monkeypatch.setenv("PARIS_TENNIS_WEBAPP_CATALOG_TTL_SECONDS", "120")
    settings = WebAppSettings.from_env()
    assert settings.catalog_ttl_seconds == 120


def test_webapp_settings_warm_on_startup_can_be_disabled_via_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warmer must be opt-out so headless deployments without users skip it cleanly."""

    monkeypatch.setenv("PARIS_TENNIS_WEBAPP_WARM_ON_STARTUP", "false")
    settings = WebAppSettings.from_env()
    assert settings.warm_on_startup is False
