"""Configuration settings loaded from environment variables."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class SchedulerConfig:
    """Scheduler timing configuration."""

    hour: int
    minute: int
    second: int
    jitter: int


@dataclass
class CaptchaConfig:
    """2Captcha service configuration."""

    api_key: str


@dataclass
class GoogleSheetsConfig:
    """Google Sheets configuration."""

    credentials_file: str
    spreadsheet_id: str


@dataclass
class ParisTennisConfig:
    """Paris Tennis website configuration."""

    base_url: str
    login_url: str
    search_url: str


@dataclass
class NotificationConfig:
    """Notification service configuration."""

    smtp_host: Optional[str]
    smtp_port: Optional[int]
    smtp_user: Optional[str]
    smtp_password: Optional[str]
    from_email: Optional[str]


@dataclass
class Settings:
    """Application settings."""

    scheduler: SchedulerConfig
    captcha: CaptchaConfig
    google_sheets: GoogleSheetsConfig
    paris_tennis: ParisTennisConfig
    notification: NotificationConfig
    debug: bool


def load_settings() -> Settings:
    """Load settings from environment variables."""
    return Settings(
        scheduler=SchedulerConfig(
            hour=int(os.getenv("HOUR", "0")),
            minute=int(os.getenv("MINUTE", "0")),
            second=int(os.getenv("SECOND", "10")),
            jitter=int(os.getenv("JITTER", "0")),
        ),
        captcha=CaptchaConfig(
            api_key=os.getenv("CAPTCHA_API_KEY", ""),
        ),
        google_sheets=GoogleSheetsConfig(
            credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
            spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID", ""),
        ),
        paris_tennis=ParisTennisConfig(
            base_url=os.getenv("PARIS_TENNIS_BASE_URL", "https://tennis.paris.fr"),
            login_url=os.getenv(
                "PARIS_TENNIS_LOGIN_URL",
                "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=authentification",
            ),
            search_url=os.getenv(
                "PARIS_TENNIS_SEARCH_URL",
                "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche",
            ),
        ),
        notification=NotificationConfig(
            smtp_host=os.getenv("SMTP_HOST"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else None,
            smtp_user=os.getenv("SMTP_USER"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            from_email=os.getenv("FROM_EMAIL"),
        ),
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )


# Global settings instance
settings = load_settings()
