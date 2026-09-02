from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.database import get_db, now_iso
from app.security import get_current_user

router = APIRouter(prefix="/api/events", tags=["events"])


class NewEvent(BaseModel):
    drink_type_id: int


@router.post("")
def trigger_in_app(body: NewEvent, request: Request):
    user = get_current_user(request)
    with get_db() as conn:
        drink = conn.execute(
            "SELECT id, name FROM drink_types WHERE id=? AND active=1", (body.drink_type_id,)
        ).fetchone()
        if not drink:
            raise HTTPException(status_code=404, detail="Drink type not found or inactive")
        conn.execute(
            "INSERT INTO events (user_id, drink_type_id, source, timestamp) VALUES (?, ?, 'in-app', ?)",
            (user.id, body.drink_type_id, now_iso()),
        )
        today_count = conn.execute(
            "SELECT COUNT(*) c FROM events WHERE user_id=? AND drink_type_id=? "
            "AND date(timestamp) = date('now')",
            (user.id, body.drink_type_id),
        ).fetchone()["c"]
    return {"status": "ok", "drink": drink["name"], "count_today": today_count}


@router.get("/today-counts")
def today_counts(request: Request):
    """Accurate per-drink counts for today, for the current user — used to
    label the in-app trigger buttons. Independent of the dashboard's
    global/personal scope toggle and not limited like /recent is."""
    user = get_current_user(request)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT dt.id AS drink_type_id, COUNT(*) c
            FROM events e JOIN drink_types dt ON dt.id = e.drink_type_id
            WHERE e.user_id = ? AND date(e.timestamp) = date('now')
            GROUP BY dt.id
            """,
            (user.id,),
        ).fetchall()
    return {r["drink_type_id"]: r["c"] for r in rows}


@router.get("/recent")
def recent(request: Request, limit: int = 10, user_id: int | None = None):
    current = get_current_user(request)
    target_id = user_id if (user_id and current.role == "admin") else current.id
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.timestamp, e.source, dt.name AS drink_name, dt.color
            FROM events e JOIN drink_types dt ON dt.id = e.drink_type_id
            WHERE e.user_id = ?
            ORDER BY e.timestamp DESC LIMIT ?
            """,
            (target_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/last")
def undo_last(request: Request, user_id: int | None = None):
    """Undo the most recent event — available at any time, not just within
    a short window, per project decision."""
    current = get_current_user(request)
    target_id = user_id if (user_id and current.role == "admin") else current.id
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, drink_type_id FROM events WHERE user_id=? ORDER BY timestamp DESC LIMIT 1",
            (target_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No events to undo")
        conn.execute("DELETE FROM events WHERE id=?", (row["id"],))
    return {"ok": True, "removedEventId": row["id"]}
