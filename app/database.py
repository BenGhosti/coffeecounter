import sqlite3
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
    pin_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passkeys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    credential_id TEXT NOT NULL UNIQUE,
    public_key TEXT NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    transports TEXT,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS drink_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drink_type_id INTEGER NOT NULL REFERENCES drink_types(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_triggered_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drink_type_id INTEGER NOT NULL REFERENCES drink_types(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'webhook',
    timestamp TEXT NOT NULL
);

-- Per-day pre-aggregation so coarse ranges (week/month/year/2y/all) never
-- rescan the full events table. Kept in sync by triggers on INSERT/DELETE;
-- "day" is the UTC date of the event (same day the charts already bucket by).
CREATE TABLE IF NOT EXISTS daily_stats (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drink_type_id INTEGER NOT NULL REFERENCES drink_types(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, drink_type_id, day)
);

CREATE TRIGGER IF NOT EXISTS trg_daily_stats_insert
AFTER INSERT ON events
BEGIN
    INSERT INTO daily_stats (user_id, drink_type_id, day, count)
    VALUES (NEW.user_id, NEW.drink_type_id, date(NEW.timestamp), 1)
    ON CONFLICT(user_id, drink_type_id, day) DO UPDATE SET count = count + 1;
END;

CREATE TRIGGER IF NOT EXISTS trg_daily_stats_delete
AFTER DELETE ON events
BEGIN
    UPDATE daily_stats SET count = count - 1
    WHERE user_id = OLD.user_id AND drink_type_id = OLD.drink_type_id
      AND day = date(OLD.timestamp);
    DELETE FROM daily_stats
    WHERE user_id = OLD.user_id AND drink_type_id = OLD.drink_type_id
      AND day = date(OLD.timestamp) AND count <= 0;
END;

CREATE TABLE IF NOT EXISTS webauthn_challenges (
    id TEXT PRIMARY KEY,
    user_id INTEGER,
    challenge TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('registration', 'authentication')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_user_ts ON events(user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_tokens_token ON webhook_tokens(token);
"""

# Curated, clearly distinguishable colors that stay legible on the dark
# coffee theme (and can be overridden per drink by the admin anytime).
DEFAULT_DRINKS = [
    ("Coffee", "#D89A52"),
    ("Cocoa", "#A9744F"),
    ("Snacks", "#86A361"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        existing = conn.execute("SELECT COUNT(*) c FROM drink_types").fetchone()["c"]
        if existing == 0:
            for name, color in DEFAULT_DRINKS:
                conn.execute(
                    "INSERT INTO drink_types (name, color, is_default, active, created_at) "
                    "VALUES (?, ?, 1, 1, ?)",
                    (name, color, now_iso()),
                )
        # Persist a generated session secret so it survives restarts without
        # requiring the user to set one manually in .env.
        row = conn.execute("SELECT value FROM kv_store WHERE key='session_secret'").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO kv_store (key, value) VALUES ('session_secret', ?)",
                (secrets.token_urlsafe(48),),
            )
        # One-time backfill for databases created before daily_stats existed.
        # The triggers keep it in sync from here on; on a fresh DB this is a
        # no-op because both tables start empty.
        ds_count = conn.execute("SELECT COUNT(*) c FROM daily_stats").fetchone()["c"]
        if ds_count == 0:
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_stats (user_id, drink_type_id, day, count)
                SELECT user_id, drink_type_id, date(timestamp), COUNT(*)
                FROM events GROUP BY user_id, drink_type_id, date(timestamp)
                """
            )


def get_session_secret() -> str:
    from app.config import settings as s
    if s.SESSION_SECRET:
        return s.SESSION_SECRET
    with get_db() as conn:
        row = conn.execute("SELECT value FROM kv_store WHERE key='session_secret'").fetchone()
        return row["value"]


def has_any_user() -> bool:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] > 0
