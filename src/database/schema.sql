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
