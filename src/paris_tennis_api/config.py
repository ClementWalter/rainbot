"""Environment-based settings for the Paris Tennis API client."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from paris_tennis_api.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class ParisTennisSettings:
    """Runtime settings loaded from environment variables."""

    email: str
    password: str
    captcha_api_key: str
    headless: bool = True

    @classmethod
    def from_env(cls) -> "ParisTennisSettings":
        """Load settings from `.env` first so local development is reproducible."""

        load_dotenv(".env")
        email = os.getenv("PARIS_TENNIS_EMAIL", "").strip()
        password = os.getenv("PARIS_TENNIS_PASSWORD", "").strip()
        captcha_api_key = os.getenv("CAPTCHA_API_KEY", "").strip()
        headless_str = os.getenv("PARIS_TENNIS_HEADLESS", "true").strip().lower()
        if not email:
            raise ValidationError("Missing PARIS_TENNIS_EMAIL.")
        if not password:
            raise ValidationError("Missing PARIS_TENNIS_PASSWORD.")
        if not captcha_api_key:
            raise ValidationError("Missing CAPTCHA_API_KEY.")
        headless = headless_str not in {"0", "false", "no"}
        return cls(
            email=email,
            password=password,
            captcha_api_key=captcha_api_key,
            headless=headless,
        )
