# RainBot Implementation Plan

## Current Status

### Summary
Phase 6 (Full Integration) is complete. All core booking functionality is implemented with the booking workflow, CAPTCHA solving, and notifications working together.

### What Exists
- [x] PRD.md - Complete product requirements
- [x] pyproject.toml - Dependencies configured (selenium, 2captcha, gspread, etc.)
- [x] main.py - Entry point with scheduler setup
- [x] ralph.py - Loop runner utility for development
- [x] src/ - Core structure with data models, Google Sheets service, browser utility, Paris Tennis service, CAPTCHA solver, and notification service
- [x] tests/ - 187 unit tests passing (models, services, browser, Paris Tennis, CAPTCHA solver, notifications, cron jobs, locking, timezone)
- [x] PLAN.md - This file

### Remaining Work
1. **Deployment**: Scaleway cloud deployment (Docker, docker-compose)

### Known Issues
1. **Partner Email Optional** - `partner_email` is optional in BookingRequest, but PRD says both user AND partner should receive reminders. The code handles this gracefully by skipping partners without email.
2. **CSS Selectors are Placeholders** - The Paris Tennis service uses generic CSS selectors that need to be updated based on the actual tennis.paris.fr website structure.
3. **Facility Address Extraction** - The `data-facility-address` attribute may need adjustment based on actual website structure.
4. **Missing Integration Tests** - Phase 6 integration tests are incomplete.

### Resolved Issues
1. **facility_address not saved to Google Sheets** - Fixed: `add_booking()` now saves `facility_address` to the spreadsheet so that match day reminders include the facility address.
2. **Race Condition in Booking Job** - Fixed: Multiple booking job instances could run concurrently, causing duplicate bookings for the same user. Now uses a locking mechanism via Google Sheets `Locks` worksheet to prevent concurrent processing of the same user. Locks expire after 5 minutes to prevent deadlocks.
3. **Partner Reminder Shows Wrong Name** - Fixed: When sending match day reminders to partners, the email incorrectly showed the partner's own name as who they were playing with, instead of the user's name. Now the `send_match_day_reminder` function accepts a `player_name` parameter to correctly display the user's name to partners.
4. **Timezone Bug in Day-of-Week Filtering** - Fixed: The booking job used `datetime.now()` without timezone awareness, causing incorrect day-of-week detection when the server runs in UTC but users are in Paris timezone. Now uses Paris timezone consistently for all date/time comparisons.
5. **Timezone Bug in _get_next_booking_date** - Fixed: The `_get_next_booking_date` method in `paris_tennis.py` used `datetime.now()` without timezone awareness, inconsistent with the rest of the codebase. Now uses `now_paris()` for consistent Paris timezone handling when calculating the next booking date.
6. **Timezone Bug in Booking.from_dict()** - Fixed: The `from_dict()` method in `booking.py` used `datetime.now()` as a fallback for invalid date values, which was inconsistent with the Paris timezone used elsewhere. Now uses `now_paris()` for consistency. Also fixed tests in `test_cron_jobs.py` to use Paris timezone functions (`today_weekday_paris()`, `now_paris()`) instead of naive `datetime.now()` to prevent test flakiness in different timezones.
7. **Test Assertion for Future Dates Only** - Fixed: The `test_get_next_booking_date_future` test had an overly permissive assertion that allowed same-day booking dates. Per PRD section 5.1 "Future dates only: Cannot book same-day courts", the test now correctly asserts that booking dates are strictly in the future (> today, not >= today).
8. **Numeric String day_of_week Parsing** - Fixed: The `BookingRequest.from_dict()` method failed to parse numeric strings like `"0"` or `"1"` for `day_of_week` (which Google Sheets may return). It only handled integer values and string enum names. Now tries to parse as integer first before falling back to enum name lookup.
9. **Missing Time Boundary Validation** - Fixed: Per PRD section 5.1 "Time boundaries: Courts available from 8:00 to 22:00", the `BookingRequest.from_dict()` method now validates and clamps `time_start` and `time_end` to the valid booking hours (08:00-22:00). Invalid or empty times default to boundary values. If time_start > time_end, they are automatically swapped. Added `MIN_BOOKING_TIME` and `MAX_BOOKING_TIME` constants for clarity.
10. **Time String Normalization Bug** - Fixed: The `is_time_in_range()` method used string comparison which failed for single-digit hour formats (e.g., "9:00" vs "08:00"). The Paris Tennis website may return times in "H:MM" format instead of "HH:MM", causing valid times like "9:00" to be incorrectly rejected. Added `normalize_time()` function that pads single-digit hours and minutes with leading zeros. Updated both `is_time_in_range()` and `_validate_time()` to use this normalization for consistent time comparisons.
11. **Pending Booking Check Too Restrictive** - Fixed: The `has_pending_booking()` method in `google_sheets.py` was checking `booking.date >= today`, which incorrectly considered already-played bookings as "pending" on the same day. Per PRD section 5.1 "One active booking per user: Users cannot have multiple pending reservations", a booking that has already happened (end time has passed) should not prevent new bookings. Now the check properly considers: (1) future date bookings are pending, (2) today's bookings are only pending if the end time hasn't passed yet. This allows users to book for next week after their same-day booking has finished.

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

- [x] Create src/__init__.py
- [x] Create src/schedulers/__init__.py
- [x] Create src/schedulers/cron_jobs.py with booking_job and send_reminder stubs
- [x] Create src/config/settings.py for environment variables
- [x] Create basic tests to verify structure
- [x] Fix pyproject.toml hatch build configuration

### Phase 2: Data Layer (COMPLETED)
**Goal**: User and booking request management via Google Sheets

- [x] Create src/models/user.py - User model with eligibility check
- [x] Create src/models/booking_request.py - BookingRequest with time range and from_dict
- [x] Create src/models/booking.py - Booking model with is_today check
- [x] Create src/services/google_sheets.py - Full CRUD for users, requests, bookings
- [x] Add tests/test_models.py - 13 tests for data models
- [x] Add tests/test_google_sheets.py - 8 tests for sheets service
- [x] Export models and services via __init__.py

### Phase 3: Paris Tennis Integration (COMPLETED)
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

### Phase 6: Full Integration (COMPLETED)
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

**Next Step**: Continue Phase 7 (Deployment) - Configure Scaleway deployment and set up monitoring/logging.

Phase 6 is complete with:
- booking_job(): Full booking workflow implementation
  - Loads active requests from Google Sheets
  - Filters eligible users with active subscriptions
  - Processes requests for today's day of week
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
  - `send_reminder` at 2:00 AM Paris time daily
- User data is stored in Google Sheets (requires service account credentials)
- CAPTCHA solving uses 2captcha-python library
- Browser utility uses webdriver-manager for automatic ChromeDriver management
- All tests passing as of facility address feature implementation

---

## Google Sheets Structure

The spreadsheet should have four worksheets:

### Users Sheet
| Column | Description |
|--------|-------------|
| id | Unique user identifier |
| name | User's display name (for personalized emails) |
| email | User's notification email |
| paris_tennis_email | Paris Tennis login email |
| paris_tennis_password | Paris Tennis password |
| subscription_active | true/false for subscription status |
| phone | Optional phone number |

### BookingRequests Sheet
| Column | Description |
|--------|-------------|
| id | Unique request identifier |
| user_id | Reference to user |
| day_of_week | monday-sunday or 0-6 |
| time_start | HH:MM format |
| time_end | HH:MM format |
| facility_preferences | Comma-separated facility codes |
| court_type | indoor/outdoor/any |
| partner_name | Playing partner's name |
| partner_email | Partner's email for reminders |
| active | true/false |

### Bookings Sheet
| Column | Description |
|--------|-------------|
| id | Unique booking identifier |
| user_id | Reference to user |
| request_id | Reference to booking request |
| facility_name | Tennis facility name |
| facility_code | Facility identifier |
| court_number | Court number |
| date | ISO format date |
| time_start | HH:MM format |
| time_end | HH:MM format |
| partner_name | Playing partner |
| confirmation_id | Paris Tennis confirmation |
| facility_address | Facility street address (for reminders) |
| created_at | When booking was made |

### Locks Sheet
| Column | Description |
|--------|-------------|
| user_id | User currently being processed |
| locked_at | ISO timestamp when lock was acquired |
| locked_by | UUID of the job that holds the lock |

**Note:** The Locks sheet is automatically created by the system if it doesn't exist. Locks expire after 5 minutes to prevent deadlocks if a job crashes.
