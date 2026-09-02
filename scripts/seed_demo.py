"""
Seeds a CoffeeCounter database with demo data so the UI can be explored
without wiring up real webhooks first:

- A demo admin (PIN 1234) plus two demo users, so the admin panel and the
  "everyone" vs "just me" dashboard views both have something to show.
- The default drink types, plus one extra ("Tea") to make the admin
  drink-type screen non-trivial too.
- ~2.5 years of randomly-but-plausibly spread events per user/drink, so
  every range switch (Day/Week/Month/Year/2 Years/All) actually has data.

Safe to re-run: by default it does nothing if users already exist. Pass
--force to wipe the existing users/events/tokens first and reseed.
"""
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import get_db, init_db, now_iso  # noqa: E402
from app.security import hash_pin  # noqa: E402


def _pin_for(digit: str) -> str:
    """Build a PIN of exactly settings.PIN_LENGTH by repeating a digit
    pattern, so demo PINs always match the configured login screen —
    whatever COFFEECOUNTER_PIN_LENGTH is set to (default 4)."""
    return (digit * settings.PIN_LENGTH)[: settings.PIN_LENGTH]


DEMO_ADMIN_PIN = _pin_for("1")
DEMO_USER_PINS = {"Mira": _pin_for("2"), "Jonas": _pin_for("3")}

EXTRA_DRINKS = [("Tea", "#C96F4A")]

# Roughly how many trigger events per user per active weekday, per drink —
# gives a believable "someone actually uses this" shape rather than
# uniform noise.
DRINK_WEIGHTS = {"Coffee": 2.2, "Cocoa": 0.4, "Snacks": 0.8, "Tea": 0.6}


def wipe(conn):
    for table in ("events", "webhook_tokens", "passkeys", "users"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM drink_types WHERE is_default=0")


def seed_events(conn, user_id: int, drink_type_id: int, drink_name: str, days_back: int):
    base_weight = DRINK_WEIGHTS.get(drink_name, 0.5)
    now = datetime.now(timezone.utc)
    rows = []
    for day_offset in range(days_back, -1, -1):
        day = now - timedelta(days=day_offset)
        if day.weekday() >= 5 and random.random() < 0.6:
            continue  # lighter on weekends, like a real office habit
        p = base_weight  # reset each day — each extra cup that day is less likely than the last
        n_today = 0
        while random.random() < p and n_today < 6:
            hour = random.choices(
                population=[8, 9, 10, 11, 13, 14, 15, 16],
                weights=[3, 4, 3, 2, 2, 3, 3, 2],
            )[0]
            ts = day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))
            rows.append((user_id, drink_type_id, "webhook" if random.random() < 0.7 else "in-app", ts.isoformat()))
            p -= 1
            n_today += 1
    conn.executemany(
        "INSERT INTO events (user_id, drink_type_id, source, timestamp) VALUES (?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="wipe existing users/events and reseed")
    parser.add_argument("--days-back", type=int, default=900, help="how far back to spread events (default ~2.5 years)")
    args = parser.parse_args()

    init_db()

    with get_db() as conn:
        existing = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        if existing > 0 and not args.force:
            print(f"Database already has {existing} user(s) — skipping seed.")
            print("Run with --force to wipe and reseed (deletes existing users/events/tokens).")
            return
        if existing > 0:
            print("Wiping existing users/events/tokens (--force) ...")
            wipe(conn)

        print("Creating demo users ...")
        conn.execute(
            "INSERT INTO users (name, role, pin_hash, created_at) VALUES (?, 'admin', ?, ?)",
            ("Demo Admin", hash_pin(DEMO_ADMIN_PIN), now_iso()),
        )
        admin_id = conn.execute("SELECT id FROM users WHERE name='Demo Admin'").fetchone()["id"]

        user_ids = {}
        for name, pin in DEMO_USER_PINS.items():
            conn.execute(
                "INSERT INTO users (name, role, pin_hash, created_at) VALUES (?, 'user', ?, ?)",
                (name, hash_pin(pin), now_iso()),
            )
            user_ids[name] = conn.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()["id"]
        all_user_ids = {"Demo Admin": admin_id, **user_ids}

        print("Adding extra drink type(s) ...")
        for name, color in EXTRA_DRINKS:
            exists = conn.execute("SELECT id FROM drink_types WHERE name=?", (name,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO drink_types (name, color, is_default, active, created_at) "
                    "VALUES (?, ?, 0, 1, ?)",
                    (name, color, now_iso()),
                )
        drinks = conn.execute("SELECT id, name FROM drink_types WHERE active=1").fetchall()

        print(f"Generating ~{args.days_back} days of events per user/drink ...")
        total = 0
        for user_name, user_id in all_user_ids.items():
            # Webhook tokens too, so the dashboard's "your webhook links" list
            # and the Test button have something real to hit right away.
            for d in drinks:
                conn.execute(
                    "INSERT INTO webhook_tokens (user_id, drink_type_id, token, active, created_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (user_id, d["id"], f"cc_demo_{user_id}_{d['id']}_{random.randint(1000,9999)}", now_iso()),
                )
                total += seed_events(conn, user_id, d["id"], d["name"], args.days_back)

    print(f"Done — {total} events across {len(all_user_ids)} users.")
    print()
    print("=" * 46)
    print(" Demo logins (PIN):")
    print(f"   Admin       -> {DEMO_ADMIN_PIN}   (Demo Admin)")
    for name, pin in DEMO_USER_PINS.items():
        print(f"   User        -> {pin}   ({name})")
    print("=" * 46)


if __name__ == "__main__":
    main()
