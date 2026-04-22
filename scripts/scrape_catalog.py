#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["paris-tennis-api"]
# [tool.uv.sources]
# paris-tennis-api = { path = "..", editable = true }
# ///
"""Scrape the tennis.paris.fr catalog anonymously and write it as JSON.

The catalog (venues, courts, surface filters, in/out codes, hour bounds) is
effectively static — it changes a few times a year at most.  Rather than
re-scraping through a logged-in Playwright browser on every /api/catalog
request (the cause of the recurring hangs), this script dumps the catalog to
data/catalog.json which the webapp then serves straight from disk.

Run locally with ``uv run scripts/scrape_catalog.py`` or via the weekly
GitHub Action that opens a PR when the file changes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from paris_tennis_api.client import ParisTennisClient

LOGGER = logging.getLogger(__name__)
OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "paris_tennis_api" / "catalog.json"
)


def main() -> int:
    """Drive an anonymous Playwright session, scrape the catalog, write JSON."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Anonymous session: empty credentials, no login required for the search
    # page which is what get_search_catalog() reads.
    with ParisTennisClient(
        email="",
        password="",
        captcha_api_key="",
        headless=True,
    ) as client:
        catalog = client.get_search_catalog(force_refresh=True)

    # `available_now` is volatile and user-irrelevant for form rendering, so
    # we strip it here — the dashboard uses it only as a hint and the actual
    # availability probe runs live against the site anyway.
    payload = {
        "venues": {
            name: {
                "venue_id": venue.venue_id,
                "name": venue.name,
                "courts": [asdict(court) for court in venue.courts],
            }
            for name, venue in catalog.venues.items()
        },
        "surface_options": dict(catalog.surface_options),
        "in_out_options": dict(catalog.in_out_options),
        "min_hour": catalog.min_hour,
        "max_hour": catalog.max_hour,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    LOGGER.info(
        "Wrote %d venues, %d surface options, %d in/out options to %s",
        len(payload["venues"]),
        len(payload["surface_options"]),
        len(payload["in_out_options"]),
        OUTPUT_PATH,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
