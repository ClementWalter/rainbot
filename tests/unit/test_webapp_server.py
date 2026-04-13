"""Unit tests for the webapp CLI server entrypoint."""

from __future__ import annotations

from pathlib import Path

from paris_tennis_api.webapp.server import build_parser, main
from paris_tennis_api.webapp.settings import WebAppSettings


def test_build_parser_accepts_host_and_port_flags() -> None:
    """Parser should expose explicit runtime overrides for host and port."""

    args = build_parser().parse_args(["--host", "0.0.0.0", "--port", "9000"])
    assert (args.host, args.port) == ("0.0.0.0", 9000)


def test_main_runs_uvicorn_with_cli_overrides(monkeypatch, tmp_path: Path) -> None:
    """CLI flags must override env-backed settings when launching the ASGI server."""

    captured: dict[str, object] = {}
    settings = WebAppSettings(
        database_path=tmp_path / "db.sqlite3",
        session_secret="secret",
        captcha_api_key="captcha",
        headless=True,
        host="127.0.0.1",
        port=8000,
    )

    monkeypatch.setattr(
        "paris_tennis_api.webapp.server.WebAppSettings.from_env",
        lambda: settings,
    )
    monkeypatch.setattr(
        "paris_tennis_api.webapp.server.create_app",
        lambda settings: "fake-app",
    )

    def _fake_run(app, **kwargs: object) -> None:
        # Accept arbitrary kwargs so the reload-mode call (which adds
        # `reload_dirs` and passes an import string) stays compatible.
        captured["app"] = app
        captured["host"] = kwargs.get("host")
        captured["port"] = kwargs.get("port")
        captured["reload"] = kwargs.get("reload", False)

    monkeypatch.setattr("paris_tennis_api.webapp.server.uvicorn.run", _fake_run)
    exit_code = main(argv=["--host", "0.0.0.0", "--port", "9001", "--reload"])
    # In reload mode the app target is the import-string form so uvicorn can
    # re-import it after every file change.
    assert (
        exit_code,
        captured["app"],
        captured["host"],
        captured["port"],
        captured["reload"],
    ) == (
        0,
        "paris_tennis_api.webapp.main:app",
        "0.0.0.0",
        9001,
        True,
    )


def test_main_uses_env_defaults_without_overrides(monkeypatch, tmp_path: Path) -> None:
    """Server main should keep settings values when no CLI override is provided."""

    captured: dict[str, object] = {}
    settings = WebAppSettings(
        database_path=tmp_path / "db.sqlite3",
        session_secret="secret",
        captcha_api_key="captcha",
        headless=True,
        host="127.0.0.2",
        port=8100,
    )

    monkeypatch.setattr(
        "paris_tennis_api.webapp.server.WebAppSettings.from_env",
        lambda: settings,
    )
    monkeypatch.setattr(
        "paris_tennis_api.webapp.server.create_app",
        lambda settings: "fake-app",
    )
    monkeypatch.setattr(
        "paris_tennis_api.webapp.server.uvicorn.run",
        lambda app, **kwargs: captured.update(
            {
                "host": kwargs.get("host"),
                "port": kwargs.get("port"),
                "reload": kwargs.get("reload", False),
            }
        ),
    )
    main(argv=[])
    assert (captured["host"], captured["port"], captured["reload"]) == (
        "127.0.0.2",
        8100,
        False,
    )
