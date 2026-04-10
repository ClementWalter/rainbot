"""Isolated captcha tests to debug the booking flow step by step.

Each test validates one step of the chain: login → search → captcha page → solve.
"""

from __future__ import annotations

import datetime as dt
import logging
import os

import pytest
from dotenv import load_dotenv

from paris_tennis_api.client import (
    RESERVATION_VIEW_URL,
    ParisTennisClient,
)
from paris_tennis_api.config import ParisTennisSettings
from paris_tennis_api.parsers import parse_antibot_config

logger = logging.getLogger(__name__)


@pytest.fixture()
def live_client():
    """Authenticated client with live credentials."""

    load_dotenv(".env")
    required = [
        os.getenv("PARIS_TENNIS_EMAIL"),
        os.getenv("PARIS_TENNIS_PASSWORD"),
        os.getenv("CAPTCHA_API_KEY"),
    ]
    if not all(required):
        pytest.skip("Live credentials are not configured in .env.")
    settings = ParisTennisSettings.from_env()
    with ParisTennisClient.from_settings(settings) as client:
        client.login()
        yield client


@pytest.fixture()
def first_slot_and_captcha_id(live_client: ParisTennisClient):
    """Search for the first available slot and return (slot, captcha_request_id)."""

    catalog = live_client.get_search_catalog()
    target_date = (dt.date.today() + dt.timedelta(days=2)).strftime("%d/%m/%Y")
    from paris_tennis_api.models import SearchRequest

    candidate_venues = tuple(
        name for name, venue in catalog.venues.items() if venue.available_now
    ) or tuple(catalog.venues.keys())

    for venue_name in candidate_venues:
        request = SearchRequest(
            venue_name=venue_name,
            date_iso=target_date,
            hour_start=catalog.min_hour,
            hour_end=catalog.max_hour,
            surface_ids=tuple(catalog.surface_options.keys()),
            in_out_codes=tuple(catalog.in_out_options.keys()),
        )
        result = live_client.search_slots(request)
        if result.slots:
            return result.slots[0], result.captcha_request_id

    pytest.skip("No available slots found for testing.")


@pytest.mark.e2e
def test_captcha_page_via_api_request(live_client, first_slot_and_captcha_id) -> None:
    """The API request context should retrieve a valid captcha page."""

    slot, captcha_request_id = first_slot_and_captcha_id
    response = live_client._request.post(
        RESERVATION_VIEW_URL,
        form={
            "equipmentId": slot.equipment_id,
            "courtId": slot.court_id,
            "dateDeb": slot.date_deb,
            "dateFin": slot.date_fin,
            "annulation": "false",
            "captchaRequestId": captcha_request_id,
        },
        timeout=120_000,
    )
    assert response.ok, f"POST returned {response.status}"

    html = response.text()
    logger.info("API captcha page URL: %s", response.url)
    logger.info("API captcha page length: %d", len(html))

    # The page should contain a valid LI_ANTIBOT config.
    config = parse_antibot_config(html)
    assert config.sp_key, "Missing sp_key in antibot config"
    assert config.base_url, "Missing base_url in antibot config"
    logger.info(
        "API antibot config: antibot_id=%s request_id=%s method=%s",
        config.antibot_id,
        config.request_id,
        config.method,
    )


@pytest.mark.e2e
def test_captcha_page_via_button_click(live_client, first_slot_and_captcha_id) -> None:
    """Clicking the slot button should navigate to a page with a valid captcha."""

    slot, _captcha_request_id = first_slot_and_captcha_id
    page = live_client._require_page()

    # The page should already be on search results after the fixture ran search_slots.
    logger.info("Page URL before click: %s", page.url)

    page.evaluate(
        """(data) => {
            const buttons = document.querySelectorAll('button.buttonAllOk');
            for (const btn of buttons) {
                if (btn.getAttribute('equipmentid') === data.equipmentId &&
                    btn.getAttribute('courtid') === data.courtId &&
                    btn.getAttribute('datedeb') === data.dateDeb &&
                    btn.getAttribute('datefin') === data.dateFin) {
                    btn.click();
                    return;
                }
            }
            throw new Error('No matching slot button found');
        }""",
        {
            "equipmentId": slot.equipment_id,
            "courtId": slot.court_id,
            "dateDeb": slot.date_deb,
            "dateFin": slot.date_fin,
        },
    )
    page.wait_for_url("**reservation**captcha**", timeout=120_000)
    page.wait_for_load_state("networkidle", timeout=120_000)

    logger.info("Page URL after click: %s", page.url)
    html = page.content()
    config = parse_antibot_config(html)
    assert config.sp_key, "Missing sp_key in antibot config"
    logger.info(
        "Page antibot config: antibot_id=%s request_id=%s method=%s",
        config.antibot_id,
        config.request_id,
        config.method,
    )


@pytest.mark.e2e
def test_captcha_solve_via_api_request(live_client, first_slot_and_captcha_id) -> None:
    """The captcha should be solvable using the config from the API request page."""

    slot, captcha_request_id = first_slot_and_captcha_id
    response = live_client._request.post(
        RESERVATION_VIEW_URL,
        form={
            "equipmentId": slot.equipment_id,
            "courtId": slot.court_id,
            "dateDeb": slot.date_deb,
            "dateFin": slot.date_fin,
            "annulation": "false",
            "captchaRequestId": captcha_request_id,
        },
        timeout=120_000,
    )
    assert response.ok

    html = response.text()
    config = parse_antibot_config(html)
    token = live_client._captcha_solver.solve(
        config=config,
        referer_url=response.url,
    )
    assert token.token, "Captcha token is empty"
    logger.info("Captcha solved: container_id=%s", token.container_id)


@pytest.mark.e2e
def test_captcha_solve_via_page_with_route_block(
    live_client, first_slot_and_captcha_id
) -> None:
    """Blocking the captcha API during page load keeps the request IDs fresh for our solver."""

    slot, _captcha_request_id = first_slot_and_captcha_id
    page = live_client._require_page()

    # Block LiveIdentity API so the on-page JS cannot consume the request IDs
    # before our external solver does.
    page.route("**/captcha.liveidentity.com/**", lambda route: route.abort())

    page.evaluate(
        """(data) => {
            const buttons = document.querySelectorAll('button.buttonAllOk');
            for (const btn of buttons) {
                if (btn.getAttribute('equipmentid') === data.equipmentId &&
                    btn.getAttribute('courtid') === data.courtId &&
                    btn.getAttribute('datedeb') === data.dateDeb &&
                    btn.getAttribute('datefin') === data.dateFin) {
                    btn.click();
                    return;
                }
            }
            throw new Error('No matching slot button found');
        }""",
        {
            "equipmentId": slot.equipment_id,
            "courtId": slot.court_id,
            "dateDeb": slot.date_deb,
            "dateFin": slot.date_fin,
        },
    )
    page.wait_for_url("**reservation**captcha**", timeout=120_000)
    page.wait_for_load_state("networkidle", timeout=120_000)

    # Remove the block so our solver can reach the captcha API.
    page.unroute("**/captcha.liveidentity.com/**")

    logger.info("Page URL after click: %s", page.url)
    config = parse_antibot_config(page.content())
    token = live_client._captcha_solver.solve(
        config=config,
        referer_url=page.url,
    )
    assert token.token, "Captcha token is empty"
    logger.info("Page-based captcha solved: container_id=%s", token.container_id)
