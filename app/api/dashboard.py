from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.common import row_to_dict
from app.api.models import model_project_summary_rows
from app.database import db_session, utc_now_iso
from app.services.collection_data import data_quality_rows, refresh_local_simulated_samples
from app.services.plc_devices import plc_device_rows
from app.services.recommendation import recalculate_all


router = APIRouter()


@router.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    with db_session() as con:
        demo_refresh = con.execute("SELECT value FROM app_settings WHERE key='demo_live_refresh'").fetchone()
        if demo_refresh and demo_refresh["value"].lower() == "true":
            refresh_local_simulated_samples(con)
        recs = recalculate_all(con)
        alarms = [
            row_to_dict(row)
            for row in con.execute(
                """
                SELECT a.*, dp.name AS dosing_point_name
                FROM alarms a
                LEFT JOIN dosing_points dp ON dp.id=a.dosing_point_id
                WHERE a.status='active'
                ORDER BY CASE a.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, a.event_time DESC
                LIMIT 8
                """
            ).fetchall()
        ]
        plc = plc_device_rows(con)
        training_models = model_project_summary_rows(con)
        quality = data_quality_rows(con)
    return {
        "recommendations": recs,
        "alarms": alarms,
        "plc": plc,
        "training_models": training_models,
        "data_quality": quality,
        "server_time": utc_now_iso(),
    }
