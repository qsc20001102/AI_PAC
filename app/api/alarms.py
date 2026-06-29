from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.common import row_to_dict
from app.database import db_session, utc_now_iso


router = APIRouter()


@router.get("/api/alarms")
def alarms(status: str = "active") -> list[dict[str, Any]]:
    with db_session() as con:
        rows = con.execute(
            """
            SELECT a.*, dp.name AS dosing_point_name
            FROM alarms a
            LEFT JOIN dosing_points dp ON dp.id=a.dosing_point_id
            WHERE (?='all' OR a.status=?)
            ORDER BY a.event_time DESC
            LIMIT 200
            """,
            (status, status),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@router.post("/api/alarms/{alarm_id}/ack")
def ack_alarm(alarm_id: int) -> dict[str, Any]:
    with db_session() as con:
        row = con.execute("SELECT id FROM alarms WHERE id=?", (alarm_id,)).fetchone()
        if not row:
            raise HTTPException(404, "报警不存在")
        con.execute(
            "UPDATE alarms SET status='acknowledged', acknowledged_at=?, acknowledged_by=? WHERE id=?",
            (utc_now_iso(), "local", alarm_id),
        )
    return {"ok": True}


@router.post("/api/alarms/ack-all")
def ack_all_alarms() -> dict[str, Any]:
    with db_session() as con:
        con.execute(
            "UPDATE alarms SET status='acknowledged', acknowledged_at=?, acknowledged_by=? WHERE status='active'",
            (utc_now_iso(), "local"),
        )
    return {"ok": True}
