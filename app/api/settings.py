from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.common import row_to_dict
from app.database import backup_database, db_session, utc_now_iso
from app.schemas import SettingUpdate
from app.services.audit import audit


router = APIRouter()


@router.post("/api/backup")
def backup() -> dict[str, Any]:
    target = backup_database()
    return {"ok": True, "path": str(target)}


@router.get("/api/export/recommendations.csv")
def export_recommendations() -> StreamingResponse:
    with db_session() as con:
        rows = con.execute(
            """
            SELECT r.recommend_time, dp.name, r.mode, r.base_l_h, r.raw_l_h, r.limited_l_h, r.final_l_h, r.quality
            FROM recommendations r
            JOIN dosing_points dp ON dp.id=r.dosing_point_id
            ORDER BY r.recommend_time DESC
            LIMIT 2000
            """
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["时间", "投加点", "模式", "保守公式L/h", "原始建议L/h", "限幅后L/h", "最终建议L/h", "质量"])
    for row in rows:
        writer.writerow(list(row))
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=ai_pac_recommendations.csv"},
    )


@router.get("/api/settings")
def settings() -> list[dict[str, Any]]:
    with db_session() as con:
        rows = con.execute("SELECT * FROM app_settings ORDER BY key").fetchall()
    return [row_to_dict(row) for row in rows]


@router.put("/api/settings/{key}")
def update_setting(key: str, payload: SettingUpdate) -> dict[str, Any]:
    with db_session() as con:
        con.execute(
            """
            INSERT INTO app_settings(key,value,updated_at)
            VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, payload.value, utc_now_iso()),
        )
        audit(con, "local", "update", "setting", key, payload.model_dump())
    return {"ok": True}
