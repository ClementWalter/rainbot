# RainBot Implementation Plan

## Current Status

### Summary
Phase 4 (CAPTCHA Solving) is complete. The 2Captcha service has been implemented and integrated with the Paris Tennis booking flow.

### What Exists
- [x] PRD.md - Complete product requirements
- [x] pyproject.toml - Dependencies configured (selenium, 2captcha, gspread, etc.)
- [x] main.py - Entry point with scheduler setup
- [x] ralph.py - Loop runner utility for development
- [x] src/ - Core structure with data models, Google Sheets service, browser utility, Paris Tennis service, and CAPTCHA solver
- [x] tests/ - Unit tests for models, services, browser, Paris Tennis, and CAPTCHA solver (83 tests passing)
- [x] PLAN.md - This file

### Remaining Work
1. **Notifications**: Email confirmations and reminders
2. **Full integration**: Wire everything together in cron_jobs
3. **Deployment**: Scaleway cloud deployment

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
│   ├── captcha_solver.py    # 2Captcha integration [TODO]
│   ├── notification.py      # Email/SMS notifications [TODO]
│   └── google_sheets.py     # GSheet data storage [DONE]
├── schedulers/
│   ├── __init__.py
│   └── cron_jobs.py         # booking_job, send_remainder [STUB]
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
- [x] Create src/schedulers/cron_jobs.py with booking_job and send_remainder stubs
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

### Phase 5: Notifications
**Goal**: Send booking confirmations and reminders

- [ ] Create src/services/notification.py
- [ ] Implement booking confirmation emails
- [ ] Implement match day reminders (send_remainder job)
- [ ] Add tests for notification service

### Phase 6: Full Integration
**Goal**: End-to-end booking automation

- [ ] Wire all services together in booking_job
- [ ] Implement priority logic for facility preferences
- [ ] Add booking history tracking
- [ ] Add comprehensive integration tests

### Phase 7: Deployment
**Goal**: Deploy to Scaleway cloud

- [ ] Create Dockerfile
- [ ] Create docker-compose.yml
- [ ] Configure Scaleway deployment
- [ ] Set up monitoring and logging

---

## Next Action

**Start Phase 5**: Implement notification service.

Next step: Create `src/services/notification.py` with email sending capabilities.

Phase 4 is complete with:
- CaptchaSolverService supporting reCAPTCHA v2/v3 and image CAPTCHAs
- Automatic CAPTCHA detection and solving from page
- Integration with Paris Tennis booking flow
- Retry logic for failed solving attempts
- 21 tests covering all CAPTCHA solver functionality

---

## Notes

- The scheduler in main.py runs:
  - `booking_job` on interval (configurable via HOUR, MINUTE, SECOND env vars)
  - `booking_job` at 8:00 AM Paris time (every 2 seconds for first 10 seconds)
  - `send_remainder` at 2:00 AM Paris time daily
- User data is stored in Google Sheets (requires service account credentials)
- CAPTCHA solving uses 2captcha-python library
- Browser utility uses webdriver-manager for automatic ChromeDriver management
- All 83 tests passing as of Phase 4 CAPTCHA solver implementation

---

## Google Sheets Structure

The spreadsheet should have three worksheets:

### Users Sheet
| Column | Description |
|--------|-------------|
| id | Unique user identifier |
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
| created_at | When booking was made |
