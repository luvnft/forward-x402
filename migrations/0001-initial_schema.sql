-- Initial schema migration with user support and monitoring

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE,
    name TEXT,
    picture TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Email endpoints that users create
CREATE TABLE IF NOT EXISTS email_endpoints (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    label TEXT,
    short_url TEXT UNIQUE NOT NULL,
    base_price INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    hit_count INTEGER DEFAULT 0,
    payment_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);