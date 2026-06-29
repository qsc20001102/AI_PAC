from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.common import row_to_dict
from app.database import DB_PATH, db_session, table_count, utc_now_iso


router = APIRouter()

BACKEND_STATUS_TABLES = (
    "plants",
    "dosing_points",
    "sensor_tags",
    "sensor_samples",
    "manual_samples",
    "recommendations",
    "alarms",
    "model_versions",
    "simulation_runs",
    "data_sources",
    "collector_runs",
    "plc_devices",
    "plc_device_events",
    "audit_logs",
)


@router.get("/api/health")
def health() -> dict[str, Any]:
    with db_session() as con:
        journal = con.execute("PRAGMA journal_mode").fetchone()[0]
        points = con.execute("SELECT COUNT(*) FROM dosing_points").fetchone()[0]
    return {"ok": True, "journal_mode": journal, "dosing_points": points, "time": utc_now_iso()}


@router.get("/api/backend/status")
def backend_status() -> dict[str, Any]:
    with db_session() as con:
        counts = {name: table_count(con, name) for name in BACKEND_STATUS_TABLES}
        latest = con.execute(
            """
            SELECT st.tag_code, st.name, ss.value, ss.unit, ss.sample_time, ss.quality, ss.source
            FROM sensor_samples ss
            JOIN sensor_tags st ON st.id=ss.tag_id
            ORDER BY ss.sample_time DESC
            LIMIT 10
            """
        ).fetchall()
        sources = con.execute("SELECT * FROM data_sources ORDER BY id").fetchall()
        journal = con.execute("PRAGMA journal_mode").fetchone()[0]
    return {
        "database": {"path": str(DB_PATH), "journal_mode": journal, "exists": DB_PATH.exists()},
        "table_counts": counts,
        "data_sources": [row_to_dict(row) for row in sources],
        "latest_samples": [row_to_dict(row) for row in latest],
        "server_time": utc_now_iso(),
    }
