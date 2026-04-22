"""Pure-HTTP availability probe for tennis.paris.fr — no browser, no login.

The /api/searches/{id}/check-availability endpoint and the scheduler's
anonymous probe previously booted a Playwright Chromium to submit the
recherche_creneau form.  That was the main cold-start hazard and the
reason ``/api/catalog``-class requests hung when a browser session got
stuck.

The form is a plain application/x-www-form-urlencoded POST against a JSP
endpoint; a GET to the search page primes JSESSIONID and that's all the
server requires for anonymous availability queries.  The existing
``parse_search_result`` already handles the anonymous rendering (cards
under ``<h4 class="panel-title">`` hour headings), so this module stays
thin: make two HTTP requests, hand the HTML to the parser, return the
same ``SearchResult`` dataclass every other caller expects.

Playwright is still required for the booking submit (captcha) and the
authenticated profile pages.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from paris_tennis_api.models import SearchRequest, SearchResult
from paris_tennis_api.parsers import parse_search_result

LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://tennis.paris.fr"
_SEARCH_URL = (
    f"{_BASE_URL}/tennis/jsp/site/Portal.jsp"
    "?page=recherche&view=rechercher_creneau"
)
# The site expects the POST to the same URL it came from, with Referer set
# to the same page using the ``action=`` variant — copied from a real
# browser session so the WAF does not flag the request.
_SEARCH_REFERER = (
    f"{_BASE_URL}/tennis/jsp/site/Portal.jsp"
    "?page=recherche&action=rechercher_creneau"
)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT_SECONDS = 20.0


def probe_availability(request: SearchRequest) -> SearchResult:
    """Run one anonymous search and return parsed slots — no login.

    Constructs its own short-lived httpx Client per call because the
    server does not require a long-lived session: one GET primes
    cookies, one POST returns the slots, and we're done.  Building the
    client per call keeps the function pure (no shared state to reset)
    and is still sub-second end-to-end.
    """

    form_pairs: list[tuple[str, str]] = [
        ("page", "recherche"),
        ("action", "rechercher_creneau"),
        ("hourRange", f"{request.hour_start}-{request.hour_end}"),
        ("selWhereTennisName", request.venue_name),
        ("when", request.date_iso),
    ]
    # Multi-select fields must be sent as repeated keys, which urlencode
    # produces via doseq=True when given a list-of-pairs.
    form_pairs.extend(("selCoating", value) for value in request.surface_ids)
    form_pairs.extend(("selInOut", value) for value in request.in_out_codes)

    with httpx.Client(
        http2=False,
        follow_redirects=True,
        timeout=_REQUEST_TIMEOUT_SECONDS,
        headers={
            "user-agent": _USER_AGENT,
            "accept-language": "en-US,en;q=0.9,fr;q=0.8",
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        },
    ) as client:
        # Prime JSESSIONID — the POST below 302s to login if the server
        # has never seen this client.
        client.get(_SEARCH_URL)
        response = client.post(
            _SEARCH_URL,
            content=urlencode(form_pairs, doseq=True),
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "origin": _BASE_URL,
                "referer": _SEARCH_REFERER,
            },
        )
        response.raise_for_status()

    LOGGER.debug(
        "Availability probe venue=%s date=%s hours=%s-%s -> %d bytes",
        request.venue_name,
        request.date_iso,
        request.hour_start,
        request.hour_end,
        len(response.content),
    )
    return parse_search_result(response.text)
