# RainBot Web Application Plan

## Overview

A mobile-first web application for managing tennis court booking requests. Users
can:

- Login with their Paris Tennis credentials
- Create/manage multiple booking "alarms" (like phone alarm app)
- Toggle requests active/inactive
- View upcoming bookings

## Data Structure Analysis

### Current Google Sheet Structure

**Requests Sheet Columns:**

| Column | Field | Type | Description | |--------|-------|------|-------------|
| Username | user_id | string | User's email | | MatchDay | day_of_week | enum |
Lundi-Dimanche (0-6) | | HourFrom | time_start | int→string | Start hour (8-22)
| | HourTo | time_end | int→string | End hour (8-22) | | InOut | court_type |
enum | Couvert/Découvert/Any | | Court_0-4 | facility_preferences | string[] |
Preferred courts | | Partenaire/full name | partner_name | string | Partner's
name | | Active | active | boolean | Toggle on/off | | RowID | id | string |
Unique identifier |

**Historique Sheet (Bookings):** | Column | Description |
|--------|-------------| | ID | Booking UUID | | UserID | Owner's email | |
RequestID | Source request | | FacilityName | Court location | | CourtNumber |
Court # | | Date | Booking date | | TimeStart/End | Time slot | |
PartnerName/Email | Guest info | | ConfirmationID | Paris Tennis ref |

### User Model (Derived from Requests)

```
- id: email
- paris_tennis_email: same as id
- paris_tennis_password: from env (shared) or per-user
- name: optional
- subscription_active: boolean
- carnet_balance: int (tickets remaining)
```

## Architecture Decision

### Option A: Keep Google Sheets as Backend ✓ SELECTED

**Pros:**

- Zero additional infrastructure
- Already working and tested
- Easy for admin to manage
- No migration needed

**Cons:**

- API rate limits
- Limited query capabilities

### Implementation: Thin API Layer

Create a FastAPI backend that:

1. Authenticates users (validates Paris Tennis credentials)
2. CRUD operations via existing GoogleSheetsService
3. Serves static frontend

## Tech Stack

### Frontend

- **React** + TypeScript
- **Tailwind CSS** for styling
- **Vite** for build
- Mobile-first responsive design
- PWA-ready (installable on phone)

### Backend

- **FastAPI** (Python)
- Reuse existing `GoogleSheetsService`
- JWT authentication
- Single Docker container with frontend static files

## UI/UX Design

### Mobile-First Alarm-Style Interface

```
┌─────────────────────────────┐
│  🎾 RainBot                 │
│  ──────────────────────────│
│                             │
│  ┌─────────────────────────┐│
│  │ 🔔 Lundi 18:00-20:00   ││
│  │ Suzanne Lenglen         ││
│  │ Couvert • Pascal A.    [●]│
│  └─────────────────────────┘│
│                             │
│  ┌─────────────────────────┐│
│  │ 🔕 Mercredi 19:00-21:00││
│  │ Elisabeth, Atlantique   ││
│  │ Découvert • -          [○]│
│  └─────────────────────────┘│
│                             │
│  ┌─────────────────────────┐│
│  │ 🔔 Samedi 10:00-12:00  ││
│  │ Any court               ││
│  │ Any • Marie D.         [●]│
│  └─────────────────────────┘│
│                             │
│         [ + Nouveau ]       │
│                             │
│  ─────────────────────────  │
│  📅 Prochaines réservations │
│                             │
│  • Dim 26/01 14:00          │
│    Lenglen Court 3          │
│                             │
└─────────────────────────────┘
```

### Color Scheme

- Primary: Tennis green (#2E7D32)
- Secondary: Clay orange (#D84315)
- Background: Light gray (#F5F5F5)
- Cards: White with subtle shadow

### Key UI Components

1. **Request Card** (alarm-style)
   - Day + time range
   - Court preferences (abbreviated)
   - Court type icon (indoor/outdoor)
   - Partner name
   - Toggle switch (active/inactive)
   - Swipe to delete

2. **Add/Edit Modal**
   - Day picker (circular like alarm)
   - Time range slider
   - Court type selector
   - Court preference multi-select
   - Partner name/email fields

3. **Upcoming Bookings** (bottom section)
   - Compact list of confirmed bookings
   - Date, time, location

## API Endpoints

```
POST   /api/auth/login          # Validate Paris Tennis credentials
GET    /api/auth/me             # Get current user info

GET    /api/requests            # List user's booking requests
POST   /api/requests            # Create new request
PATCH  /api/requests/{id}       # Update request (incl. toggle active)
DELETE /api/requests/{id}       # Delete request

GET    /api/bookings            # List user's confirmed bookings
GET    /api/facilities          # List available tennis facilities
```

## File Structure

```
rainbot/
├── src/
│   ├── api/                    # NEW: FastAPI app
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI app entry
│   │   ├── auth.py            # JWT auth
│   │   ├── routes/
│   │   │   ├── requests.py
│   │   │   ├── bookings.py
│   │   │   └── facilities.py
│   │   └── deps.py            # Dependencies
│   ├── models/                 # Existing
│   ├── services/               # Existing
│   └── ...
├── frontend/                   # NEW: React app
│   ├── src/
│   │   ├── components/
│   │   │   ├── RequestCard.tsx
│   │   │   ├── RequestForm.tsx
│   │   │   ├── BookingList.tsx
│   │   │   └── Toggle.tsx
│   │   ├── pages/
│   │   │   ├── Login.tsx
│   │   │   └── Dashboard.tsx
│   │   ├── hooks/
│   │   ├── api/
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
├── Dockerfile                  # Updated for API + static
├── docker-compose.yml          # Add web service
└── main.py                     # Existing scheduler
```

## Deployment Architecture

```
┌─────────────────────────────────────────┐
│              Scaleway VPS               │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────┐    ┌─────────────────┐│
│  │   nginx     │───▶│ rainbot-web    ││
│  │  (reverse   │    │ (FastAPI +     ││
│  │   proxy)    │    │  static files) ││
│  │  :80/:443   │    │  :8000         ││
│  └─────────────┘    └─────────────────┘│
│                                         │
│  ┌─────────────────────────────────────┐│
│  │         rainbot-scheduler          ││
│  │     (existing booking job)          ││
│  └─────────────────────────────────────┘│
│                                         │
└─────────────────────────────────────────┘
         │
         ▼
  Google Sheets API
```

## Implementation Steps

### Phase 1: Backend API (2 hours)

1. Create FastAPI app structure
2. Implement JWT auth with Paris Tennis validation
3. CRUD routes for requests
4. Read-only routes for bookings
5. Facilities endpoint

### Phase 2: Frontend (3 hours)

1. Vite + React + TypeScript setup
2. Tailwind configuration
3. Login page
4. Dashboard with request cards
5. Add/Edit request modal
6. Upcoming bookings section
7. Responsive polish

### Phase 3: Deployment (1 hour)

1. Update Dockerfile for multi-stage build
2. Update docker-compose with nginx
3. Update GitHub Actions deploy
4. SSL with Let's Encrypt (optional)

## Security Considerations

- JWT tokens with short expiry (1 hour)
- CORS restricted to domain
- Rate limiting on login endpoint
- No credential storage (validate live with Paris Tennis)
- HTTPS required in production

## Future Enhancements

- Push notifications for booking confirmations
- Calendar integration (Google Calendar, Apple)
- Booking history with stats
- Partner management
- Court preference learning (ML)
