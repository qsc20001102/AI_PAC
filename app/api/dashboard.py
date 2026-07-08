from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

from fastapi import APIRouter

from app.api.common import row_to_dict
from app.api.models import model_project_summary_rows
from app.database import db_session, utc_now, utc_now_iso
from app.services.collection_data import data_quality_rows
from app.services.plc_devices import plc_device_rows
from app.services.recommendation import recalculate_all


router = APIRouter()

# P1-4 修复：原代码每次 GET /api/dashboard 都调用 recalculate_all，
# 该函数即便内部有按投加点的缓存也会执行多条 SQL 判断，造成不必要的开销。
# 此处增加进程内 TTL 缓存（60 秒），同一窗口内直接复用上一次的计算结果。
_DASHBOARD_RECS_TTL_SECONDS = 60
_dashboard_recs_cache: dict[str, Any] = {"recs": None, "computed_at": None}
_dashboard_recs_lock = threading.Lock()


def _get_cached_recommendations(con) -> list[dict[str, Any]]:
    """获取带 TTL 缓存的推荐结果。缓存失效时重新计算并写回。"""
    now = utc_now()
    with _dashboard_recs_lock:
        cached_at = _dashboard_recs_cache["computed_at"]
        if cached_at is not None and (now - cached_at) < timedelta(seconds=_DASHBOARD_RECS_TTL_SECONDS):
            return _dashboard_recs_cache["recs"]
    # 缓存未命中或已过期，重新计算（在锁外执行避免长时间持锁）
    recs = recalculate_all(con)
    with _dashboard_recs_lock:
        _dashboard_recs_cache["recs"] = recs
        _dashboard_recs_cache["computed_at"] = now
    return recs


@router.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    with db_session() as con:
        recs = _get_cached_recommendations(con)
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
