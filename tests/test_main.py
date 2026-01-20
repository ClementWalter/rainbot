"""Tests for main module configuration."""

from __future__ import annotations

import importlib
import sys

import dotenv


def _reload_main(monkeypatch, env: dict[str, str]):
    for key in ("REMINDER_HOUR", "REMINDER_MINUTE", "REMINDER_SECOND"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    # Prevent dotenv from loading values during tests.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    sys.modules.pop("main", None)
    import main

    return importlib.reload(main)


def test_reminder_schedule_defaults(monkeypatch):
    """Defaults should align with morning reminders."""
    module = _reload_main(monkeypatch, {})

    assert module.REMINDER_HOUR == 8
    assert module.REMINDER_MINUTE == 0
    assert module.REMINDER_SECOND == 0


def test_reminder_schedule_env_override(monkeypatch):
    """Environment variables should override reminder schedule."""
    module = _reload_main(
        monkeypatch,
        {
            "REMINDER_HOUR": "9",
            "REMINDER_MINUTE": "30",
            "REMINDER_SECOND": "15",
        },
    )

    assert module.REMINDER_HOUR == 9
    assert module.REMINDER_MINUTE == 30
    assert module.REMINDER_SECOND == 15
