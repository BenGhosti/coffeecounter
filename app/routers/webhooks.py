import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_db, now_iso
from app.security import get_current_user, CurrentUser

router = APIRouter(tags=["webhooks"])


def generate_token() -> str:
    return "cc_" + secrets.token_urlsafe(24)


class NewToken(BaseModel):
    user_id: int
    drink_type_id: int


@router.get("/api/webhook-tokens")
def list_tokens(request: Request, user_id: int | None = None):
    current = get_current_user(request)
    target_id = user_id if (user_id and current.role == "admin") else current.id
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT wt.id, wt.token, wt.active, wt.created_at, wt.last_triggered_at,
                   wt.user_id, dt.id AS drink_type_id, dt.name AS drink_name, dt.color
            FROM webhook_tokens wt
            JOIN drink_types dt ON dt.id = wt.drink_type_id
            WHERE wt.user_id = ?
            ORDER BY wt.created_at
            """,
            (target_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/webhook-tokens")
def create_token(body: NewToken, request: Request):
    current = get_current_user(request)
    if current.role != "admin" and current.id != body.user_id:
        raise HTTPException(status_code=403, detail="Not allowed")
    token = generate_token()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO webhook_tokens (user_id, drink_type_id, token, active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (body.user_id, body.drink_type_id, token, now_iso()),
        )
    return {"id": cur.lastrowid, "token": token, "url": f"{settings.BASE_URL}hook/{token}"}


@router.delete("/api/webhook-tokens/{token_id}")
def revoke_token(token_id: int, request: Request):
    current = get_current_user(request)
    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM webhook_tokens WHERE id=?", (token_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Token not found")
        if current.role != "admin" and current.id != row["user_id"]:
            raise HTTPException(status_code=403, detail="Not allowed")
        conn.execute("UPDATE webhook_tokens SET active=0 WHERE id=?", (token_id,))
    return {"ok": True}


@router.api_route("/hook/{token}", methods=["GET", "POST"])
def trigger_webhook(token: str):
    """The primary trigger method. GET is intentionally allowed (bookmarklets,
    iOS Shortcuts, ESP32 buttons, curl) since a trigger only ever adds +1."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT wt.id, wt.user_id, wt.drink_type_id, wt.active, wt.last_triggered_at, dt.name
            FROM webhook_tokens wt
            JOIN drink_types dt ON dt.id = wt.drink_type_id
            WHERE wt.token = ?
            """,
            (token,),
        ).fetchone()
        if not row or not row["active"]:
            raise HTTPException(status_code=404, detail="Unknown or revoked webhook")

        if settings.WEBHOOK_DEBOUNCE > 0 and row["last_triggered_at"]:
            last = datetime.fromisoformat(row["last_triggered_at"])
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < settings.WEBHOOK_DEBOUNCE:
                today_count = conn.execute(
                    "SELECT COUNT(*) c FROM events WHERE user_id=? AND drink_type_id=? "
                    "AND date(timestamp) = date('now')",
                    (row["user_id"], row["drink_type_id"]),
                ).fetchone()["c"]
                return {
                    "status": "debounced",
                    "message": f"Ignored — triggered again within {settings.WEBHOOK_DEBOUNCE}s",
                    "count_today": today_count,
                }

        ts = now_iso()
        conn.execute(
            "INSERT INTO events (user_id, drink_type_id, source, timestamp) VALUES (?, ?, 'webhook', ?)",
            (row["user_id"], row["drink_type_id"], ts),
        )
        conn.execute("UPDATE webhook_tokens SET last_triggered_at=? WHERE id=?", (ts, row["id"]))
        today_count = conn.execute(
            "SELECT COUNT(*) c FROM events WHERE user_id=? AND drink_type_id=? "
            "AND date(timestamp) = date('now')",
            (row["user_id"], row["drink_type_id"]),
        ).fetchone()["c"]

    return {"status": "ok", "drink": row["name"], "count_today": today_count}
