"""High-level API client for tennis.paris.fr using a browser-backed session."""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import asdict
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
    ) -> None:
        self._email = email
        self._password = password
        self._headless = headless
        self._logger = logger or logging.getLogger(__name__)

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

        page = self._require_page()
        response = page.goto(AUTH_URL, wait_until="domcontentloaded", timeout=120_000)
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
                throw new Error('No matching slot button found on search results page');
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

    # Prepaid payment modes the site offers, in order of preference.  Only
    # modes that consume an *existing* balance belong here — `ticket` is the
    # paid purchase path (routes to payfip.gouv.fr) and must never be clicked
    # automatically or we'd silently charge the user.
    _PAYMENT_MODE_PREFERENCE: tuple[str, ...] = ("wallet", "existingTicket")
    # Known paid modes we refuse to select.  Listed explicitly so the error
    # message can distinguish "paid option skipped" from "unknown mode".
    _PAID_PAYMENT_MODES: frozenset[str] = frozenset({"ticket"})

    def _submit_payment_step(self) -> None:
        """Select the first available prepaid card and confirm payment."""

        page = self._require_page()
        start_url = page.url
        self._logger.debug("Payment step starting — URL: %s", start_url)

        # Enumerate all payment modes so we can diagnose which options the site
        # offered if the booking fails to advance.  Kept at INFO so operators
        # see the real options the first time they hit a new account shape.
        payment_modes = page.evaluate(
            "() => Array.from(document.querySelectorAll('table[paymentmode]'))"
            ".map(el => el.getAttribute('paymentmode'))"
        )
        self._logger.info("Payment page modes available: %s", payment_modes)

        # Walk the preference list and click the first prepaid card that's on
        # the page.  The site requires a selected card before #submit advances,
        # so missing this step makes the flow silently stall at methode_paiement.
        selected_mode = ""
        for candidate in self._PAYMENT_MODE_PREFERENCE:
            card = page.locator(f"table[paymentmode='{candidate}']")
            if card.count() > 0:
                card.first.click()
                selected_mode = candidate
                time.sleep(1)
                break

        if not selected_mode:
            # Refusing to fall back to `ticket` (paid) is deliberate: clicking
            # it would redirect to payfip and silently charge whatever card
            # the account has on file.  Raise a clear error instead so the
            # operator can top up the prepaid balance or book differently.
            paid_offered = sorted(
                mode for mode in payment_modes or [] if mode in self._PAID_PAYMENT_MODES
            )
            raise BookingError(
                "No prepaid payment option available on methode_paiement. "
                f"available_modes={payment_modes}, "
                f"prepaid_tried={list(self._PAYMENT_MODE_PREFERENCE)}, "
                f"paid_modes_skipped={paid_offered}. "
                "Refusing to auto-click paid options (would charge via payfip)."
            )

        page.locator("#submit").click()
        time.sleep(3)
        page.wait_for_load_state("networkidle", timeout=30_000)
        end_url = page.url
        self._logger.info(
            "Payment step done — URL: %s (was: %s, mode=%s)",
            end_url,
            start_url,
            selected_mode,
        )

        # Any payfip redirect means we somehow clicked through to the paid
        # gateway.  Abort loudly: never let a webapp/CLI run finish "silently"
        # in a real-money payment flow.
        if "payfip" in str(end_url):
            raise BookingError(
                "Payment step redirected to payfip (paid gateway) despite "
                f"selecting prepaid mode={selected_mode!r}. url={end_url}."
            )

        # When the submit click is ignored (e.g. button kept disabled), the
        # URL stays at methode_paiement and `get_current_reservation` later
        # returns empty.  Surface this now with enough context to diagnose.
        if "methode_paiement" in str(end_url):
            raise BookingError(
                "Payment step did not advance past methode_paiement. "
                f"selected_mode={selected_mode}, "
                f"available_modes={payment_modes}, url={end_url}."
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
