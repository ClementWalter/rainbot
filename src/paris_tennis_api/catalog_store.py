"""Load the static venue catalog shipped at data/catalog.json.

The catalog is scraped offline (scripts/scrape_catalog.py + weekly GitHub
Action) instead of at request time so /api/catalog and saved-search form
validation never pay Playwright+login latency.  Everything else (real slot
searches, booking) still hits the live site because that data is dynamic.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from paris_tennis_api.models import SearchCatalog, TennisCourt, TennisVenue

LOGGER = logging.getLogger(__name__)

# Ship the catalog inside the package so it cannot be shadowed by a mounted
# volume (Scaleway mounts /app/data as a volume, which would hide a sibling
# data/catalog.json baked into the image).
_DEFAULT_PATH = Path(__file__).resolve().parent / "catalog.json"


@lru_cache(maxsize=1)
def load_static_catalog(path: Path | None = None) -> SearchCatalog | None:
    """Load the JSON catalog once per process; return None if the file is absent.

    Missing file is non-fatal so a fresh checkout without a scraped catalog
    still boots — callers fall back to a generic empty payload (same shape
    as the old cache-miss response).
    """

    target = path or _DEFAULT_PATH
    if not target.is_file():
        LOGGER.warning("Static catalog %s is missing; run scripts/scrape_catalog.py", target)
        return None

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        LOGGER.error("Could not parse %s: %s", target, error)
        return None

    venues = {
        name: TennisVenue(
            venue_id=str(payload.get("venue_id", "")),
            name=str(payload.get("name", name)),
            # available_now is dynamic; the static catalog always says False
            # and the SPA ignores it (availability is probed live).
            available_now=False,
            courts=tuple(
                TennisCourt(
                    court_id=str(court.get("court_id", "")),
                    name=str(court.get("name", "")),
                )
                for court in payload.get("courts", [])
            ),
        )
        for name, payload in raw.get("venues", {}).items()
    }

    return SearchCatalog(
        venues=venues,
        # date_options is only used for stale validation paths the webapp
        # no longer relies on; leave empty so callers do not build UI off it.
        date_options=tuple(),
        surface_options=dict(raw.get("surface_options", {})),
        in_out_options=dict(raw.get("in_out_options", {})),
        min_hour=int(raw.get("min_hour", 8)),
        max_hour=int(raw.get("max_hour", 22)),
    )
