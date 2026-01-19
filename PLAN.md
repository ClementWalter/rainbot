# RainBot Implementation Plan

## Current Status

### Summary
Phase 1 is complete. The basic project structure is in place and main.py can now import its dependencies. The core business logic (booking, CAPTCHA, notifications) still needs implementation.

### What Exists
- [x] PRD.md - Complete product requirements
- [x] pyproject.toml - Dependencies configured (selenium, 2captcha, gspread, etc.)
- [x] main.py - Entry point with scheduler setup
- [x] ralph.py - Loop runner utility for development
- [x] src/ - Basic structure with stub implementations
- [x] tests/ - Basic structure tests
- [x] PLAN.md - This file

### Remaining Work
1. **Data layer**: Google Sheets integration for user/booking data
2. **Paris Tennis service**: Website automation with Selenium
3. **CAPTCHA solving**: 2Captcha integration
4. **Notifications**: Email confirmations and reminders
5. **Full integration**: Wire everything together
6. **Deployment**: Scaleway cloud deployment

---

## Architecture Overview

Based on the PRD and existing main.py, the architecture should be:

```
src/
├── __init__.py
├── config/
│   ├── __init__.py
│   └── settings.py          # Environment variables, constants
├── models/
│   ├── __init__.py
│   ├── booking_request.py   # User booking preferences
│   ├── booking.py           # Completed booking record
│   └── user.py              # User credentials and info
├── services/
│   ├── __init__.py
│   ├── paris_tennis.py      # Paris tennis website interaction
│   ├── captcha_solver.py    # 2Captcha integration
│   ├── notification.py      # Email/SMS notifications
│   └── google_sheets.py     # GSheet data storage
├── schedulers/
│   ├── __init__.py
│   └── cron_jobs.py         # booking_job, send_remainder
└── utils/
    ├── __init__.py
    └── browser.py           # Selenium browser setup
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

### Phase 2: Data Layer (NEXT)
**Goal**: User and booking request management via Google Sheets

- [ ] Create src/services/google_sheets.py
- [ ] Create src/models/booking_request.py
- [ ] Create src/models/user.py
- [ ] Implement reading user preferences from Google Sheets
- [ ] Add tests for data layer

### Phase 3: Paris Tennis Integration
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

**Implement Phase 2**: Create the data layer with Google Sheets integration.

This is the next priority because:
1. The booking system needs to read user preferences and credentials
2. It establishes where data comes from for all other services
3. It's required before implementing the booking logic

---

## Notes

- The scheduler in main.py runs:
  - `booking_job` on interval (configurable via HOUR, MINUTE, SECOND env vars)
  - `booking_job` at 8:00 AM Paris time (every 2 seconds for first 10 seconds)
  - `send_remainder` at 2:00 AM Paris time daily
- User data is likely stored in Google Sheets (gspread dependency)
- CAPTCHA solving uses 2captcha-python library
