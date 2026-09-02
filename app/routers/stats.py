from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException

from app.database import get_db
from app.security import get_current_user

router = APIRouter(prefix="/api/stats", tags=["stats"])

# range -> (lookback timedelta or None for "all", sqlite strftime bucket format)
RANGE_CONFIG = {
    "day": (timedelta(days=1), "%Y-%m-%dT%H:00"),
    "week": (timedelta(days=7), "%Y-%m-%d"),
    "month": (timedelta(days=31), "%Y-%m-%d"),
    "year": (timedelta(days=366), "%Y-%m"),
    "2year": (timedelta(days=731), "%Y-%m"),
    "all": (None, "%Y-%m"),
}


@router.get("")
def get_stats(request: Request, scope: str = "global", range: str = "month", user_id: int | None = None):
    current = get_current_user(request)
    if range not in RANGE_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid range")
    if scope not in ("global", "user"):
        raise HTTPException(status_code=400, detail="Invalid scope")

    lookback, bucket_fmt = RANGE_CONFIG[range]
    since = None
    if lookback:
        since = (datetime.now(timezone.utc) - lookback).isoformat()

    target_user = None
    if scope == "user":
        target_user = user_id if (user_id and current.role == "admin") else current.id

    with get_db() as conn:
        drinks = conn.execute(
            "SELECT id, name, color FROM drink_types WHERE active=1 ORDER BY created_at"
        ).fetchall()

        series = {}
        for d in drinks:
            params = [bucket_fmt, d["id"]]
            query = (
                "SELECT strftime(?, timestamp) AS bucket, COUNT(*) AS c "
                "FROM events WHERE drink_type_id = ?"
            )
            if target_user:
                query += " AND user_id = ?"
                params.append(target_user)
            if since:
                query += " AND timestamp >= ?"
                params.append(since)
            query += " GROUP BY bucket ORDER BY bucket"
            rows = conn.execute(query, params).fetchall()
            series[d["name"]] = {
                "color": d["color"],
                "points": [{"bucket": r["bucket"], "count": r["c"]} for r in rows],
            }

        pie_params = []
        pie_query = (
            "SELECT dt.name, dt.color, COUNT(*) c FROM events e "
            "JOIN drink_types dt ON dt.id = e.drink_type_id WHERE dt.active = 1"
        )
        if target_user:
            pie_query += " AND e.user_id = ?"
            pie_params.append(target_user)
        if since:
            pie_query += " AND e.timestamp >= ?"
            pie_params.append(since)
        pie_query += " GROUP BY dt.id"
        pie_rows = conn.execute(pie_query, pie_params).fetchall()

        total_params = list(pie_params)
        total_query = "SELECT COUNT(*) c FROM events e WHERE 1=1"
        if target_user:
            total_query += " AND e.user_id = ?"
        if since:
            total_query += " AND e.timestamp >= ?"
        total = conn.execute(total_query, total_params).fetchone()["c"]

    return {
        "series": series,
        "pie": [{"name": r["name"], "color": r["color"], "count": r["c"]} for r in pie_rows],
        "total": total,
    }
