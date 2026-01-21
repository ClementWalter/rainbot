# RainBot Implementation Plan

## Current Status

### Summary

Core booking modules and unit-test coverage are in place, booking history can be
exported via the CLI and emailed on demand, but the live integration is not
production-ready because Paris Tennis login/booking steps still need live-site
validation, CAPTCHA edge cases and carnet selection remain unverified, and
deployment/integration testing remains incomplete. AJAX slot scraping now falls
back to DOM parsing to reduce false "no slots" results when the endpoint fails,
but the fallback still needs live-site validation. Reservation submission now
includes LiveIdentity anti-bot token fields observed on tennis.paris.fr to align
with the real booking flow, but the full captcha-to-confirmation path still
needs live-site verification. The AJAX slot fetch now uses live-site parameter
names (`selInOut`, `selCoating`) to avoid empty results from misnamed filters.
Search result scraping now attempts to solve CAPTCHA gates before parsing
availability, but still needs real-site verification. Availability retries now
refresh `captchaRequestId` after solving CAPTCHA gates so the AJAX slot endpoint
receives the updated token on retry. Slot parsing now also extracts booking
identifiers from link query strings or inline `onclick` handlers when data
attributes are missing, but still needs live-site verification. Availability
scraping now carries refreshed `captchaRequestId` values across facility AJAX
requests to reduce repeated CAPTCHA gating when the search page rotates tokens
mid-loop.

### What Exists

- [x] PRD.md - Complete product requirements
- [x] pyproject.toml - Dependencies configured (selenium, 2captcha, gspread,
      etc.)
- [x] main.py - Entry point with scheduler setup
- [x] ralph.py - Loop runner utility for development
- [x] src/ - Core structure with data models, Google Sheets service, browser
      utility, Paris Tennis service, CAPTCHA solver, and notification service
- [x] src/services/booking_history.py - Booking history CSV export helper
- [x] src/cli.py - Booking history export CLI (CSV) + email delivery
- [x] tests/ - Unit tests covering models, services, browser, Paris Tennis,
      CAPTCHA solver, notifications, cron jobs, locking, timezone, no-slots
      tracking, HTML escaping, cleanup job
- [x] PLAN.md - This file

### Remaining Work

1. **Paris Tennis selectors/flow**: Validate the remaining live DOM selectors
   and CAPTCHA handling (login entrypoint, reservation details player fields,
   payment selection, confirmation page, partner fields, search form facility
   selection) and complete an end-to-end run on tennis.paris.fr. Slot scraping
   now uses `action=ajax_rechercher_creneau` (the live slot listing endpoint),
   and reservation posts now include LiveIdentity token fields, but the full
   booking flow still needs validation on the live site.
2. **Carnet payment step validation**: Align carnet selection/payment
   confirmation with the live DOM and confirm any post-confirmation payment
   steps. The carnet selector now handles price table options but still needs
   live-site validation.
3. **Subscription/payment**: Add paid subscription handling beyond manual
   `subscription_active` flags.
4. **Integration tests**: Add end-to-end tests (recorded HTML or staging) for
   the booking flow.
5. **LiveIdentity anti-bot CAPTCHA**: Image-based LI_ANTIBOT flow is wired up.
   The solver now reuses existing `li-antibot-token` values and attempts a
   browser-side `LI_ANTIBOT.reloadAntibot/loadAntibot` refresh before calling
   2Captcha, but live-site validation is still required to confirm behavior and
   resolve "Blacklisted end-user" cases.
6. **Deployment**: Scaleway cloud deployment (Docker, docker-compose) plus
   monitoring/logging. Use the Scaleway skill for guidance; it is not currently
   installed in this environment, so install it via `skill-installer` before
   starting deployment work.
7. **Booking history access**: CLI CSV export and on-demand email delivery
   exist; still need a self-service UI/API if end-user access is required.
8. **User onboarding/request management**: Provide a user-facing interface
   (admin UI, simple API, or form) for managing users, subscriptions, and
   booking requests instead of editing Google Sheets directly.
9. **Success metrics**: Instrument booking success rate, CAPTCHA solve rate, and
   notification delivery (logs/metrics + dashboard) per PRD section 8.
10. **Credential security**: Protect Paris Tennis credentials and SMTP secrets
    with encryption and/or a secrets manager (aligns with PRD risk mitigation).
11. **Anti-bot hardening**: Add human-like interaction patterns (randomized
    delays, throttling, jitter) beyond current webdriver flags to reduce the
    risk of automation blocks (PRD section 10).
12. **Paris Tennis flow consolidation**: `paris_tennis.py` currently contains
    overlapping booking flow helpers (AJAX parsing plus legacy DOM scraping).
    Remove unused placeholders, keep a single validated flow, and align tests
    accordingly.

### Known Issues

1. **Partner Email Optional** - `partner_email` is optional in BookingRequest,
   but PRD says both user AND partner should receive reminders. The code handles
   this gracefully by skipping partners without email.
2. **Login state selectors still need broader validation** - The landing page
   and Mon Paris SSO selectors have been validated on tennis.paris.fr, but the
   post-login booking flow still needs live-site verification for reservation
   details (player fields), carnet selection, and confirmation selectors.
3. **LiveIdentity CAPTCHA edge cases** - Invisible challenge handling now defers
   to reCAPTCHA detection, but live-site validation on tennis.paris.fr is still
   pending.
4. **Parallel Paris Tennis flow code** - The service mixes placeholder DOM
   scraping with AJAX-based slot parsing, which can drift as the site evolves.
5. **LiveIdentity token blacklisted** - Live site sessions can populate
   `li-antibot-token` with "Blacklisted end-user" before booking. Availability
   scraping now refreshes/omits invalid tokens before AJAX requests, but the
   reservation flow still needs live validation and mitigation if tokens remain
   blacklisted.

### Resolved Issues

1. **facility_address not saved to Google Sheets** - Fixed: `add_booking()` now
   saves `facility_address` to the spreadsheet so that match day reminders
   include the facility address.
2. **Race Condition in Booking Job** - Fixed: Multiple booking job instances
   could run concurrently, causing duplicate bookings for the same user. Now
   uses a locking mechanism via Google Sheets `Locks` worksheet to prevent
   concurrent processing of the same user. Locks expire after 5 minutes to
   prevent deadlocks.
3. **Partner Reminder Shows Wrong Name** - Fixed: When sending match day
   reminders to partners, the email incorrectly showed the partner's own name as
   who they were playing with, instead of the user's name. Now the
   `send_match_day_reminder` function accepts a `player_name` parameter to
   correctly display the user's name to partners.
4. **Timezone Bug in Day-of-Week Filtering** - Fixed: The booking job used
   `datetime.now()` without timezone awareness, causing incorrect day-of-week
   detection when the server runs in UTC but users are in Paris timezone. Now
   uses Paris timezone consistently for all date/time comparisons.
5. **Timezone Bug in \_get_next_booking_date** - Fixed: The
   `_get_next_booking_date` method in `paris_tennis.py` used `datetime.now()`
   without timezone awareness, inconsistent with the rest of the codebase. Now
   uses `now_paris()` for consistent Paris timezone handling when calculating
   the next booking date.
6. **Timezone Bug in Booking.from_dict()** - Fixed: The `from_dict()` method in
   `booking.py` used `datetime.now()` as a fallback for invalid date values,
   which was inconsistent with the Paris timezone used elsewhere. Now uses
   `now_paris()` for consistency. Also fixed tests in `test_cron_jobs.py` to use
   Paris timezone functions (`today_weekday_paris()`, `now_paris()`) instead of
   naive `datetime.now()` to prevent test flakiness in different timezones.
7. **Test Assertion for Future Dates Only** - Fixed: The
   `test_get_next_booking_date_future` test had an overly permissive assertion
   that allowed same-day booking dates. Per PRD section 5.1 "Future dates only:
   Cannot book same-day courts", the test now correctly asserts that booking
   dates are strictly in the future (> today, not >= today).
8. **Numeric String day_of_week Parsing** - Fixed: The
   `BookingRequest.from_dict()` method failed to parse numeric strings like
   `"0"` or `"1"` for `day_of_week` (which Google Sheets may return). It only
   handled integer values and string enum names. Now tries to parse as integer
   first before falling back to enum name lookup.
9. **Missing Time Boundary Validation** - Fixed: Per PRD section 5.1 "Time
   boundaries: Courts available from 8:00 to 22:00", the
   `BookingRequest.from_dict()` method now validates and clamps `time_start` and
   `time_end` to the valid booking hours (08:00-22:00). Invalid or empty times
   default to boundary values. If time_start > time_end, they are automatically
   swapped. Added `MIN_BOOKING_TIME` and `MAX_BOOKING_TIME` constants for
   clarity.
10. **Time String Normalization Bug** - Fixed: The `is_time_in_range()` method
    used string comparison which failed for single-digit hour formats (e.g.,
    "9:00" vs "08:00"). The Paris Tennis website may return times in "H:MM"
    format instead of "HH:MM", causing valid times like "9:00" to be incorrectly
    rejected. Added `normalize_time()` function that pads single-digit hours and
    minutes with leading zeros. Updated both `is_time_in_range()` and
    `_validate_time()` to use this normalization for consistent time
    comparisons.
11. **Pending Booking Check Too Restrictive** - Fixed: The
    `has_pending_booking()` method in `google_sheets.py` was checking
    `booking.date >= today`, which incorrectly considered already-played
    bookings as "pending" on the same day. Per PRD section 5.1 "One active
    booking per user: Users cannot have multiple pending reservations", a
    booking that has already happened (end time has passed) should not prevent
    new bookings. Now the check properly considers: (1) future date bookings are
    pending, (2) today's bookings are only pending if the end time hasn't passed
    yet. This allows users to book for next week after their same-day booking
    has finished.
12. **CAPTCHA Token JavaScript Injection Vulnerability** - Fixed: The
    `_inject_recaptcha_token()` method in `captcha_solver.py` was directly
    interpolating the token into JavaScript strings using f-strings (e.g.,
    `textarea.value = '{token}'`). If the token contained single quotes, double
    quotes, backslashes, or newlines, this would break JavaScript execution and
    cause CAPTCHA solving to fail silently. Now uses `json.dumps()` to properly
    escape the token before embedding it in JavaScript, ensuring all special
    characters are safely handled.
13. **Partner Email Not Stored in Booking** - Fixed: The `partner_email` was
    only stored in `BookingRequest`, not in `Booking`. The `send_reminder()` job
    relied on looking up the original booking request to get the partner's email
    for reminders. If a booking request was deleted or modified after booking,
    the partner reminder would fail. Now `partner_email` is stored directly on
    the `Booking` model and persisted to Google Sheets, ensuring reminders work
    correctly regardless of booking request changes.
14. **Empty Date/Created_at String in Booking.from_dict** - Fixed: The
    `from_dict()` method in `booking.py` used `datetime.fromisoformat()`
    directly on string values without checking for empty strings or invalid
    formats, which would raise a ValueError and crash the application. Now
    properly handles empty strings, invalid date formats, and non-datetime types
    by defaulting to `now_paris()` for date and `None` (which triggers
    `__post_init__` to set `now_paris()`) for created_at.
15. **Silent Failure When No Slots Available** - Fixed: When the booking job
    found no available slots matching a user's criteria, it would silently
    return without notifying the user. This poor user experience left users
    unaware that their request was being processed. Now sends an informational
    "no slots available" notification (`send_no_slots_notification()`) that
    includes the search criteria (day, time range, facilities) and reassures the
    user that the system will continue searching automatically.
16. **No-Slots Notification Spam** - Fixed: The `send_no_slots_notification()`
    was called every time the booking job ran and found no slots. With the
    default interval scheduling (as frequent as every 10 seconds), this would
    spam users with repeated identical notifications. Added a
    `NoSlotsNotifications` worksheet in Google Sheets to track when
    notifications were sent for each request/target-date combination. Now only
    sends one "no slots" notification per booking request per target booking
    date. Also added cleanup function `cleanup_old_no_slots_notifications()` to
    remove old tracking records.
17. **HTML Injection Vulnerability in Email Notifications** - Fixed: All
    notification methods (`send_booking_confirmation`,
    `send_match_day_reminder`, `send_booking_failure_notification`,
    `send_no_slots_notification`) were directly interpolating user-provided data
    into HTML templates using f-strings without escaping. This allowed potential
    HTML/CSS injection attacks through malicious user names, facility names,
    partner names, error messages, or other user-controlled fields. While email
    clients typically don't execute JavaScript, malformed HTML can break email
    rendering and CSS injection can be used for phishing attempts. Now uses
    `html.escape()` to properly escape all user-provided data before embedding
    it in HTML templates.
18. **Missing Cleanup Job for NoSlotsNotifications** - Fixed: The
    `cleanup_old_no_slots_notifications()` function existed in
    `google_sheets.py` but was never called by any scheduled job. This would
    cause the NoSlotsNotifications sheet to grow indefinitely, potentially
    causing performance issues. Added `cleanup_old_notifications()` cron job
    that runs daily at 3:00 AM Paris time (after the reminder job) to clean up
    records older than 7 days.
19. **BookingRequest court_type defaults** - Fixed: `BookingRequest.from_dict()`
    now treats blank or invalid `court_type` values as `CourtType.ANY` instead
    of raising and dropping the request.
20. **Priority Logic Slot Ordering** - Fixed: Available slots are now sorted by
    facility preference order and earliest start time to guarantee the intended
    priority logic from the PRD.
21. **Booking Job Too Restrictive by Day** - Fixed: booking_job no longer
    restricts processing to requests whose day_of_week matches today. It now
    processes requests daily and always searches for the next occurrence of the
    requested day, improving continuous monitoring and booking success chances.
22. **Carnet Balance Eligibility** - Fixed: Users can now provide a
    `carnet_balance` value (remaining tickets) and the eligibility check blocks
    bookings when the balance is zero or negative.
23. **Booking History CSV Export Not Exposed via Sheets Service** - Fixed: Added
    `export_booking_history_csv()` on `GoogleSheetsService` to generate CSV
    histories directly from stored bookings.
24. **Case-Sensitive Boolean Parsing from Google Sheets** - Fixed: Uppercase
    "TRUE" values for `subscription_active` and `active` were treated as false,
    unintentionally disabling eligible users/requests. Parsing is now
    case-insensitive for these flags.
25. ~~**User Lock Scope Per Request** - The booking job released the per-user
    lock after each request, allowing another job to process the same user
    between requests and potentially book multiple courts.~~ **FIXED**: The
    booking job now groups requests by user, holds the lock across all of that
    user's requests, and stops after the first successful booking per user.
26. ~~**Day-of-Week Parsing Too Strict** - `BookingRequest.from_dict()` only
    accepted English day names and would fail on French inputs or extra
    whitespace from Google Sheets, dropping valid requests.~~ **FIXED**: Parsing
    now strips whitespace and accepts French day names (e.g., "mardi").
27. **Time Strings With Seconds Not Normalized** - `normalize_time()` rejected
    values like "09:00:00" (common from Google Sheets or site HTML), causing
    booking time validation and slot filtering to fail. **FIXED**: Now accepts
    "HH:MM:SS" and strips seconds for consistent comparisons.
28. **Carnet Balance Not Decremented After Booking** - Fixed: Successful
    bookings now decrement and persist the user's carnet balance in the Users
    sheet when a balance is tracked, preventing overbooking on stale balances.
29. **Blank Subscription/Active Flags Disable Users/Requests** - Fixed:
    `subscription_active` and `active` values that are empty or `None` now
    default to `True` to avoid unintentionally disabling eligible users or
    active requests when Sheets cells are blank.
30. ~~**Missing/Invalid time_end Allows Same-Day Double Booking** - When a
    booking for today lacks a valid `time_end`, `has_pending_booking()` treated
    it as not pending, allowing duplicate same-day bookings in violation of the
    "one active booking per user" rule.~~ **FIXED**: Missing/invalid end times
    are now treated as pending for the day.
31. ~~**Invisible reCAPTCHA Misclassified as v3** - The CAPTCHA solver treated
    `data-size="invisible"` as reCAPTCHA v3, causing invalid solve calls for
    invisible v2 widgets.~~ **FIXED**: Invisible v2 now calls
    `solve_recaptcha_v2(..., invisible=True)` while v3 detection uses
    `data-action` and page hints.
32. **Booking.from_dict Drops Date Objects** - `Booking.from_dict()` replaced
    `date` values passed as `datetime.date` objects with `now_paris()`, which
    could shift booking dates for records coming from Google Sheets. **FIXED**:
    Date objects are now converted to Paris-midnight `datetime` values and
    preserved.
33. **Notification Locale** - Email templates relied on system locale for
    day/month names, so French templates could display English dates. **FIXED**:
    Booking confirmation dates now use explicit French day/month mappings.
34. **Court Type Validation in Slot Parsing** - Fixed: Court slots now attempt
    to detect indoor/outdoor from DOM attributes/classes and filter mismatched
    results even if the UI filter fails, while allowing unknown types through.
35. **Invalid Time Component Handling** - Fixed: `normalize_time()` now
    validates hour/minute/second ranges (rejecting values like "24:00" or
    "12:99") to prevent invalid times from slipping into request validation and
    slot filtering.
36. **Facility Preferences None Crash** - Fixed: `BookingRequest.from_dict()`
    now defaults `facility_preferences` to an empty list when the source value
    is `None` or an unexpected type, preventing `TypeError` when iterating
    facility preferences during court searches.
37. **French Time Format Parsing** - Fixed: `normalize_time()` now accepts
    French-style formats like "18h00" or "18 h 00" so booking requests and slot
    parsing don't silently drop valid times entered in common French notation.
38. **User.from_dict None Handling** - Fixed: `User.from_dict()` previously
    converted `None` values into the literal string `"None"` for required fields
    (id/email/credentials), which could make users appear eligible with missing
    credentials and trigger failed logins. Now treats `None` as empty strings so
    eligibility checks behave correctly.
39. **BookingRequest Direct Init Time Normalization** - Fixed: Direct
    `BookingRequest(...)` construction did not normalize/clamp `time_start` and
    `time_end`, which could break time range comparisons (e.g., "9:00" vs
    "20:00"). Added `__post_init__` to normalize/clamp and swap inverted times,
    plus tests for direct initialization.
40. **Partner Booking Confirmation Missing** - Fixed: Successful bookings only
    notified the user, even when a partner email was provided. Now a booking
    confirmation email is also sent to the partner when `partner_email` is
    available.
41. **Reminder Schedule Configuration** - Fixed: Match-day reminder cron time is
    now configurable via `REMINDER_HOUR`, `REMINDER_MINUTE`, and
    `REMINDER_SECOND`, with a default of 08:00 to align with the PRD's "morning"
    reminder requirement.
42. **Image CAPTCHA URL Handling** - Fixed: image CAPTCHA sources that are
    HTTP(S) URLs are now downloaded and base64-encoded before sending to the
    2Captcha solver, preventing failures when the CAPTCHA image is not a local
    file path.
43. **AJAX Availability Endpoint Path** - Fixed: the day-availability fetch now
    builds the AJAX URL from `search_url` so it resolves to
    `/tennis/jsp/site/Portal.jsp?page=recherche&action=ajax_disponibilite`
    instead of a relative path that duplicated `jsp/site`.
44. **Facility Favorites Discovery** - Fixed: Paris Tennis facility detection
    now uses live DOM favorites (`window.jsFav` / `.tennisName`) with fallback
    to legacy selectors, improving alignment with tennis.paris.fr.
45. **Court Number Parsing Regex** - Fixed: Court number parsing in
    `paris_tennis.py` used a double-escaped regex that matched literal `\s`/`\d`
    sequences, so labels like "Court n° 3" were not reduced to the numeric court
    number. The regex now correctly extracts digits from common labels.
46. **Booking Date Timezone Normalization** - Fixed: `Booking.from_dict()`
    parsed ISO datetime strings with timezone offsets but did not normalize them
    to Paris time, so dates near midnight could be off by a day for reminders
    and pending-booking checks. Parsed `date`/`created_at` values are now
    converted to Europe/Paris, and `Booking.is_today()` compares Paris dates for
    timezone-aware values.
47. **LiveIdentity invisible CAPTCHA fallback** - Fixed: Invisible LI_ANTIBOT
    responses no longer hard-fail the CAPTCHA solver; the flow now defers to
    reCAPTCHA detection so invisible challenges can still be solved.
48. **Mon Paris Login Entrypoint** - Fixed: The login flow now detects Mon Paris
    links (parisian-account/mobileMonCompte) and clicks the Mon Paris
    "Connexion" dropdown to reach the SSO login form, aligning with the current
    moncompte.paris.fr flow.
49. **Booking.is_today naive datetime handling** - Fixed: Naive `Booking.date`
    values are normalized to Paris timezone when checking `is_today`, and the
    tests now use `now_paris()` to align with the Paris-only time model.
50. **Facility Address Extraction in AJAX flow** - Fixed:
    `_parse_available_slots_html()` now extracts facility addresses from AJAX
    HTML (data attributes or address labels) so booking confirmations and
    reminders include the facility address.
51. **CAPTCHA Form Submission After Solve** - Fixed: The booking flow solved
    CAPTCHA challenges but did not explicitly submit the CAPTCHA form, which
    could leave the reservation stuck on the CAPTCHA page. The flow now submits
    the CAPTCHA form when present to advance to payment/confirmation.
52. **Relative Image CAPTCHA URLs** - Fixed: Image CAPTCHA sources that are
    relative URLs (for example, `/captcha/image`) are now resolved against the
    current page URL before being sent to the solver, preventing failures when
    the site returns non-absolute image sources.
53. **Image CAPTCHA Data URI Handling** - Fixed: Image CAPTCHA sources embedded
    as `data:` URIs now have their base64 payload extracted before sending to
    the solver, preventing failures when CAPTCHAs are inlined in HTML.
54. **AJAX Slot Attribute Variants** - Fixed: AJAX slot parsing only matched
    `buttonAllOk` buttons and camel-case attributes, so slots could be missed
    when the live site emits `data-*` attributes. Parsing now accepts `data-*`
    equipment/court/date/price/captcha attributes, improving real-site scraping
    resilience.
55. **AJAX Slot Date Format Variants** - Fixed: Availability parsing only
    handled `YYYY/MM/DD HH:MM:SS` date strings, so slots with dashes or missing
    seconds were dropped. Parsing now accepts both slash/dash formats and
    optional seconds to avoid missing valid slots.
56. **8:00 AM Booking Burst Minute Scope** - Fixed: The burst booking cron jobs
    ran every minute during the 8 AM hour because the minute field was omitted.
    The schedule now pins `minute=0` so the burst only runs at
    08:00:00-08:00:08, and tests cover the cron configuration.
57. **AJAX Slot Endpoint Mismatch** - Fixed: Slot scraping previously called
    `action=ajax_disponibilite`, which only returns day-level availability and
    no `buttonAllOk` booking payloads. The scraper now uses
    `action=ajax_rechercher_creneau` with `selInOut[]`/`selCoating[]` parameters
    to fetch actual slot HTML from the live site.
58. **Facility Preferences Substring Matching** - Fixed: Facility preferences
    now match facility names when a unique substring match exists (useful for
    codes embedded in facility names), reducing failed searches when request
    preferences are stored as codes.
59. **Facility Preference Ordering With Codes** - Fixed: When requests stored
    facility preferences as short codes (for example, "FAC001") and slots used
    normalized facility names, the sorting logic could ignore preference order
    and sort purely by time. Sorting now applies substring-aware matching so
    facility priority is preserved even when codes are embedded in facility
    names.
60. **Zero Interval Schedule Crash** - Fixed: APScheduler raises when the
    interval job is configured with HOUR/MINUTE/SECOND all set to zero. The
    scheduler now clamps negative values to zero and defaults to a 10-second
    interval when all values are zero, preventing startup crashes from invalid
    configuration.
61. **Reservation Form Action URL** - Fixed: The reservation form submission
    used a relative action path (`jsp/site/Portal.jsp...`) that could duplicate
    `jsp/site` when resolved from the search results page, potentially breaking
    booking. The action URL is now built from the search URL and passed into the
    submission script, with tests covering the absolute URL.
62. **reCAPTCHA v3 Script-Only Detection** - Fixed: CAPTCHA solving relied on
    DOM elements with `data-sitekey`, so pages that only embed reCAPTCHA v3 via
    `api.js?render=` or `grecaptcha.execute(...)` were skipped. The solver now
    extracts sitekeys/actions from page source and CAPTCHA detection recognizes
    script-only reCAPTCHA, ensuring v3 challenges are solved.
63. **AJAX-Only Slot Search Fallback** - Fixed: `search_available_courts()`
    previously returned no slots when the AJAX endpoint failed or facility
    preferences could not be resolved, even if slots were visible in the DOM. It
    now falls back to DOM parsing when AJAX yields no slots or no facility names
    are resolved.
64. **Hidden Search Form Results Context** - Fixed: The live search page hides
    the `#rechercher` submit button, so Selenium timeouts prevented reaching the
    `action=rechercher_creneau` results context and `captchaRequestId`. The flow
    now submits `#search_form` directly and only falls back to clicking the
    button when needed.
65. **French Boolean Parsing** - Fixed: `is_truthy()` now accepts French boolean
    strings (for example, "vrai" or "oui") and common English "yes" values so
    active/subscription flags are not misread in French-localized Google Sheets.
66. **LiveIdentity Single-Quoted Config Parsing** - Fixed: The LiveIdentity
    parser expected JSON arrays and failed when `LI_ANTIBOT.loadAntibot(...)`
    used single-quoted JavaScript arrays, preventing anti-bot CAPTCHA detection.
    The parser now normalizes JS literals and accepts single-quoted arrays so
    LiveIdentity challenges are detected reliably.
67. **LiveIdentity Token Validation Trigger** - Fixed: The token injection now
    dispatches input/change events on `li-antibot-token` and calls
    `checkFormValidity()` when available so the live CAPTCHA form enables the
    submit button after a successful solve.
68. **DOM Fallback Ignores Facility Preferences** - Fixed: When the AJAX slot
    search failed, DOM parsing returned slots for all facilities, which could
    result in bookings outside a user's preferred facilities. The DOM fallback
    now filters slots using normalized facility preference matching before
    sorting and booking.
69. **AJAX Slot Elements Limited to `<button>` Tags** - Fixed: Availability
    parsing now considers anchor/input elements and attribute-based selectors so
    slots are not missed when the live site renders booking controls outside
    `<button>` tags.
70. **Search Form Submission Bypassed UI Handlers** - Fixed: The search flow
    used `form.submit()` on the hidden `#search_form`, which bypassed the
    "Rechercher" button handlers that populate `selWhereTennisName` and caused
    empty facility lists and mismatched `captchaRequestId` values. The flow now
    updates the search form with the target date/facilities and triggers the
    hidden button click to keep parameters aligned with the live site.
71. **LiveIdentity Config Extraction With Extra Args** - Fixed: The LiveIdentity
    parser only matched `LI_ANTIBOT.loadAntibot([...])` and failed when the live
    site used `window.LI_ANTIBOT.loadAntibot([...], ...)` or added extra
    arguments. Config extraction now scans for the bracketed array literal
    regardless of extra arguments, ensuring CAPTCHA parsing works on live pages.
72. **DOM Fallback Slot Parsing** - Fixed: DOM fallback parsing now recognizes
    live `.buttonAllOk` slots and extracts booking identifiers (`equipmentId`,
    `courtId`, `dateDeb`, `dateFin`), facility names from panel IDs, and
    indoor/outdoor labels so fallback bookings work when AJAX results are
    unavailable.
73. **LiveIdentity CAPTCHA Image URL Resolution** - Fixed: The LiveIdentity
    solver previously concatenated `base_url` with the challenge image URL,
    which produced invalid URLs when the API returned absolute image links. The
    solver now uses `urljoin` with normalized base URLs so both absolute and
    relative image paths resolve correctly.
74. **Facility Preferences Not Resolved From Map List** - Fixed: The live search
    page exposes facility names via `window.mapMarkers`, which can be a Map of
    names, a Map with nested `map` entries, or a plain object with a nested
    `map` property. The service now reads facility names from
    `mapMarkers.get('map')`, `mapMarkers.map`/`mapMarkers['map']`,
    `mapSelectTennis` variants, and the direct Map keys so facility filtering
    works on tennis.paris.fr.
75. **CAPTCHA Gate Before Availability Scrape** - Fixed: search result scraping
    now detects and solves CAPTCHA challenges before parsing availability,
    preventing the live site from returning empty slot results when anti-bot
    challenges appear.
76. **LiveIdentity Token Reuse/Refresh** - Fixed: the CAPTCHA solver now checks
    existing `li-antibot-token` values and triggers the in-page
    `LI_ANTIBOT.reloadAntibot/loadAntibot` flow to refresh tokens before falling
    back to 2Captcha, reducing failed solves on tennis.paris.fr.
77. **Session-Protected Image CAPTCHA Fetch** - Fixed: image CAPTCHA solving now
    attempts to fetch the CAPTCHA image through the browser context first,
    preserving session cookies so protected CAPTCHA images can be solved
    reliably on tennis.paris.fr.
78. **captchaRequestId Extraction Too Narrow** - Fixed: booking previously only
    read a hidden input with `id="captchaRequestId"`, missing cases where the
    value is stored under input `name` attributes, `data-*` attributes, window
    variables, or inline scripts. `_get_captcha_request_id()` now checks these
    sources to keep reservation submissions aligned with the live site.
79. **reCAPTCHA Token Injection Missed Page Callbacks** - Fixed: token injection
    now dispatches input/change events and invokes `data-callback` handlers
    (plus known `___grecaptcha_cfg` callbacks) so the live site recognizes
    solved CAPTCHA responses.
80. **Login CAPTCHA Resubmission** - Fixed: the Mon Paris login flow now solves
    CAPTCHA challenges when present and re-submits the login form so
    authentication does not stall on CAPTCHA gates.
81. **AJAX Availability Missing captchaRequestId** - Fixed:
    `_fetch_availability_html()` now includes the `captchaRequestId` parameter
    when available so the live `ajax_rechercher_creneau` endpoint returns slot
    results even when CAPTCHA gating is active.
82. **LiveIdentity Image CAPTCHA Session Fetch** - Fixed: LiveIdentity image
    challenges now attempt a browser-context fetch first so session-protected
    CAPTCHA images can be solved even when direct HTTP requests are blocked,
    falling back to a direct request when browser fetch fails.
83. **Login State False Positive** - Fixed: The site renders a hidden
    `#banner-mon-compte_menu__logout` element even when logged out, which caused
    `_is_logged_in()` to return true and skip authentication. Login detection
    now checks for visible `.navbar-collapse.connected/.disconnected` nav state
    and the login button before falling back to other indicators.
84. **Facility Names Hidden Inside mapMarkers Values** - Fixed:
    `_get_available_facility_names()` now extracts facility names from both
    mapMarkers keys and common name/label fields inside mapMarkers values (plus
    nested `map`/`mapSelectTennis` entries). This prevents AJAX slot scraping
    from using placeholder `map*` keys that do not match real facility names.
85. **Day-First AJAX Slot Dates Not Parsed** - Fixed: `_parse_slot_datetime()`
    now accepts day-first date formats like `DD/MM/YYYY HH:MM(:SS)` (plus dash
    variants), preventing Paris tennis AJAX slots from being dropped when the
    site returns French-style dates.
86. **LiveIdentity Reload JS Error** - Fixed: `LI_ANTIBOT.reloadAntibot()` can
    throw a `TypeError` on the live search results page (blocking token
    refresh). The refresh helper now catches reload failures and falls back to
    `LI_ANTIBOT.loadAntibot()` with the parsed config so LiveIdentity tokens can
    still be refreshed before calling 2Captcha.
87. **AJAX Availability CAPTCHA Retry** - Fixed: When the AJAX slot endpoint
    returns CAPTCHA HTML, `_fetch_availability_html()` now detects the gate,
    attempts to solve the CAPTCHA, and retries once before giving up.
88. **AJAX Filter Parameter Names** - Fixed: the availability fetch now uses
    `selInOut` and `selCoating` parameter names (matching the live search AJAX
    request) instead of `selInOut[]`/`selCoating[]`, preventing empty results
    from misnamed filters.
89. **Reservation POST Missing LiveIdentity Tokens** - Fixed: the booking
    submission now includes `li-antibot-token` and `li-antibot-token-code`
    fields (captured from the live search results page) so the reservation
    request matches the tennis.paris.fr flow.
90. **Surface Filter Values Read Before Navigation** - Fixed: `selCoating`
    values were fetched before the search page loaded, leaving AJAX requests
    without surface filters and potentially returning empty results. The surface
    values are now read after the search page is loaded.
91. **reCAPTCHA Response Field Missing** - Fixed: When pages did not include a
    `g-recaptcha-response` field, token injection had no effect. The injector
    now creates hidden response fields in available forms (or falls back to the
    document body) before setting the token and dispatching events.
92. **AJAX Availability Missing LiveIdentity Tokens** - Fixed: the availability
    fetch now forwards `li-antibot-token` and `li-antibot-token-code` values
    from the results page when present so the live AJAX search stays aligned
    with the anti-bot session state.
93. **Invalid LiveIdentity Tokens Sent to AJAX Availability** - Fixed: the
    availability fetch now refreshes LiveIdentity tokens when they are invalid
    (for example, "Blacklisted end-user") and omits invalid tokens before
    sending AJAX requests.
94. **Booking Re-submits Search Without captchaRequestId** - Fixed: bookings now
    reuse the current results page `captchaRequestId` when available before
    re-submitting the search form, reducing unnecessary CAPTCHA retries and
    keeping the selected slot in context.
95. **Reservation Details + Payment Step Handling** - Fixed: booking flow now
    fills reservation player fields, clicks "Ajouter un partenaire" when needed,
    and selects carnet payment options from price tables before advancing,
    aligning with the live reservation flow.
96. **AJAX Availability CAPTCHA Retry Refresh** - Fixed: when the availability
    AJAX response returns CAPTCHA HTML, the retry now refreshes
    `captchaRequestId` from the page after solving so the next request includes
    the updated token.
97. **Slot Identifiers In href/onclick** - Fixed: availability and DOM parsing
    now extract equipment/court/date identifiers (and `captchaRequestId`) from
    query strings or inline `onclick` handlers when data attributes are missing,
    improving scraping reliability on tennis.paris.fr.
98. **LiveIdentity CAPTCHA Fallback** - Fixed: CAPTCHA solving now attempts
    reCAPTCHA/image fallbacks when LiveIdentity detection fails and returns the
    last error instead of reporting "No CAPTCHA detected", improving success
    rates when LiveIdentity config markup is missing.
99. **Booking Flow Race Condition After Reservation Submit** - Fixed: The
    booking flow now waits for a CAPTCHA or reservation/payment step after
    submitting the reservation form, preventing fast follow-up actions from
    running before the live page transition completes.
100. **Refreshed captchaRequestId Not Reused Across Facilities** - Fixed: AJAX
     availability scraping now reuses refreshed `captchaRequestId` values across
     facility iterations so subsequent slot fetches stay aligned with the latest
     CAPTCHA session token.
101. **AJAX captchaRequestId Hidden in Availability HTML** - Fixed: availability
     parsing now extracts `captchaRequestId` from AJAX HTML (hidden inputs or
     scripts) and assigns it to slots when button attributes are missing, so
     booking submissions reuse the correct CAPTCHA token.
102. **CAPTCHA Solve False Positives** - Fixed: when a CAPTCHA is detected but
     the solver reports "No CAPTCHA detected", the flow now treats this as a
     failure instead of proceeding without a solved challenge.

---

## Architecture Overview

```
src/
├── __init__.py
├── config/
│   ├── __init__.py
│   └── settings.py          # Environment variables, constants
├── models/
│   ├── __init__.py
│   ├── booking_request.py   # User booking preferences [DONE]
│   ├── booking.py           # Completed booking record [DONE]
│   └── user.py              # User credentials and info [DONE]
├── services/
│   ├── __init__.py
│   ├── paris_tennis.py      # Paris tennis website interaction [DONE]
│   ├── captcha_solver.py    # 2Captcha integration [DONE]
│   ├── notification.py      # Email notifications [DONE]
│   └── google_sheets.py     # GSheet data storage [DONE]
├── schedulers/
│   ├── __init__.py
│   └── cron_jobs.py         # booking_job, send_reminder [DONE]
└── utils/
    ├── __init__.py
    └── browser.py           # Selenium browser setup [DONE]
```

---

## Implementation Phases

### Phase 1: Core Structure (COMPLETED)

**Goal**: Make main.py runnable with placeholder implementations

- [x] Create src/**init**.py
- [x] Create src/schedulers/**init**.py
- [x] Create src/schedulers/cron_jobs.py with booking_job and send_reminder
      stubs
- [x] Create src/config/settings.py for environment variables
- [x] Create basic tests to verify structure
- [x] Fix pyproject.toml hatch build configuration

### Phase 2: Data Layer (COMPLETED)

**Goal**: User and booking request management via Google Sheets

- [x] Create src/models/user.py - User model with eligibility check
- [x] Create src/models/booking_request.py - BookingRequest with time range and
      from_dict
- [x] Create src/models/booking.py - Booking model with is_today check
- [x] Create src/services/google_sheets.py - Full CRUD for users, requests,
      bookings
- [x] Add tests/test_models.py - 13 tests for data models
- [x] Add tests/test_google_sheets.py - 8 tests for sheets service
- [x] Export models and services via **init**.py

### Phase 3: Paris Tennis Integration (PARTIAL)

**Goal**: Interact with the Paris Tennis booking website

- [x] Create src/utils/browser.py (Selenium setup with anti-detection)
- [x] Create src/services/paris_tennis.py
- [x] Implement login functionality
- [x] Implement availability search
- [x] Implement booking flow
- [x] Add tests for tennis service (22 tests)

### Phase 4: CAPTCHA Solving (COMPLETED)

**Goal**: Integrate 2Captcha for verification

- [x] Create src/services/captcha_solver.py
- [x] Integrate with booking flow
- [x] Add retry logic
- [x] Add tests for captcha service (21 tests)

### Phase 5: Notifications (COMPLETED)

**Goal**: Send booking confirmations and reminders

- [x] Create src/services/notification.py
- [x] Implement booking confirmation emails (French HTML emails)
- [x] Implement match day reminders (send_reminder job)
- [x] Implement booking failure notifications
- [x] Add tests for notification service (28 tests)

### Phase 6: Full Integration (PARTIAL)

**Goal**: End-to-end booking automation

- [x] Wire all services together in booking_job
- [x] Implement priority logic for facility preferences
- [x] Add booking history tracking
- [ ] Add comprehensive integration tests

### Phase 7: Deployment

**Goal**: Deploy to Scaleway cloud

- [x] Create Dockerfile
- [x] Create docker-compose.yml
- [x] Create .dockerignore
- [x] Create .env.example
- [ ] Configure Scaleway deployment
- [ ] Set up monitoring and logging

---

## Next Action

**Next Step**: Align Paris Tennis selectors/flow with the live site and add a
basic end-to-end smoke test before moving on to Scaleway deployment/monitoring.

Phase 6 is mostly implemented with:

- booking_job(): Full booking workflow implementation
  - Loads active requests from Google Sheets
  - Filters eligible users with active subscriptions
  - Processes requests daily for the next occurrence of the requested day of
    week
  - Checks for pending bookings to avoid duplicates
  - Logs into Paris Tennis, searches courts, books slots
  - Handles CAPTCHA via integrated solver
  - Sends notifications on success/failure
- send_reminder(): Daily reminder job
  - Loads today's bookings
  - Sends reminders to users and partners

---

## Notes

- The scheduler in main.py runs:
  - `booking_job` on interval (configurable via HOUR, MINUTE, SECOND env vars)
  - `booking_job` at 8:00 AM Paris time (every 2 seconds for first 10 seconds)
  - `send_reminder` at 8:00 AM Paris time daily (configurable via
    `REMINDER_HOUR`, `REMINDER_MINUTE`, `REMINDER_SECOND`)
  - `cleanup_old_notifications` at 3:00 AM Paris time daily (removes no-slots
    notification records older than 7 days)
- User data is stored in Google Sheets (requires service account credentials)
- CAPTCHA solving uses 2captcha-python library
- Browser utility uses webdriver-manager for automatic ChromeDriver management
- All unit tests passing as of court_type default handling update

---

## Google Sheets Structure

The spreadsheet should have four worksheets:

### Users Sheet

| Column                | Description                                   |
| --------------------- | --------------------------------------------- |
| id                    | Unique user identifier                        |
| name                  | User's display name (for personalized emails) |
| email                 | User's notification email                     |
| paris_tennis_email    | Paris Tennis login email                      |
| paris_tennis_password | Paris Tennis password                         |
| subscription_active   | true/false for subscription status            |
| carnet_balance        | Remaining tickets in the user's carnet        |
| phone                 | Optional phone number                         |

### BookingRequests Sheet

| Column               | Description                    |
| -------------------- | ------------------------------ |
| id                   | Unique request identifier      |
| user_id              | Reference to user              |
| day_of_week          | monday-sunday or 0-6           |
| time_start           | HH:MM format                   |
| time_end             | HH:MM format                   |
| facility_preferences | Comma-separated facility codes |
| court_type           | indoor/outdoor/any             |
| partner_name         | Playing partner's name         |
| partner_email        | Partner's email for reminders  |
| active               | true/false                     |

### Bookings Sheet

| Column           | Description                             |
| ---------------- | --------------------------------------- |
| id               | Unique booking identifier               |
| user_id          | Reference to user                       |
| request_id       | Reference to booking request            |
| facility_name    | Tennis facility name                    |
| facility_code    | Facility identifier                     |
| court_number     | Court number                            |
| date             | ISO format date                         |
| time_start       | HH:MM format                            |
| time_end         | HH:MM format                            |
| partner_name     | Playing partner                         |
| partner_email    | Partner's email for reminders           |
| confirmation_id  | Paris Tennis confirmation               |
| facility_address | Facility street address (for reminders) |
| created_at       | When booking was made                   |

### Locks Sheet

| Column    | Description                          |
| --------- | ------------------------------------ |
| user_id   | User currently being processed       |
| locked_at | ISO timestamp when lock was acquired |
| locked_by | UUID of the job that holds the lock  |

**Note:** The Locks sheet is automatically created by the system if it doesn't
exist. Locks expire after 5 minutes to prevent deadlocks if a job crashes.

### NoSlotsNotifications Sheet

| Column      | Description                                 |
| ----------- | ------------------------------------------- |
| request_id  | The booking request ID                      |
| target_date | The target booking date (YYYY-MM-DD format) |
| sent_at     | ISO timestamp when notification was sent    |

**Note:** The NoSlotsNotifications sheet is automatically created by the system
if it doesn't exist. This sheet tracks when "no slots available" notifications
were sent to prevent spamming users with repeated notifications. Old records
(older than 7 days by default) can be cleaned up using
`cleanup_old_no_slots_notifications()`.
