# RainBot Implementation Plan

## Current Status

### Summary
Phase 2 (Data Layer) is complete. The data models and Google Sheets service are implemented and tested. The project can now read users, booking requests, and bookings from Google Sheets.

### What Exists
- [x] PRD.md - Complete product requirements
- [x] pyproject.toml - Dependencies configured (selenium, 2captcha, gspread, etc.)
- [x] main.py - Entry point with scheduler setup
- [x] ralph.py - Loop runner utility for development
- [x] src/ - Core structure with data models and Google Sheets service
- [x] tests/ - Unit tests for models and services (27 tests passing)
- [x] PLAN.md - This file

### Remaining Work
1. **Paris Tennis service**: Website automation with Selenium
2. **CAPTCHA solving**: 2Captcha integration
3. **Notifications**: Email confirmations and reminders
4. **Full integration**: Wire everything together in cron_jobs
5. **Deployment**: Scaleway cloud deployment

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
│   ├── paris_tennis.py      # Paris tennis website interaction [TODO]
│   ├── captcha_solver.py    # 2Captcha integration [TODO]
│   ├── notification.py      # Email/SMS notifications [TODO]
│   └── google_sheets.py     # GSheet data storage [DONE]
├── schedulers/
│   ├── __init__.py
│   └── cron_jobs.py         # booking_job, send_remainder [STUB]
└── utils/
    ├── __init__.py
    └── browser.py           # Selenium browser setup [TODO]
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

### Phase 3: Paris Tennis Integration (NEXT)
**Goal**: Interact with the Paris Tennis booking website

- [ ] Create src/utils/browser.py (Selenium setup)
- [ ] Create src/services/paris_tennis.py
- [ ] Implement login functionality
- [ ] Implement availability search
- [ ] Implement booking flow
- [ ] Add tests for tennis service

### Phase 4: CAPTCHA Solving
**Goal**: Integrate 2Captcha for verification

- [ ] Create src/services/captcha_solver.py
- [ ] Integrate with booking flow
- [ ] Add retry logic
- [ ] Add tests for captcha service

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

**Implement Phase 3**: Create the Paris Tennis integration.

This is the next priority because:
1. The core booking logic depends on interacting with the Paris Tennis website
2. Data layer is ready to provide user credentials and booking preferences
3. This is the most complex service and central to the product

---

## Notes

- The scheduler in main.py runs:
  - `booking_job` on interval (configurable via HOUR, MINUTE, SECOND env vars)
  - `booking_job` at 8:00 AM Paris time (every 2 seconds for first 10 seconds)
  - `send_remainder` at 2:00 AM Paris time daily
- User data is stored in Google Sheets (requires service account credentials)
- CAPTCHA solving uses 2captcha-python library
- All 27 tests passing as of Phase 2 completion

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
