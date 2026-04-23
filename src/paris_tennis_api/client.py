"""High-level API client for tennis.paris.fr using a browser-backed session."""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from paris_tennis_api.captcha import AntiBotSolver
from paris_tennis_api.config import ParisTennisSettings
from paris_tennis_api.exceptions import AuthenticationError, BookingError
from paris_tennis_api.models import (
    BookedReservation,
    ProfileTab,
    ReservationSummary,
    SearchCatalog,
    SearchRequest,
    SearchResult,
    SlotOffer,
    TicketAvailabilitySummary,
)
from paris_tennis_api.parsers import (
    parse_antibot_config,
    parse_profile_reservation,
    parse_search_catalog,
    parse_search_result,
    parse_ticket_availability,
)

BASE_URL = "https://tennis.paris.fr/tennis/"
AUTH_URL = (
    "https://v70-auth.paris.fr/auth/realms/paris/protocol/openid-connect/auth?"
    "client_id=T23-PR&response_type=code&redirect_uri="
    "https%3A%2F%2Ftennis.paris.fr%2Ftennis%2Fservlet%2Fplugins%2Foauth2%2Fcallback"
    "%3Fdata_client%3DauthData&scope=openid"
)
SEARCH_URL = urljoin(
    BASE_URL, "jsp/site/Portal.jsp?page=recherche&view=recherche_creneau"
)
SEARCH_ACTION_URL = urljoin(
    BASE_URL,
    "jsp/site/Portal.jsp?page=recherche&action=rechercher_creneau",
)
RESERVATION_VIEW_URL = urljoin(
    BASE_URL,
    "jsp/site/Portal.jsp?page=reservation&view=reservation_captcha",
)
RESERVATION_ACTION_URL = urljoin(
    BASE_URL,
    "jsp/site/Portal.jsp?page=reservation&action=reservation_captcha",
)
MA_RESERVATION_URL = urljoin(BASE_URL, ProfileTab.MA_RESERVATION.value)


def _resolve_debug_dir(debug_dir: str | Path | None) -> Path | None:
    """Return the directory to write failure snapshots to, or None to disable.

    Explicit constructor arg wins; else ``PARIS_TENNIS_DEBUG_DIR`` env var;
    else None so local dev doesn't litter the repo with dumps.  Production
    (Fly/Scaleway) sets the env to a path on the mounted data volume so
    snapshots survive container restarts and can be reviewed after the fact.
    """

    if debug_dir is not None:
        return Path(debug_dir)
    env_value = os.environ.get("PARIS_TENNIS_DEBUG_DIR", "").strip()
    if env_value:
        return Path(env_value)
    return None


class ParisTennisClient:
    """Browser-backed API client with local validation before booking operations."""

    def __init__(
        self,
        email: str,
        password: str,
        captcha_api_key: str,
        *,
        headless: bool = True,
        logger: logging.Logger | None = None,
        debug_dir: str | Path | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._headless = headless
        self._logger = logger or logging.getLogger(__name__)
        # Dumps land on the Fly/Scaleway data volume so they survive container
        # restarts: that is the only way to review what the browser saw when
        # a booking fails at 08:00:13 and the user reads the logs later.
        self._debug_dir = _resolve_debug_dir(debug_dir)

        self._captcha_solver = AntiBotSolver(
            captcha_api_key=captcha_api_key, logger=self._logger
        )

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        self._catalog_cache: SearchCatalog | None = None
        self._is_authenticated = False

    @classmethod
    def from_settings(cls, settings: ParisTennisSettings) -> "ParisTennisClient":
        """Create a client from `.env`-backed settings."""

        return cls(
            email=settings.email,
            password=settings.password,
            captcha_api_key=settings.captcha_api_key,
            headless=settings.headless,
        )

    def __enter__(self) -> "ParisTennisClient":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def open(self) -> None:
        """Start the browser context once so all calls share one authenticated session."""

        if self._page is not None:
            return
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

    def close(self) -> None:
        """Close browser resources cleanly to avoid leaking local processes."""

        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def _request(self):
        """Expose the BrowserContext API request context for direct HTTP calls."""

        self.open()
        if self._context is None:
            raise RuntimeError("Browser context was not initialized.")
        return self._context.request

    def login(self) -> None:
        """Authenticate using the same flow as the real login form."""

        try:
            page = self._require_page()
            response = page.goto(
                AUTH_URL, wait_until="domcontentloaded", timeout=120_000
            )
            if response is not None and response.status >= 400:
                raise AuthenticationError(
                    f"Login entrypoint returned HTTP {response.status}."
                )

            if page.locator("#username").count() == 0:
                raise AuthenticationError("Login page did not expose username input.")

            page.fill("#username", self._email)
            page.fill("#password", self._password)
            page.locator("form#form-login button[type='submit']").click()

            page.wait_for_url("**tennis.paris.fr/tennis/**", timeout=120_000)
            self._is_authenticated = True

            page.goto(MA_RESERVATION_URL, wait_until="networkidle", timeout=120_000)
            profile_html = page.content()
            summary = parse_profile_reservation(profile_html)
            if not summary.raw_text:
                raise AuthenticationError(
                    "Could not validate authenticated profile session."
                )
        except Exception as error:
            # Dump before re-raising so the user can inspect what the browser
            # saw at the moment login broke — URL alone isn't enough.
            self._dump_debug(f"login_{type(error).__name__}")
            raise

    def get_search_catalog(self, *, force_refresh: bool = False) -> SearchCatalog:
        """Return catalog metadata used to validate search input locally."""

        if self._catalog_cache is not None and not force_refresh:
            return self._catalog_cache

        page = self._require_page()
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=120_000)

        # The server redirects to the booking wizard when a previous flow was
        # left incomplete.  Walk through it and abort to free the session.
        if "recherche" not in page.url:
            self._logger.info(
                "Search blocked by pending booking at %s — clearing.", page.url
            )
            self._clear_pending_booking()
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=120_000)

        catalog = parse_search_catalog(page.content())
        self._catalog_cache = catalog
        return catalog

    def search_slots(self, request: SearchRequest) -> SearchResult:
        """Search slots after validating options against scraped catalog metadata.

        Works without login for anonymous availability polling (returns empty
        ``slots`` but confirms the venue/date exists).  Bookable slot details
        and ``captcha_request_id`` are only populated for authenticated sessions.
        """

        try:
            return self._search_slots_impl(request)
        except Exception as error:
            self._dump_debug(f"search_slots_{type(error).__name__}")
            raise

    def _search_slots_impl(self, request: SearchRequest) -> SearchResult:
        catalog = self.get_search_catalog()
        request.validate(catalog)

        page = self._require_page()
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=120_000)

        # The server redirects to the booking wizard when a previous flow was
        # left incomplete (e.g. the last booking bailed at the payment step).
        # Walk through it and abort so retries land on a fresh search page
        # instead of crashing in page.evaluate with "null" form elements.
        if "recherche" not in page.url:
            self._logger.info(
                "Search blocked by pending booking at %s — clearing.", page.url
            )
            self._clear_pending_booking()
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=120_000)

        payload = {
            "venueName": request.venue_name,
            "dateIso": request.date_iso,
            "hourRange": f"{request.hour_start}-{request.hour_end}",
            "surfaceIds": list(request.surface_ids),
            "inOutCodes": list(request.in_out_codes),
        }

        # We submit through the existing form because the site stores extra search context in JS state.
        page.evaluate(
            """(data) => {
                const setSingleOption = (selectId, value) => {
                    const select = document.getElementById(selectId);
                    select.innerHTML = "";
                    const option = document.createElement("option");
                    option.value = value;
                    option.text = value;
                    option.selected = true;
                    select.appendChild(option);
                };

                setSingleOption("selWhereTennisName", data.venueName);
                const whereInput = document.getElementById("where");
                if (whereInput) {
                    whereInput.value = data.venueName;
                }
                document.getElementById("whenIso").value = data.dateIso;
                document.getElementById("hourRange").value = data.hourRange;

                document.querySelectorAll("input[name='selCoating']").forEach((checkbox) => {
                    checkbox.checked = data.surfaceIds.includes(checkbox.value);
                });
                document.querySelectorAll("input[name='selInOut']").forEach((checkbox) => {
                    checkbox.checked = data.inOutCodes.includes(checkbox.value);
                });

                document.getElementById("search_form").submit();
            }""",
            payload,
        )

        page.wait_for_url("**action=rechercher_creneau**", timeout=120_000)
        return parse_search_result(page.content())

    def book_slot(self, slot: SlotOffer, captcha_request_id: str) -> str:
        """Book a slot by driving the page through the full browser flow.

        The booking wizard has four phases:
        1. Captcha verification
        2. Court validation (fill partner name)
        3. Payment method (select prepaid ticket)
        4. Confirmation
        """

        try:
            return self._book_slot_impl(slot, captcha_request_id)
        except Exception as error:
            self._dump_debug(f"book_slot_{type(error).__name__}")
            raise

    def _book_slot_impl(
        self, slot: SlotOffer, captcha_request_id: str
    ) -> str:
        self._require_authenticated()
        if not captcha_request_id.strip():
            # We keep this explicit guard even if the browser click flow can
            # still navigate, because missing request IDs usually signal a
            # stale/anonymous search result that should not be booked.
            raise BookingError("captcha_request_id is required for booking.")
        page = self._require_page()

        # Log the exact slot we are about to book so post-mortems can correlate
        # booking attempts with search-result logs even when the flow fails.
        self._logger.info("Booking slot: %s", asdict(slot))

        # Block LiveIdentity API while the page navigates so the on-page JS
        # cannot consume the captcha request IDs before our external solver.
        page.route("**/captcha.liveidentity.com/**", lambda route: route.abort())

        # Phase 1 — click the slot button to start the booking flow.
        # We prefer the exact slot the caller chose so logs stay honest, but
        # fall back to any bookable button on the page.  The results DOM can
        # mutate between parse and click (site JS removes expired rows); by
        # this point the probe already confirmed something is open, so
        # clicking whatever is still there is strictly better than bailing.
        clicked = page.evaluate(
            """(data) => {
                const buttons = Array.from(
                    document.querySelectorAll('button.buttonAllOk')
                );
                const exact = buttons.find((btn) =>
                    btn.getAttribute('equipmentid') === data.equipmentId &&
                    btn.getAttribute('courtid') === data.courtId &&
                    btn.getAttribute('datedeb') === data.dateDeb &&
                    btn.getAttribute('datefin') === data.dateFin
                );
                const chosen = exact || buttons[0];
                if (!chosen) {
                    throw new Error(
                        'No bookable button on search results page'
                    );
                }
                chosen.click();
                return {
                    matchedExact: Boolean(exact),
                    equipmentId: chosen.getAttribute('equipmentid'),
                    courtId: chosen.getAttribute('courtid'),
                    dateDeb: chosen.getAttribute('datedeb'),
                    dateFin: chosen.getAttribute('datefin'),
                };
            }""",
            {
                "equipmentId": slot.equipment_id,
                "courtId": slot.court_id,
                "dateDeb": slot.date_deb,
                "dateFin": slot.date_fin,
            },
        )
        self._logger.info("Phase 1 clicked button: %s", clicked)
        page.wait_for_url("**reservation**captcha**", timeout=120_000)
        page.wait_for_load_state("networkidle", timeout=120_000)
        page.unroute("**/captcha.liveidentity.com/**")

        # Phase 2 — solve the captcha.
        captcha_html = page.content()
        config = parse_antibot_config(captcha_html)
        anti_bot_token = self._captcha_solver.solve(
            config=config,
            referer_url=page.url,
        )

        with page.expect_navigation(wait_until="networkidle", timeout=120_000):
            page.evaluate(
                """(data) => {
                    const container = document.getElementById(data.containerId);
                    const form = container
                        ? container.closest('form')
                        : document.querySelector('form');
                    if (!form) throw new Error('No form found on captcha page');

                    const setField = (name, value) => {
                        let el = form.querySelector('input[name="' + name + '"]');
                        if (!el) {
                            el = document.createElement('input');
                            el.type = 'hidden';
                            el.name = name;
                            form.appendChild(el);
                        }
                        el.value = value;
                    };

                    setField(data.tokenName, data.token);
                    setField(data.tokenCodeName, data.tokenCode);
                    setField('submitControle', 'submit');
                    form.submit();
                }""",
                {
                    "containerId": anti_bot_token.container_id,
                    "tokenName": f"{anti_bot_token.container_id}-token",
                    "tokenCodeName": f"{anti_bot_token.container_id}-token-code",
                    "token": anti_bot_token.token,
                    "tokenCode": anti_bot_token.token_code,
                },
            )

        # Phase 3 — court validation: fill partner identity and advance.
        self._submit_validation_step()

        # Phase 4 — payment: select prepaid ticket card and confirm.
        self._submit_payment_step()

        response_html = page.content()
        self._logger.info("Booking final URL: %s", page.url)
        return response_html

    def get_profile_tab(self, tab: ProfileTab) -> str:
        """Return raw HTML for one profile tab to support future CLI/App formatting."""

        self._require_authenticated()
        page = self._require_page()
        page.goto(
            urljoin(BASE_URL, tab.value), wait_until="networkidle", timeout=120_000
        )
        return page.content()

    def get_all_profile_tabs(self) -> dict[ProfileTab, str]:
        """Fetch every profile tab with one authenticated session."""

        results: dict[ProfileTab, str] = {}
        for tab in ProfileTab:
            results[tab] = self.get_profile_tab(tab)
        return results

    def get_current_reservation(self) -> ReservationSummary:
        """Return parsed reservation state from profile."""

        html = self.get_profile_tab(ProfileTab.MA_RESERVATION)
        return parse_profile_reservation(html)

    def get_available_tickets(self) -> TicketAvailabilitySummary:
        """Return parsed available ticket balances from the profile tab."""

        html = self.get_profile_tab(ProfileTab.CARNET_RESERVATION)
        return parse_ticket_availability(html)

    def cancel_current_reservation(self) -> bool:
        """Cancel active reservation if present and return final no-reservation state."""

        self._require_authenticated()
        current = self.get_current_reservation()
        if not current.has_active_reservation:
            return False

        response = self._request.post(
            MA_RESERVATION_URL,
            form={"annulation": "true", "token": current.cancellation_token},
            timeout=120_000,
        )
        if not response.ok:
            raise BookingError(f"Cancellation failed ({response.status}).")

        refreshed = self.get_current_reservation()
        return not refreshed.has_active_reservation

    def book_first_available(
        self,
        *,
        days_in_advance: int = 2,
        preferred_venues: tuple[str, ...] = (),
    ) -> BookedReservation:
        """Book the first available slot for a date at least two days in advance."""

        self._require_authenticated()
        if days_in_advance < 2:
            raise BookingError("Booking tests must use at least two days in advance.")

        catalog = self.get_search_catalog()
        target_date = (dt.date.today() + dt.timedelta(days=days_in_advance)).strftime(
            "%d/%m/%Y"
        )

        candidate_venues = preferred_venues or tuple(
            name for name, venue in catalog.venues.items() if venue.available_now
        )

        if not candidate_venues:
            candidate_venues = tuple(catalog.venues.keys())

        for venue_name in candidate_venues:
            request = SearchRequest(
                venue_name=venue_name,
                date_iso=target_date,
                hour_start=catalog.min_hour,
                hour_end=catalog.max_hour,
                surface_ids=tuple(catalog.surface_options.keys()),
                in_out_codes=tuple(catalog.in_out_options.keys()),
            )
            result = self.search_slots(request)
            if not result.slots:
                continue

            chosen_slot = result.slots[0]
            self._logger.info(
                "Booking first available slot: %s",
                asdict(chosen_slot),
            )
            self.book_slot(chosen_slot, result.captcha_request_id)
            summary = self.get_current_reservation()
            if not summary.has_active_reservation:
                raise BookingError(
                    "Reservation did not appear in profile after booking."
                )
            return BookedReservation(venue_name=venue_name, slot=chosen_slot)

        raise BookingError("No available slot found for requested date.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _dump_debug(self, reason: str) -> Path | None:
        """Save a screenshot + HTML + URL of the current page for post-mortems.

        Called from the top-level public methods' except clauses so every
        failure inside a Playwright flow leaves behind a reviewable snapshot.
        Safe to call with no page attached — just returns None.  Errors here
        are swallowed to a log line: we never want debug capture to mask
        the real booking failure the caller is propagating.
        """

        if self._debug_dir is None or self._page is None:
            return None
        try:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
        except Exception as err:  # noqa: BLE001
            self._logger.warning(
                "Debug dir %s unusable: %s", self._debug_dir, err
            )
            return None
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_reason = re.sub(r"[^A-Za-z0-9._-]+", "_", reason).strip("_")[:80]
        stem = self._debug_dir / f"{timestamp}_{safe_reason or 'error'}"
        try:
            self._page.screenshot(
                path=str(stem) + ".png", full_page=True, timeout=10_000
            )
        except Exception as err:  # noqa: BLE001
            self._logger.warning("Debug screenshot failed (%s): %s", stem, err)
        try:
            stem.with_suffix(".html").write_text(
                self._page.content(), encoding="utf-8"
            )
        except Exception as err:  # noqa: BLE001
            self._logger.warning("Debug HTML dump failed (%s): %s", stem, err)
        try:
            stem.with_suffix(".url.txt").write_text(
                self._page.url, encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass
        self._logger.warning("Debug dump saved at %s", stem)
        return stem

    def _require_page(self) -> Page:
        self.open()
        if self._page is None:
            raise RuntimeError("Browser page was not initialized.")
        return self._page

    def _require_authenticated(self, *, optional: bool = False) -> None:
        if optional:
            return
        if not self._is_authenticated:
            raise AuthenticationError(
                "Call login() before using authenticated methods."
            )

    def _submit_validation_step(self) -> None:
        """Fill partner fields on the 'Validation du court' page and advance."""

        page = self._require_page()
        start_url = page.url
        self._logger.debug("Validation step starting — URL: %s", start_url)

        player_fields = page.locator("input[name='player1']")
        player_count = player_fields.count()
        if player_count >= 2:
            player_fields.nth(0).fill("Partenaire")
            player_fields.nth(1).fill("Test")
        else:
            self._logger.debug(
                "Validation step found %s partner field(s) (expected 2).", player_count
            )

        page.evaluate("""() => {
            const btn = document.getElementById('submitControle');
            if (btn) { btn.disabled = false; btn.classList.remove('disabled'); }
        }""")
        page.locator("#submitControle").click()
        time.sleep(2)
        page.wait_for_load_state("networkidle", timeout=30_000)
        end_url = page.url
        self._logger.info(
            "Validation step done — URL: %s (was: %s)", end_url, start_url
        )

        # The validation page stays at `reservation_creneau` when the site
        # rejects our submission (e.g. missing partner name, account flagged).
        # Raise here instead of letting the payment step inherit the wrong page.
        if "reservation_creneau" in str(end_url):
            raise BookingError(
                "Validation step did not advance past reservation_creneau. "
                f"partner_fields={player_count}, url={end_url}."
            )

    def _submit_payment_step(self) -> None:
        """Select the prepaid ticket card and confirm payment.

        Mirrors the logic exercised by the live e2e test: look for the
        ``existingTicket`` card, click it if present, then press ``#submit``.
        No DOM-text heuristics — if the site drifts we surface a clear error
        instead of inventing fallback selection.
        """

        page = self._require_page()
        start_url = page.url
        self._logger.debug("Payment step starting — URL: %s", start_url)

        card = page.locator("table[paymentmode='existingTicket']")
        card_count = card.count()
        if card_count == 0:
            # No prepaid card means pressing #submit would route to a paid
            # gateway.  Stop here — tennis.paris.fr still holds the slot
            # server-side for 15 minutes, so the user can finish manually.
            payment_modes = page.evaluate(
                "() => Array.from(document.querySelectorAll('table[paymentmode]'))"
                ".map(el => el.getAttribute('paymentmode'))"
            )
            self._logger.warning(
                "No 'existingTicket' payment card found. Available modes: %s",
                payment_modes,
            )
            raise BookingError(
                "No prepaid hours available for auto-booking. Your reservation "
                "is held for 15 minutes — finish it manually at "
                "https://tennis.paris.fr."
            )
        card.first.click()
        time.sleep(1)

        page.locator("#submit").click()
        time.sleep(3)
        page.wait_for_load_state("networkidle", timeout=30_000)
        end_url = page.url
        self._logger.info(
            "Payment step done — URL: %s (was: %s)", end_url, start_url
        )

        # Safety guards: never let a run finish silently in a paid-gateway
        # flow and never report success while still on methode_paiement.
        if "payfip" in str(end_url):
            raise BookingError(
                f"Payment step redirected to payfip (paid gateway). url={end_url}."
            )
        if "methode_paiement" in str(end_url):
            raise BookingError(
                "Payment step did not advance past methode_paiement. "
                f"existingTicket_card_count={card_count}, url={end_url}."
            )

    def _clear_pending_booking(self) -> None:
        """Walk through a stale booking wizard to the payment page, then abort.

        The server blocks all navigation while a booking flow is in progress.
        The only reliable escape is to advance to the payment page where the
        ``ajaxAbortBooking`` JS function is available.
        """

        page = self._require_page()

        # Solve captcha if that's where the redirect landed.
        if "reservation_captcha" in page.url:
            page.route("**/captcha.liveidentity.com/**", lambda route: route.abort())
            page.reload(wait_until="networkidle", timeout=120_000)
            page.unroute("**/captcha.liveidentity.com/**")

            captcha_html = page.content()
            config = parse_antibot_config(captcha_html)
            anti_bot_token = self._captcha_solver.solve(
                config=config,
                referer_url=page.url,
            )

            with page.expect_navigation(wait_until="networkidle", timeout=120_000):
                page.evaluate(
                    """(data) => {
                        const container = document.getElementById(data.containerId);
                        const form = container
                            ? container.closest('form')
                            : document.querySelector('form');
                        if (!form) throw new Error('No form found on captcha page');
                        const setField = (name, value) => {
                            let el = form.querySelector('input[name="' + name + '"]');
                            if (!el) {
                                el = document.createElement('input');
                                el.type = 'hidden';
                                el.name = name;
                                form.appendChild(el);
                            }
                            el.value = value;
                        };
                        setField(data.tokenName, data.token);
                        setField(data.tokenCodeName, data.tokenCode);
                        setField('submitControle', 'submit');
                        form.submit();
                    }""",
                    {
                        "containerId": anti_bot_token.container_id,
                        "tokenName": f"{anti_bot_token.container_id}-token",
                        "tokenCodeName": f"{anti_bot_token.container_id}-token-code",
                        "token": anti_bot_token.token,
                        "tokenCode": anti_bot_token.token_code,
                    },
                )
            self._logger.info("Pending captcha resolved — now at %s.", page.url)

        # Advance through the validation step if needed.
        if "reservation_creneau" in page.url:
            self._submit_validation_step()

        # Abort from the payment page.
        if "methode_paiement" in page.url:
            page.evaluate(
                "() => { if (typeof ajaxAbortBooking === 'function') ajaxAbortBooking(); }"
            )
            time.sleep(3)
            page.wait_for_load_state("networkidle", timeout=30_000)
            self._logger.info("Stale booking aborted — now at %s.", page.url)
