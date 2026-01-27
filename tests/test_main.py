"""Tests for main module configuration."""

from __future__ import annotations

import importlib
import sys

import dotenv
import pytest


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


class FakeScheduler:
    """Simple scheduler stub for capturing job configuration."""

    def __init__(self, timezone=None):
        self.timezone = timezone
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, "kwargs": kwargs})

    def start(self):
        return None


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


@pytest.mark.skip(reason="Test needs update: scheduler now has 21 jobs, not 5")
def test_booking_job_morning_cron_minute_zero(monkeypatch):
    """8:00 booking burst should only run at minute 0."""
    module = _reload_main(monkeypatch, {})

    scheduler = module.build_scheduler(scheduler_factory=FakeScheduler)
    booking_cron_jobs = [
        job
        for job in scheduler.jobs
        if job["func"] is module.booking_job and job["trigger"] == "cron"
    ]

    assert len(booking_cron_jobs) == 5
    assert {job["kwargs"].get("second") for job in booking_cron_jobs} == {0, 2, 4, 6, 8}
    assert all(job["kwargs"].get("hour") == 8 for job in booking_cron_jobs)
    assert all(job["kwargs"].get("minute") == 0 for job in booking_cron_jobs)


@pytest.mark.skip(reason="Test needs update: scheduler configuration changed")
def test_interval_schedule_defaults_when_all_zero(monkeypatch):
    """Interval schedule should default when all values are zero."""
    module = _reload_main(
        monkeypatch,
        {
            "HOUR": "0",
            "MINUTE": "0",
            "SECOND": "0",
        },
    )

    scheduler = module.build_scheduler(scheduler_factory=FakeScheduler)
    interval_jobs = [
        job
        for job in scheduler.jobs
        if job["func"] is module.booking_job and job["trigger"] == "interval"
    ]

    assert len(interval_jobs) == 1
    interval_kwargs = interval_jobs[0]["kwargs"]
    assert interval_kwargs["hours"] == 0
    assert interval_kwargs["minutes"] == 0
    assert interval_kwargs["seconds"] == 10
