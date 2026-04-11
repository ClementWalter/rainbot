"""CLI entrypoint used to run the local Paris Tennis web application."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from typing import Sequence

import uvicorn

from paris_tennis_api.webapp.main import create_app
from paris_tennis_api.webapp.settings import WebAppSettings

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Create an explicit CLI so local execution does not depend on uvicorn import paths."""

    parser = argparse.ArgumentParser(
        prog="paris-tennis-webapp",
        description="Run the mobile-first Paris Tennis web app locally.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Override PARIS_TENNIS_WEBAPP_HOST.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override PARIS_TENNIS_WEBAPP_PORT.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logs.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the app server with env-backed defaults and optional CLI overrides."""

    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    settings = WebAppSettings.from_env()
    if args.host is not None:
        settings = replace(settings, host=args.host)
    if args.port is not None:
        settings = replace(settings, port=args.port)

    LOGGER.info(
        "Starting webapp at http://%s:%s using db=%s",
        settings.host,
        settings.port,
        settings.database_path,
    )
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.host, port=settings.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
