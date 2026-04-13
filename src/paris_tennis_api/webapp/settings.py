"""Runtime settings for the local Paris Tennis web application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class WebAppSettings:
    """Environment-backed settings so local runs and deployment use the same knobs."""

    database_path: Path
    session_secret: str
    captcha_api_key: str
    headless: bool
    host: str
    port: int
    timezone: str = "Europe/Paris"
    # Catalog TTL governs how often we re-hit tennis.paris.fr to refresh venue
    # options. 10 minutes keeps the dashboard feeling live without paying the
    # full login+navigate cost on every request.
    catalog_ttl_seconds: int = 600
    # The warmer pre-populates per-user catalog caches on startup so the first
    # /searches request doesn't wear the login latency.  Tests disable this.
    warm_on_startup: bool = True

    @classmethod
    def from_env(cls) -> "WebAppSettings":
        """Load settings from env with safe local defaults for low-maintenance setup."""

        project_root = _discover_project_root()
        # Anchor dotenv loading to the repository so startup is not tied to process CWD.
        load_dotenv(project_root / ".env")
        database_path = _resolve_database_path(
            raw_value=os.getenv("PARIS_TENNIS_WEBAPP_DB", ""),
            project_root=project_root,
        )
        # The app auto-creates the parent directory so first boot stays frictionless.
        database_path.parent.mkdir(parents=True, exist_ok=True)

        session_secret = os.getenv("PARIS_TENNIS_WEBAPP_SESSION_SECRET", "dev-session")
        captcha_api_key = _first_non_empty_env(
            "PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY",
            "PARIS_TENNIS_CAPTCHA_API_KEY",
            "CAPTCHA_API_KEY",
        )
        headless = os.getenv(
            "PARIS_TENNIS_WEBAPP_HEADLESS", os.getenv("PARIS_TENNIS_HEADLESS", "true")
        ).strip().lower() not in {"0", "false", "no"}
        host = os.getenv("PARIS_TENNIS_WEBAPP_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port_raw = os.getenv("PARIS_TENNIS_WEBAPP_PORT", "8000").strip()
        port = int(port_raw) if port_raw.isdigit() else 8000
        timezone = os.getenv("PARIS_TENNIS_WEBAPP_TIMEZONE", "Europe/Paris").strip()
        timezone = timezone or "Europe/Paris"
        catalog_ttl_raw = os.getenv("PARIS_TENNIS_WEBAPP_CATALOG_TTL_SECONDS", "").strip()
        catalog_ttl_seconds = (
            int(catalog_ttl_raw) if catalog_ttl_raw.isdigit() else 600
        )
        warm_raw = os.getenv("PARIS_TENNIS_WEBAPP_WARM_ON_STARTUP", "true")
        warm_on_startup = warm_raw.strip().lower() not in {"0", "false", "no"}

        return cls(
            database_path=database_path,
            session_secret=session_secret,
            captcha_api_key=captcha_api_key,
            headless=headless,
            host=host,
            port=port,
            timezone=timezone,
            catalog_ttl_seconds=catalog_ttl_seconds,
            warm_on_startup=warm_on_startup,
        )


def _first_non_empty_env(*keys: str) -> str:
    """Return the first non-empty env value so deployments can rename secrets safely."""

    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _discover_project_root() -> Path:
    """Find repository root once so config loading stays stable across launch contexts."""

    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return module_path.parent


def _resolve_database_path(*, raw_value: str, project_root: Path) -> Path:
    """Resolve relative DB paths against project root to avoid CWD-dependent storage."""

    value = raw_value.strip() or "data/paris_tennis_webapp.sqlite3"
    database_path = Path(value)
    if database_path.is_absolute():
        return database_path
    return project_root / database_path
