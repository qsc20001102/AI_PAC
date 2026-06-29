from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query

from app.database import db_session
from app.services.recommendation import PROCESS_SOURCE_MAP


router = APIRouter()


@router.get("/api/trends")
def trends(
    dosing_point_id: int = Query(1, ge=1),
    hours: int = Query(6, ge=1, le=720),
) -> dict[str, Any]:
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    with db_session() as con:
        point = con.execute(
            "SELECT * FROM dosing_points WHERE id=?",
            (dosing_point_id,),
        ).fetchone()
        series: dict[str, dict[str, Any]] = {}
        tags = []
        if point and (bool(point["source_configured"]) or any(point[field] is not None for field, *_ in PROCESS_SOURCE_MAP)):
            q_points = effective_flow_series(con, point, since)
            if q_points is not None:
                series["Q"] = {"name": "参与计算流量", "unit": "m3/h", "points": q_points}
            for field, logical_type, logical_name, default_unit in PROCESS_SOURCE_MAP:
                if logical_type in {"ZONE_Q", "REFLUX_Q1", "REFLUX_Q2"}:
                    continue
                tag_id = point[field]
                if tag_id is None:
                    continue
                tag = con.execute("SELECT id, tag_code, name, unit FROM sensor_tags WHERE id=?", (tag_id,)).fetchone()
                if tag:
                    tags.append((tag, logical_type, logical_name, default_unit))
        else:
            legacy_tags = con.execute(
                "SELECT id, tag_type, tag_code, name, unit FROM sensor_tags WHERE dosing_point_id=?",
                (dosing_point_id,),
            ).fetchall()
            for tag in legacy_tags:
                if tag["tag_type"] in {"Q", "PO4_P", "TP_BEFORE", "TP_OUT", "PH", "PAC_ACTUAL"}:
                    tags.append((tag, tag["tag_type"], tag["tag_code"], tag["unit"]))
        for tag, logical_type, logical_name, default_unit in tags:
            rows = con.execute(
                """
                SELECT sample_time AS time, value
                FROM sensor_samples
                WHERE tag_id=? AND sample_time>=?
                ORDER BY sample_time
                """,
                (tag["id"], since),
            ).fetchall()
            series[logical_type] = {
                "name": logical_name,
                "tag_code": tag["tag_code"],
                "unit": tag["unit"] or default_unit,
                "points": [{"time": row["time"], "value": row["value"]} for row in rows],
            }
        rec_rows = con.execute(
            """
            SELECT recommend_time AS time, final_l_h, mode
            FROM recommendations
            WHERE dosing_point_id=? AND recommend_time>=? AND source='online'
            ORDER BY recommend_time
            """,
            (dosing_point_id, since),
        ).fetchall()
        series["PAC_SUGGEST"] = {
            "name": "PAC 建议",
            "unit": "L/h",
            "points": [{"time": row["time"], "value": row["final_l_h"], "mode": row["mode"]} for row in rec_rows],
        }
    return {"dosing_point_id": dosing_point_id, "hours": hours, "series": series}


def tag_series_rows(con, tag_id: int | None, since: str) -> list[dict[str, Any]]:
    if tag_id is None:
        return []
    rows = con.execute(
        """
        SELECT sample_time AS time, value
        FROM sensor_samples
        WHERE tag_id=? AND sample_time>=? AND quality='good'
        ORDER BY sample_time
        """,
        (tag_id, since),
    ).fetchall()
    return [{"time": row["time"], "value": float(row["value"])} for row in rows]


def effective_flow_series(con, point: Any, since: str) -> list[dict[str, Any]] | None:
    if point["zone_flow_tag_id"] is not None:
        base_rows = tag_series_rows(con, point["zone_flow_tag_id"], since)
        weight = 1.0
    elif point["in_flow_tag_id"] is not None:
        base_rows = tag_series_rows(con, point["in_flow_tag_id"], since)
        weight = float(point["in_flow_weight"] if point["in_flow_weight"] is not None else 1.0)
    else:
        return None
    if not base_rows:
        return []
    points = []
    for row in base_rows:
        points.append({"time": row["time"], "value": row["value"] * weight})
    return points
