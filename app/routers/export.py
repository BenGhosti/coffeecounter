import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.security import get_current_user
from app.routers.stats import RANGE_CONFIG

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("")
def export_csv(request: Request, scope: str = "global", range: str = "month", user_id: int | None = None):
    current = get_current_user(request)
    if range not in RANGE_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid range")

    lookback, _ = RANGE_CONFIG[range]
    since = (datetime.now(timezone.utc) - lookback).isoformat() if lookback else None

    target_user = None
    if scope == "user":
        target_user = user_id if (user_id and current.role == "admin") else current.id

    query = (
        "SELECT e.timestamp, u.name AS user_name, dt.name AS drink_name, e.source "
        "FROM events e "
        "JOIN users u ON u.id = e.user_id "
        "JOIN drink_types dt ON dt.id = e.drink_type_id "
        "WHERE 1=1"
    )
    params = []
    if target_user:
        query += " AND e.user_id = ?"
        params.append(target_user)
    if since:
        query += " AND e.timestamp >= ?"
        params.append(since)
    query += " ORDER BY e.timestamp"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "user", "drink", "source"])
    for r in rows:
        writer.writerow([r["timestamp"], r["user_name"], r["drink_name"], r["source"]])
    buf.seek(0)

    filename = f"coffeecounter_{scope}_{range}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
