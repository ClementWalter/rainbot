# Codebase Report: Paris Tennis URLs and Endpoints

Generated: 2026-01-27

## Summary

The rainbot system interacts with the Paris Tennis booking website
(tennis.paris.fr) through a combination of:

- Browser-based navigation (requires authentication)
- AJAX API endpoints (require auth + anti-bot tokens)
- External SSO via moncompte.paris.fr
- LiveIdentity anti-bot/captcha system

All endpoints require authentication except the initial public landing pages.

---

## Base Configuration

**Location:** `src/config/settings.py` (lines 89-98)

```python
ParisTennisConfig(
    base_url=os.getenv("PARIS_TENNIS_BASE_URL", "https://tennis.paris.fr"),
    login_url=os.getenv("PARIS_TENNIS_LOGIN_URL", "https://tennis.paris.fr/tennis/"),
    search_url=os.getenv("PARIS_TENNIS_SEARCH_URL",
        "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche&view=recherche_creneau"),
)
```

**Environment Variables:**

- `PARIS_TENNIS_BASE_URL` - Base domain
- `PARIS_TENNIS_LOGIN_URL` - Entry point for login flow
- `PARIS_TENNIS_SEARCH_URL` - Court search page

---

## URL Inventory

### 1. Public/Landing URLs (No Auth Required)

| URL                               | Purpose                   | Access |
| --------------------------------- | ------------------------- | ------ |
| `https://tennis.paris.fr`         | Base domain               | Public |
| `https://tennis.paris.fr/tennis/` | Landing/login entry point | Public |

**Usage:** ✓ VERIFIED

- Entry point in `login()` method (line 221)
- Browser navigates here first
- May redirect to SSO

---

### 2. Authentication URLs

#### Paris Tennis SSO

| URL                                     | Purpose                  | Auth Required    |
| --------------------------------------- | ------------------------ | ---------------- |
| `https://moncompte.paris.fr/moncompte/` | Mon Paris SSO login form | No (SSO entry)   |
| `https://moncompte.paris.fr/*`          | SSO flow pages           | No (during auth) |

**Usage:** ✓ VERIFIED

- Detected via selectors: `a[href*='moncompte.paris.fr']` (line 48-49)
- Login form validation checks for this domain (line 380)
- `_click_login_entrypoint()` navigates to SSO

**Flow:**

1. User lands on `tennis.paris.fr/tennis/`
2. Click login button → redirects to `moncompte.paris.fr`
3. Submit credentials
4. Redirect back to tennis.paris.fr (authenticated)

---

### 3. Search/Availability URLs

#### Browser-Based Search Page

| URL                                                                                        | Purpose         | Auth Required |
| ------------------------------------------------------------------------------------------ | --------------- | ------------- |
| `https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche&view=recherche_creneau` | Court search UI | Yes           |

**Usage:** ✓ VERIFIED

- Stored in `self.search_url` (line 185)
- Navigated to in `search_available_courts()` (line 477, 577)
- Base for constructing AJAX URLs

#### AJAX Availability Endpoint

| Endpoint                                                   | Method | Purpose                           | Auth Required         |
| ---------------------------------------------------------- | ------ | --------------------------------- | --------------------- |
| `Portal.jsp?page=recherche&action=ajax_rechercher_creneau` | POST   | Fetch available slots (live data) | Yes + anti-bot tokens |

**Usage:** ✓ VERIFIED

- Constant: `SEARCH_SLOTS_AJAX_PATH` (line 89)
- Called in `_fetch_availability_html()` (line 1228)
- Requires parameters:
  - `hourRange` - Time range (e.g., "18-20")
  - `when` - Date/day code
  - `selWhereTennisName` - Facility name
  - `selInOut[]` - Indoor/outdoor filter (V=indoor, F=outdoor)
  - `selCoating[]` - Surface type filters
  - `captchaRequestId` - Anti-bot request ID
  - `li-antibot-token` - LiveIdentity token
  - `li-antibot-token-code` - LiveIdentity token code

**Full URL Construction:**

```python
ajax_url = urljoin(self.search_url, SEARCH_SLOTS_AJAX_PATH)
# Results in: https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche&action=ajax_rechercher_creneau
```

**Response:** HTML fragment with slot listings

---

### 4. Booking/Reservation URLs

#### Reservation Captcha Page

| URL                                                    | Method | Purpose                                | Auth Required         |
| ------------------------------------------------------ | ------ | -------------------------------------- | --------------------- |
| `Portal.jsp?page=reservation&view=reservation_captcha` | POST   | Submit booking request (shows captcha) | Yes + anti-bot tokens |

**Usage:** ✓ VERIFIED

- Used in `_submit_reservation_form()` (line 1808)
- Form submission with parameters:
  - `equipmentId` - Facility equipment ID
  - `courtId` - Court ID
  - `dateDeb` - Start datetime (format: `YYYY/MM/DD HH:MM:SS`)
  - `dateFin` - End datetime
  - `annulation` - Cancellation flag (false)
  - `captchaRequestId` - Anti-bot request ID
  - `li-antibot-token` - LiveIdentity token
  - `li-antibot-token-code` - LiveIdentity token code

**Full URL Construction:**

```python
action_url = urljoin(self.search_url,
    "Portal.jsp?page=reservation&view=reservation_captcha")
# Results in: https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=reservation_captcha
```

#### Reservation Details Page

| URL Pattern                  | Purpose                           | Auth Required |
| ---------------------------- | --------------------------------- | ------------- |
| `*view=reservation_creneau*` | Booking confirmation/details view | Yes           |

**Usage:** ✓ VERIFIED

- Detected in `_handle_reservation_details()` (line 2828)
- Appears after successful booking submission

---

### 5. LiveIdentity Anti-Bot URLs

#### Captcha Configuration Endpoint

| URL                                                                                    | Method | Purpose                        | Auth Required |
| -------------------------------------------------------------------------------------- | ------ | ------------------------------ | ------------- |
| `https://captcha.liveidentity.com/captcha/public/frontend/api/v3/captchas/transaction` | POST   | Initialize captcha transaction | No            |

**Usage:** ✓ VERIFIED

- Called in `_start_liveidentity_transaction()` (line 1004)
- Returns transaction ID

#### Captcha Challenge Endpoint

| URL                                                                        | Method | Purpose                 | Auth Required |
| -------------------------------------------------------------------------- | ------ | ----------------------- | ------------- |
| `https://captcha.liveidentity.com/captcha/public/frontend/api/v3/captchas` | POST   | Fetch captcha challenge | No            |

**Usage:** ✓ VERIFIED

- Called in `_fetch_liveidentity_challenge()` (line 1051)
- Requires transaction ID from previous step
- Returns challenge image URL and question

#### Captcha Validation Endpoint

| URL                                                         | Method | Purpose               | Auth Required |
| ----------------------------------------------------------- | ------ | --------------------- | ------------- |
| `https://captcha.liveidentity.com/captcha/{validation_url}` | POST   | Submit captcha answer | No            |

**Usage:** ✓ VERIFIED

- Called in `_validate_liveidentity_answer()` (line 1103)
- `{validation_url}` extracted from challenge response
- Returns success/failure + tokens

**Base URL Configuration:**

- Extracted from page via `get_value(4)` in `_extract_liveidentity_config()`
  (line 631)
- Typically: `https://captcha.liveidentity.com/captcha`

---

## URL Flow Mapping

### Complete Booking Flow

```
1. HOME (Public)
   └─> https://tennis.paris.fr/tennis/
       ├─> Accept cookies
       └─> Click login button

2. SSO LOGIN (External)
   └─> https://moncompte.paris.fr/moncompte/
       ├─> Fill email/password
       ├─> Solve captcha (if present)
       └─> Submit → Redirect back authenticated

3. SEARCH PAGE (Auth Required)
   └─> https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche&view=recherche_creneau
       ├─> Select filters (date, time, facility, court type)
       └─> Submit search form

4. FETCH SLOTS (AJAX, Auth Required)
   └─> POST Portal.jsp?page=recherche&action=ajax_rechercher_creneau
       ├─> Include anti-bot tokens (li-antibot-token, li-antibot-token-code)
       ├─> Include captchaRequestId
       └─> Returns HTML with available slots

5. SELECT SLOT & BOOK (Auth Required)
   └─> POST Portal.jsp?page=reservation&view=reservation_captcha
       ├─> Include slot details (equipmentId, courtId, dates)
       ├─> Include anti-bot tokens
       └─> May trigger captcha challenge

6. SOLVE CAPTCHA (If Required)
   └─> LiveIdentity API sequence:
       ├─> POST /api/v3/captchas/transaction (start)
       ├─> POST /api/v3/captchas (get challenge)
       ├─> POST /{validation_url} (submit answer)
       └─> Returns new tokens

7. CONFIRMATION (Auth Required)
   └─> *view=reservation_creneau* (confirmation page)
       └─> Extract booking confirmation ID
```

---

## Authentication Requirements

### Public Endpoints (No Auth)

- Base domain: `https://tennis.paris.fr`
- Landing page: `https://tennis.paris.fr/tennis/`
- SSO login: `https://moncompte.paris.fr/*`
- LiveIdentity captcha API: `https://captcha.liveidentity.com/captcha/*`

### Requires Authentication

- Search page UI
- AJAX availability endpoint
- Booking submission
- Confirmation pages

### Requires Auth + Anti-Bot Tokens

- AJAX availability fetch (li-antibot-token, li-antibot-token-code)
- Booking form submission (li-antibot-token, li-antibot-token-code)
- Both also require `captchaRequestId`

---

## API vs Browser Access

### Browser-Based (Playwright Required)

- Login flow (SSO redirect chain)
- Search page navigation
- Cookie/session management
- Anti-bot token extraction from page

**Why Browser Required:**

- LiveIdentity tokens injected via JavaScript
- Session cookies set through redirects
- Form actions dynamically generated

### API-Based (Could Use Requests)

- LiveIdentity captcha API (standalone)
- Availability AJAX endpoint (if you have tokens)

**However:** The system uses browser (Playwright) for everything because:

1. Tokens are JavaScript-injected
2. Session management is complex
3. Anti-bot detection requires full browser fingerprint

---

## Anti-Bot Token System

### LiveIdentity Token Flow

**Token Sources:**

- `li-antibot-token` - Hidden input field (name: `li-antibot-token`)
- `li-antibot-token-code` - Hidden input field (name: `li-antibot-token-code`)

**Token Lifecycle:**

1. Tokens injected by LiveIdentity JS on page load
2. Read via `_read_li_antibot_tokens()` (line 887)
3. Validated via `_is_valid_li_token()` (line 915)
4. Refreshed via `_refresh_li_antibot_tokens()` (line 927) if invalid
5. Included in all AJAX/form submissions

**Validation Check:** ✓ VERIFIED

- Token must exist (not empty)
- Token code must exist (not empty)
- Both must be non-placeholder values

**Where Used:**

- AJAX availability fetch (line 1246-1251)
- Reservation form submission (line 1839-1844)

---

## Key Constants & Selectors

### URL Query Patterns

```python
SEARCH_RESULTS_QUERY = "page=recherche&action=rechercher_creneau"  # Line 88
SEARCH_SLOTS_AJAX_PATH = "Portal.jsp?page=recherche&action=ajax_rechercher_creneau"  # Line 89
```

### LiveIdentity Version

```python
LIVEIDENTITY_JS_VERSION = "v4"  # Line 48 in captcha_solver.py
```

---

## Environment Variable Summary

**From .env.example:**

- `PARIS_TENNIS_BASE_URL` - Not in .env.example (defaults to
  https://tennis.paris.fr)
- `PARIS_TENNIS_LOGIN_URL` - Not in .env.example (defaults to
  https://tennis.paris.fr/tennis/)
- `PARIS_TENNIS_SEARCH_URL` - Not in .env.example (defaults to Portal.jsp URL)

**Note:** Paris Tennis URLs are hardcoded with sensible defaults. No need to set
env vars unless URLs change.

---

## Data Models

### URL-Related Data Structures

**CourtSlot** (line 124-142 in paris_tennis.py):

- Contains facility codes, court IDs, dates
- Used to construct booking URLs

**BookingResult** (line 144-152):

- Contains confirmation ID after successful booking

**LiveIdentityConfig** (line 61-71 in captcha_solver.py):

- Contains `base_url` for captcha API
- Extracted from page config

---

## Security Notes

### CAPTCHA Bypass via 2Captcha

- System uses 2Captcha API to solve image captchas
- Configured via `CAPTCHA_API_KEY` env variable
- LiveIdentity captchas sent to 2Captcha workers
- Cost: ~$0.001-0.003 per solve

### Session Management

- Cookies stored in Playwright browser context
- Session persists across searches
- Login state checked via navbar selectors

### Anti-Bot Evasion

- Playwright-stealth plugin used
- Browser fingerprint randomization
- Anti-bot tokens required for all protected endpoints

---

## Testing Evidence

**Test Coverage:** ✓ VERIFIED

Key test files:

- `tests/test_paris_tennis.py` - URL construction tests (lines 428-455,
  1434-1463)
- `tests/test_captcha_solver.py` - LiveIdentity URL tests (lines 361, 492,
  653, 693)

**Test URLs Used:**

- `https://example.com/tennis/jsp/site/Portal.jsp?...` (mock URLs)
- `https://tennis.paris.fr/booking` (test fixtures)

---

## Open Questions

**None identified.** All URLs are well-documented and actively used.

---

## Code References

| Feature                  | File                             | Lines          |
| ------------------------ | -------------------------------- | -------------- |
| URL configuration        | `src/config/settings.py`         | 89-98          |
| Base URLs                | `src/services/paris_tennis.py`   | 183-185        |
| Login flow               | `src/services/paris_tennis.py`   | 207-271        |
| Search page navigation   | `src/services/paris_tennis.py`   | 477, 577       |
| AJAX availability        | `src/services/paris_tennis.py`   | 1217-1299      |
| Reservation form         | `src/services/paris_tennis.py`   | 1799-1870      |
| LiveIdentity config      | `src/services/captcha_solver.py` | 61-71, 631-639 |
| LiveIdentity transaction | `src/services/captcha_solver.py` | 1004-1010      |
| LiveIdentity challenge   | `src/services/captcha_solver.py` | 1051-1060      |
| LiveIdentity validation  | `src/services/captcha_solver.py` | 1103-1112      |
