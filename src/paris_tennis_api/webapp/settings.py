"""Runtime settings for the local Paris Tennis web application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WebAppSettings:
    """Environment-backed settings so local runs and deployment use the same knobs."""

    database_path: Path
    session_secret: str
    captcha_api_key: str
    headless: bool
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "WebAppSettings":
        """Load settings from env with safe local defaults for low-maintenance setup."""

        database_path = Path(
            os.getenv("PARIS_TENNIS_WEBAPP_DB", "data/paris_tennis_webapp.sqlite3")
        )
        # The app auto-creates the parent directory so first boot stays frictionless.
        database_path.parent.mkdir(parents=True, exist_ok=True)

        session_secret = os.getenv("PARIS_TENNIS_WEBAPP_SESSION_SECRET", "dev-session")
        captcha_api_key = os.getenv(
            "PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY", os.getenv("CAPTCHA_API_KEY", "")
        )
        headless = os.getenv(
            "PARIS_TENNIS_WEBAPP_HEADLESS", os.getenv("PARIS_TENNIS_HEADLESS", "true")
        ).strip().lower() not in {"0", "false", "no"}
        host = os.getenv("PARIS_TENNIS_WEBAPP_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port_raw = os.getenv("PARIS_TENNIS_WEBAPP_PORT", "8000").strip()
        port = int(port_raw) if port_raw.isdigit() else 8000

        return cls(
            database_path=database_path,
            session_secret=session_secret,
            captcha_api_key=captcha_api_key,
            headless=headless,
            host=host,
            port=port,
        )
