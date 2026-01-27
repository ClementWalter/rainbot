# Booking Flow Analysis Report

Generated: 2026-01-27

## Summary

The booking flow in `src/schedulers/cron_jobs.py` **performs login FIRST**, then
searches for available courts. This is the CRITICAL finding - authentication
happens BEFORE any slot availability checks.

---

## Exact Order of Operations

### High-Level Flow (Lines 40-127)

```
booking_job() [Line 40]
  └─> _booking_job_async() [Line 58]
      ├─ Get active booking requests [Line 70]
      ├─ Get eligible users [Line 78]
      ├─ Filter & group requests by user [Lines 84-90]
      └─ For each user:
          ├─ Acquire lock [Line 98]
          ├─ Check pending bookings [Line 107]
          └─ Process each request [Line 114]
              └─> _process_booking_request_async()
```

### Detailed Processing Flow (Lines 129-297)

**✓ VERIFIED** The exact sequence in `_process_booking_request_async()`:

#### Phase 1: Authentication (Lines 149-168)

```python
Line 149: async with create_paris_tennis_session() as tennis_service:
Line 151:     logger.info(f"Logging in for user {user.email}")
Line 152:     login_success = await tennis_service.login(
Line 153:         user.paris_tennis_email, user.paris_tennis_password
Line 154:     )
Line 156:     if not login_success:
Line 157:         logger.error(f"Login failed for user {user.email}")
Line 158-167: [Error handling and notification]
Line 168:     return False  # Exit if login fails
```

**Key Point**: Login happens at line 152-154. If login fails (line 156), the
function returns False immediately at line 168. **No court search occurs without
successful login.**

#### Phase 2: Search for Courts (Lines 170-172)

```python
Line 170: # Search for available courts
Line 171: logger.info(f"Searching for courts matching request {request.id}")
Line 172: available_slots = await tennis_service.search_available_courts(request)
```

**Key Point**: Court search only executes AFTER successful login (line 172).
This is sequential - no parallelization.

#### Phase 3: Handle Search Results (Lines 174-212)

```python
Line 174: if not available_slots:
Line 175:     logger.info(f"No available slots found for request {request.id}")
Line 176-211: [Send notification, mark as sent]
Line 212:     return False
```

#### Phase 4: Attempt Booking (Lines 214-273)

```python
Line 214: logger.info(f"Found {len(available_slots)} available slots")
Line 222: for slot in available_slots:
Line 228:     result = await tennis_service.book_court(...)
Line 236:     if result.success:
Line 250:         booking = _create_booking_from_result(...)
Line 253:         sheets.add_booking(booking)
Line 270:         notification.send_booking_confirmation(user, booking)
Line 273:         return True  # Success - exit
```

---

## What Happens Before vs After Authentication

### BEFORE Authentication (Lines 58-148)

**✓ VERIFIED** These operations occur WITHOUT logging into Paris Tennis:

1. **Database Operations** (Lines 70-71)
   - Fetch active booking requests from SQLite
   - `requests_db_service.get_active_booking_requests()`

2. **Google Sheets Operations** (Lines 78-81)
   - Fetch eligible users (subscription status, credentials)
   - `sheets.get_eligible_users()`
   - Build user map and filter requests

3. **Lock Management** (Line 98)
   - Acquire user lock to prevent concurrent processing
   - `sheets.acquire_user_lock(user.id, job_id)`

4. **Pending Check** (Line 107)
   - Check if user has pending booking
   - `sheets.has_pending_booking(user.id)`

**No Paris Tennis interaction until line 149.**

### AFTER Authentication (Lines 170-273)

**✓ VERIFIED** These operations require an active Paris Tennis session:

1. **Court Search** (Line 172)
   - `tennis_service.search_available_courts(request)`
   - Navigates to Paris Tennis search page
   - Submits search form with preferences
   - Parses availability results

2. **Court Booking** (Line 228)
   - `tennis_service.book_court(slot, ...)`
   - Submits booking form
   - Handles CAPTCHA if present
   - Confirms reservation

3. **Post-Booking** (Lines 253-270)
   - Save to Google Sheets
   - Update carnet balance
   - Send confirmation emails

---

## Paris Tennis Service Implementation

### Login Method (paris_tennis.py:207-271)

**✓ VERIFIED** Login process:

```python
Line 207: async def login(self, email: str, password: str) -> bool:
Line 221:     await self.page.goto(self.login_url)
Line 224:     await self._accept_cookie_banner()
Line 227:     await self._click_login_entrypoint()
Line 230:     if await self._is_logged_in():  # Check if already logged in
Line 231:         self._logged_in = True
Line 232:         return True
Line 237:     await self.page.fill("#username", email)
Line 240:     await self.page.fill("#password", password)
Line 246:     await self.page.click("button[type='submit']")
Line 252:     if await self._solve_captcha_if_present():
Line 253:         await self._submit_login_form_if_present()
Line 257:     if await self._is_logged_in():
Line 258:         self._logged_in = True
Line 259:         return True
```

**Key Points**:

- Navigates to login URL (line 221)
- Fills credentials (lines 237-240)
- Submits form (line 246)
- Handles CAPTCHA if present (lines 252-253)
- Verifies login success (line 257)
- Sets internal `_logged_in` flag (line 258)

### Search Method (paris_tennis.py:445-524)

**✓ VERIFIED** Search process:

```python
Line 445: async def search_available_courts(self, request, target_date) -> list[CourtSlot]:
Line 470:     logger.info(f"Searching courts for {target_date.strftime('%Y-%m-%d')}")
Line 477:     await self.page.goto(self.search_url)
Line 478:     await self._accept_cookie_banner()
Line 480:     facility_names = await self._resolve_facility_preferences(request)
Line 481:     captcha_request_id = await self._ensure_search_results_page(
Line 482:         target_date=target_date,
Line 483:         facility_names=facility_names,
Line 484:         hour_range=hour_range,
Line 485:         sel_in_out=sel_in_out,
Line 486:     )
Line 505:     html, captcha_request_id = await self._fetch_availability_html(...)
Line 524:     slots = self._parse_available_slots_html(...)
```

**Key Points**:

- Assumes already logged in (no login check)
- Navigates to search URL (line 477)
- Submits search form (line 481-486)
- Fetches availability via AJAX (line 505)
- Parses results (line 524)

---

## Critical Findings

### 1. Sequential Dependencies

```
LOGIN (Line 152)
  ↓ [MUST succeed]
SEARCH (Line 172)
  ↓ [If slots found]
BOOK (Line 228)
```

**No parallelization**. Each step blocks the next.

### 2. Early Exit on Login Failure

```python
Line 156: if not login_success:
Line 168:     return False  # No search performed
```

If login fails, the entire booking attempt aborts. No slot checking occurs.

### 3. Session Context Manager

```python
Line 149: async with create_paris_tennis_session() as tennis_service:
```

The entire process (login → search → book) occurs within a single Playwright
session. The browser context remains active throughout.

### 4. Authentication State

The `tennis_service` maintains internal state:

- `self._logged_in` flag (set in login method, line 258)
- Playwright page session with cookies
- No re-login during search/booking

### 5. Lock Timing

```
Line 98:  Acquire lock (BEFORE login)
Line 152: Login
Line 172: Search
Line 121: Release lock (in finally block)
```

The lock is held during the entire login → search → book cycle. This prevents
concurrent processing but also blocks other requests if login is slow.

---

## Potential Issues

### Issue 1: Login Latency Blocks Availability Checks

**Problem**: If login takes 5-10 seconds (CAPTCHA, slow network), no slots are
checked during that time. Slots could be claimed by others.

**Evidence**: Lines 152-168 show login is synchronous blocking operation.

### Issue 2: No Pre-Validation of Slot Existence

**Problem**: System doesn't check if ANY slots exist before attempting login.
Could waste login attempts on days with zero availability.

**Evidence**: Line 172 only executes AFTER login completes at line 152.

### Issue 3: Single Session for Multiple Slots

**Advantage**: Reuses authenticated session for booking attempts. **Risk**: If
session expires during slot iteration, all remaining attempts fail.

**Evidence**: Lines 222-273 show multiple `book_court()` calls use same
`tennis_service` instance.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│ booking_job() [Line 40]                                 │
│   └─> _booking_job_async() [Line 58]                   │
└─────────────────────────────────────────────────────────┘
                          │
                          ├─ Fetch Data (Lines 70-90)
                          │  ├─ SQLite: Active requests
                          │  ├─ Sheets: Eligible users
                          │  └─ Filter by user
                          │
                          └─ For Each User ────────────┐
                                                        │
┌───────────────────────────────────────────────────────▼─┐
│ _process_booking_request_async() [Line 129]            │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │ PHASE 1: Authentication [Lines 149-168]       │    │
│  │ ─────────────────────────────────────────────  │    │
│  │  • Create session (Playwright context)        │    │
│  │  • Navigate to login URL                      │    │
│  │  • Fill credentials                           │    │
│  │  • Submit form                                │    │
│  │  • Handle CAPTCHA if present                  │    │
│  │  • Verify login success                       │    │
│  │  └─> IF FAIL: Return False (EXIT) ────────────┼────┼─> END
│  │      IF SUCCESS: Continue ↓                   │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │ PHASE 2: Search [Lines 170-172]               │    │
│  │ ─────────────────────────────────────────────  │    │
│  │  • Navigate to search URL                     │    │
│  │  • Submit search form with preferences        │    │
│  │  • Fetch availability via AJAX                │    │
│  │  • Parse results                              │    │
│  │  └─> IF NO SLOTS: Send notification (EXIT) ───┼────┼─> END
│  │      IF SLOTS FOUND: Continue ↓               │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │ PHASE 3: Booking [Lines 222-273]              │    │
│  │ ─────────────────────────────────────────────  │    │
│  │  • For each available slot:                   │    │
│  │    ├─ Submit booking form                     │    │
│  │    ├─ Handle CAPTCHA if present               │    │
│  │    ├─ Confirm reservation                     │    │
│  │    └─> IF SUCCESS: Save & notify (EXIT) ──────┼────┼─> END
│  │                                                │    │
│  │  • All slots failed: Send failure notification│    │
│  └────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## Key Takeaways

1. **Login happens FIRST** (line 152) - always before slot checking
2. **No parallel operations** - strictly sequential: login → search → book
3. **Early exit on login failure** - no search attempted if login fails
4. **Single session reuse** - login once, search/book multiple times within same
   session
5. **Lock held throughout** - from before login (line 98) until after
   booking/failure (line 121)

---

## File References

| File                           | Lines   | Purpose                                              |
| ------------------------------ | ------- | ---------------------------------------------------- |
| `src/schedulers/cron_jobs.py`  | 40-55   | Entry point `booking_job()`                          |
| `src/schedulers/cron_jobs.py`  | 58-127  | Main loop `_booking_job_async()`                     |
| `src/schedulers/cron_jobs.py`  | 129-297 | Request processor `_process_booking_request_async()` |
| `src/services/paris_tennis.py` | 207-271 | Login implementation                                 |
| `src/services/paris_tennis.py` | 445-524 | Search implementation                                |

---

## Conclusion

The current booking flow architecture prioritizes **authentication-first**,
which ensures all operations occur within a valid session but introduces latency
before any availability checking. Login failures or CAPTCHA challenges delay
slot discovery, potentially causing missed booking opportunities.

**✓ VERIFIED**: All findings confirmed by reading actual source code and tracing
execution flow with specific line numbers.
