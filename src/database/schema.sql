-- Booking requests table
-- Stores user booking preferences, migrated from Google Sheets

CREATE TABLE IF NOT EXISTS booking_requests (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    time_start TEXT NOT NULL,
    time_end TEXT NOT NULL,
    court_type TEXT NOT NULL DEFAULT 'any',
    facility_preferences TEXT,  -- JSON array as string
    partner_name TEXT,
    partner_email TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Index for efficient queries by user and active status
CREATE INDEX IF NOT EXISTS idx_requests_user_active ON booking_requests(user_id, active);

-- Bot activity logs table
-- Stores logs from the booking scheduler for user visibility
CREATE TABLE IF NOT EXISTS bot_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    timestamp TEXT DEFAULT (datetime('now')),
    level TEXT NOT NULL DEFAULT 'INFO',  -- INFO, WARNING, ERROR, SUCCESS
    message TEXT NOT NULL,
    request_id TEXT,  -- Optional: link to booking request
    facility_name TEXT,  -- Optional: facility involved
    details TEXT  -- Optional: JSON with extra details
);

-- Index for efficient queries by user
CREATE INDEX IF NOT EXISTS idx_logs_user_timestamp ON bot_logs(user_id, timestamp DESC);

-- Bookings table
-- Stores completed booking history, migrated from Google Sheets
CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    facility_name TEXT NOT NULL,
    facility_code TEXT NOT NULL,
    court_number TEXT NOT NULL,
    date TEXT NOT NULL,  -- ISO date format YYYY-MM-DD
    time_start TEXT NOT NULL,
    time_end TEXT NOT NULL,
    partner_name TEXT,
    partner_email TEXT,
    confirmation_id TEXT,
    facility_address TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bookings_user_date ON bookings(user_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date);

-- User locks table
-- Concurrency control for booking jobs
CREATE TABLE IF NOT EXISTS user_locks (
    user_id TEXT PRIMARY KEY,
    locked_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,  -- job_id
    expires_at TEXT NOT NULL  -- locked_at + 300 seconds
);

CREATE INDEX IF NOT EXISTS idx_locks_expires ON user_locks(expires_at);

-- No-slots notifications tracking table
-- Prevents duplicate "no slots" notifications for same request/date
CREATE TABLE IF NOT EXISTS no_slots_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    target_date TEXT NOT NULL,  -- YYYY-MM-DD
    sent_at TEXT DEFAULT (datetime('now')),
    UNIQUE(request_id, target_date)
);

CREATE INDEX IF NOT EXISTS idx_no_slots_sent_at ON no_slots_notifications(sent_at);
