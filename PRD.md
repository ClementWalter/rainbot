# RainBot - Product Requirements Document

## 1. Overview

### 1.1 Product Summary

RainBot is an automated tennis court booking service for **Paris municipal
tennis facilities** (Tennis Parisiens). The service enables users to
automatically secure court reservations based on their preferences without
manually competing for slots on the booking platform.

### 1.2 Problem Statement

Booking tennis courts in Paris is competitive. Popular courts and time slots are
often taken within minutes of becoming available. Users must:

- Constantly monitor the booking website
- Be available at specific release times
- Manually navigate a multi-step booking process with CAPTCHA verification
- Repeat this process weekly for regular playing schedules

### 1.3 Solution

An automated booking agent that:

- Monitors court availability on behalf of users
- Automatically completes the booking process when matching slots are found
- Handles CAPTCHA verification
- Notifies users and their partners of successful bookings

---

## 2. Target Users

### 2.1 Primary Users

- **Regular tennis players** in Paris with consistent weekly schedules
- **Tennis groups/partners** who play together on recurring days and times
- **Busy professionals** who cannot monitor the booking website manually

### 2.2 User Prerequisites

- Valid Paris tennis account with stored credentials
- Pre-purchased ticket carnet (payment method on the platform)
- Paid subscription to the RainBot service

---

## 3. Core Features

### 3.1 Booking Request Management

Users can define their booking preferences:

| Preference               | Description                                            |
| ------------------------ | ------------------------------------------------------ |
| **Day of Week**          | Which day to book (Monday through Sunday)              |
| **Time Range**           | Preferred hours (e.g., 18:00 - 20:00)                  |
| **Facility Preferences** | Ranked list of preferred tennis facilities             |
| **Court Type**           | Indoor (covered) / Outdoor (uncovered) / No preference |
| **Partner Information**  | Name of playing partner for the booking                |
| **Active Status**        | Enable/disable the request                             |

### 3.2 Automated Booking

The bot automatically:

1. Searches for available courts matching user criteria
2. Logs into the user's Paris tennis account
3. Navigates the booking flow
4. Solves CAPTCHA challenges
5. Completes payment using the user's ticket carnet
6. Confirms the reservation

### 3.3 Notifications

- **Booking Confirmation**: Immediate notification when a court is successfully
  booked
- **Match Day Reminder**: Both player and partner receive reminders on the day
  of their match

### 3.4 Booking History

Users can view their booking history including:

- Date and time of booking
- Facility and court details
- Partner information
- Booking confirmation ID

---

## 4. User Flow

```text
┌─────────────────────────────────────────────────────────────────┐
│                         USER SETUP                              │
├─────────────────────────────────────────────────────────────────┤
│  1. User registers with their Paris tennis credentials          │
│  2. User subscribes to the service (payment)                    │
│  3. User creates booking request(s) with preferences            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AUTOMATED PROCESS                          │
├─────────────────────────────────────────────────────────────────┤
│  1. Bot monitors for available courts matching criteria         │
│  2. When match found: Bot logs into user's account              │
│  3. Bot searches and selects the court                          │
│  4. Bot solves CAPTCHA verification                             │
│  5. Bot enters partner details                                  │
│  6. Bot completes payment with user's ticket carnet             │
│  7. Bot confirms booking                                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        NOTIFICATIONS                            │
├─────────────────────────────────────────────────────────────────┤
│  • Booking confirmation sent to user                            │
│  • Match day reminder sent to user AND partner                  │
│  • Booking logged in history                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Business Rules

### 5.1 Booking Constraints

- **One active booking per user**: Users cannot have multiple pending
  reservations
- **Future dates only**: Cannot book same-day courts
- **Weekly recurrence**: Requests are for recurring day-of-week, not specific
  dates
- **Time boundaries**: Courts available from 8:00 to 22:00

### 5.2 Eligibility Rules

- User must have valid Paris tennis credentials
- User must have paid subscription status
- User's request must be marked as active
- User must have sufficient tickets in their carnet

### 5.3 Priority Logic

- First available court matching criteria is booked
- Facility preferences are checked in order (court_1 first, then court_2, etc.)
- First available time slot within the specified range is selected

---

## 6. Key Constraint: CAPTCHA Verification

The Paris tennis booking platform requires CAPTCHA verification to complete
reservations. This is a critical constraint that the bot must handle:

### 6.1 CAPTCHA Challenge

- Visual/text-based CAPTCHA presented during booking flow
- Must be solved correctly to proceed with reservation
- Failed CAPTCHA = failed booking attempt

### 6.2 Requirements

- Bot must integrate with a CAPTCHA solving service
- Solution must be fast enough to not lose the booking slot
- Multiple retries may be needed for complex CAPTCHAs

---

## 7. Notification Requirements

### 7.1 Booking Confirmation

**Trigger**: Successful court booking **Recipients**: User (booker) **Content**:

- Confirmation that booking succeeded
- Court location and facility name
- Date and time of reservation
- Partner name

### 7.2 Match Day Reminder

**Trigger**: Morning of the match day **Recipients**: User AND Partner
**Content**:

- Match time
- Facility name and address
- Court details
- Friendly reminder (bring equipment, water, etc.)

---

## 8. Success Metrics

| Metric                    | Description                                      |
| ------------------------- | ------------------------------------------------ |
| **Booking Success Rate**  | % of attempts that result in successful bookings |
| **CAPTCHA Solve Rate**    | % of CAPTCHAs successfully solved                |
| **User Satisfaction**     | % of users with successful weekly bookings       |
| **Notification Delivery** | % of notifications successfully delivered        |

---

## 9. Scope Boundaries

### 9.1 In Scope

- Automated booking for Paris municipal tennis courts
- User preference management
- CAPTCHA handling
- Email notifications to users and partners
- Booking history tracking

### 9.2 Out of Scope

- Court cancellation/modification
- Booking for non-Paris tennis facilities
- Real-time availability display to users
- Mobile application
- Payment processing (uses existing user ticket carnet)
- User account creation on Paris tennis platform

---

## 10. Risks & Mitigations

| Risk                             | Impact              | Mitigation                                               |
| -------------------------------- | ------------------- | -------------------------------------------------------- |
| Booking platform changes UI/flow | Bot stops working   | Monitor for changes, maintain adaptable automation       |
| CAPTCHA system updates           | Booking failures    | Use robust CAPTCHA solving service with multiple methods |
| Platform blocks automation       | Service unavailable | Implement human-like behavior patterns                   |
| User credentials compromised     | Security breach     | Secure credential storage, encourage unique passwords    |
| High demand, limited slots       | User frustration    | Set expectations, prioritize based on subscription tier  |

---

## 11. Technical Requirements

The whole stack NEEDS to be deployed to Scaleway cloud. Use the Scaleway skill
to understand how to deploy the stack.

---

## 12. Implementation Path

See [PLAN.md](PLAN.md) for the implementation path.
