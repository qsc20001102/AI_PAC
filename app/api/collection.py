from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.common import row_to_dict
from app.database import db_session
from app.database import utc_now_iso
from app.schemas import CollectionTagCreate, CollectionTagUpdate, HistoryPurgeIn
from app.services.audit import audit
from app.services.collection_runtime import (
    collection_due_rows,
    collection_tag_row,
    poll_collection_rows,
    validate_collection_payload,
)


router = APIRouter()


@router.get("/api/samples/latest")
def latest_samples(dosing_point_id: int | None = None) -> list[dict[str, Any]]:
    where = "WHERE st.enabled=1"
    params: list[Any] = []
    if dosing_point_id:
        where += " AND st.dosing_point_id=?"
        params.append(dosing_point_id)
    with db_session() as con:
        rows = con.execute(
            f"""
            SELECT st.*, dp.name AS dosing_point_name,
                ss.value, ss.sample_time, ss.receive_time, ss.quality, ss.source AS sample_source
            FROM sensor_tags st
            JOIN dosing_points dp ON dp.id=st.dosing_point_id
            LEFT JOIN sensor_samples ss ON ss.id = (
                SELECT id FROM sensor_samples
                WHERE tag_id=st.id
                ORDER BY sample_time DESC
                LIMIT 1
            )
            {where}
            ORDER BY dp.display_order, st.id
            """,
            params,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@router.get("/api/collection")
def collection_config(dosing_point_id: int | None = None, scope: str | None = None) -> dict[str, Any]:
    with db_session() as con:
        points = [row_to_dict(row) for row in con.execute("SELECT * FROM dosing_points ORDER BY display_order").fetchall()]
        devices = [row_to_dict(row) for row in con.execute("SELECT * FROM plc_devices ORDER BY id").fetchall()]
        where = ""
        params: list[Any] = []
        if scope == "public":
            where = "WHERE st.dosing_point_id IS NULL"
        elif dosing_point_id is not None:
            where = "WHERE st.dosing_point_id=?"
            params.append(dosing_point_id)
        tags = [
            row_to_dict(row)
            for row in con.execute(
                f"""
                SELECT st.*, dp.name AS dosing_point_name, d.name AS plc_device_name,
                    ss.value, ss.sample_time, ss.quality AS sample_quality, ss.source AS sample_source
                FROM sensor_tags st
                LEFT JOIN dosing_points dp ON dp.id=st.dosing_point_id
                LEFT JOIN plc_devices d ON d.id=st.plc_device_id
                LEFT JOIN sensor_samples ss ON ss.id = (
                    SELECT id FROM sensor_samples
                    WHERE tag_id=st.id
                    ORDER BY sample_time DESC
                    LIMIT 1
                )
                {where}
                ORDER BY CASE WHEN st.dosing_point_id IS NULL THEN 0 ELSE 1 END, dp.display_order, st.id
                """,
                params,
            ).fetchall()
        ]
    return {
        "points": points,
        "devices": devices,
        "tags": tags,
        "data_types": [
            {"value": "REAL", "label": "REAL", "length": "4 字节"},
            {"value": "BOOL", "label": "BOOL", "length": "1 位"},
            {"value": "INT", "label": "INT", "length": "2 字节"},
        ],
    }


@router.post("/api/collection/public/tags")
def create_public_collection_tag(payload: CollectionTagCreate) -> dict[str, Any]:
    validate_collection_payload(payload)
    now = utc_now_iso()
    tag_type = payload.tag_type.strip().upper()
    if not all((char.isascii() and (char.isalnum() or char in "_-")) for char in tag_type):
        raise HTTPException(422, "采集类型只能包含字母、数字、下划线和中划线")
    with db_session() as con:
        existing = con.execute("SELECT id FROM sensor_tags WHERE tag_code=?", (payload.tag_code.strip(),)).fetchone()
        if existing:
            raise HTTPException(409, "采集点名称已存在，必须全系统唯一")
        if payload.plc_device_id is not None:
            device = con.execute("SELECT id FROM plc_devices WHERE id=?", (payload.plc_device_id,)).fetchone()
            if not device:
                raise HTTPException(422, "数据源 PLC 设备不存在")
        cur = con.execute(
            """
            INSERT INTO sensor_tags(
                dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,
                min_value,max_value,source,enabled,data_type,plc_device_id,data_address,
                poll_interval_seconds,history_enabled,history_interval_minutes,last_quality,last_read_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                None,
                payload.tag_code.strip(),
                tag_type,
                payload.tag_code.strip(),
                payload.unit.strip(),
                max(payload.poll_interval_seconds * 2, 1),
                max(payload.poll_interval_seconds * 12, 15),
                None,
                None,
                "s7comm",
                int(payload.enabled),
                payload.data_type.upper(),
                payload.plc_device_id,
                payload.data_address.strip().upper(),
                payload.poll_interval_seconds,
                int(payload.history_enabled),
                payload.history_interval_minutes,
                "unknown",
                now,
            ),
        )
        tag_id = int(cur.lastrowid)
        audit(con, "local", "create", "collection_tag", str(tag_id), payload.model_dump() | {"dosing_point_id": None})
        created = collection_tag_row(con, tag_id)
    return {"ok": True, "id": tag_id, "tag": created}


@router.post("/api/collection/points/{point_id}/tags")
def create_collection_tag(point_id: int, payload: CollectionTagCreate) -> dict[str, Any]:
    validate_collection_payload(payload)
    now = utc_now_iso()
    tag_type = payload.tag_type.strip().upper()
    if not all((char.isascii() and (char.isalnum() or char in "_-")) for char in tag_type):
        raise HTTPException(422, "采集类型只能包含字母、数字、下划线和中划线")
    with db_session() as con:
        point = con.execute("SELECT * FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not point:
            raise HTTPException(404, "投加点不存在")
        existing = con.execute("SELECT id FROM sensor_tags WHERE tag_code=?", (payload.tag_code.strip(),)).fetchone()
        if existing:
            raise HTTPException(409, "采集点名称已存在，必须全系统唯一")
        if payload.plc_device_id is not None:
            device = con.execute("SELECT id FROM plc_devices WHERE id=?", (payload.plc_device_id,)).fetchone()
            if not device:
                raise HTTPException(422, "数据源 PLC 设备不存在")
        cur = con.execute(
            """
            INSERT INTO sensor_tags(
                dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,
                min_value,max_value,source,enabled,data_type,plc_device_id,data_address,
                poll_interval_seconds,history_enabled,history_interval_minutes,last_quality,last_read_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                point_id,
                payload.tag_code.strip(),
                tag_type,
                payload.tag_code.strip(),
                payload.unit.strip(),
                max(payload.poll_interval_seconds * 2, 1),
                max(payload.poll_interval_seconds * 12, 15),
                None,
                None,
                "s7comm",
                int(payload.enabled),
                payload.data_type.upper(),
                payload.plc_device_id,
                payload.data_address.strip().upper(),
                payload.poll_interval_seconds,
                int(payload.history_enabled),
                payload.history_interval_minutes,
                "unknown",
                now,
            ),
        )
        tag_id = int(cur.lastrowid)
        audit(con, "local", "create", "collection_tag", str(tag_id), payload.model_dump() | {"dosing_point_id": point_id})
        created = collection_tag_row(con, tag_id)
    return {"ok": True, "id": tag_id, "tag": created}


@router.put("/api/collection/tags/{tag_id}")
def update_collection_tag(tag_id: int, payload: CollectionTagUpdate) -> dict[str, Any]:
    validate_collection_payload(payload)
    with db_session() as con:
        tag = con.execute("SELECT * FROM sensor_tags WHERE id=?", (tag_id,)).fetchone()
        if not tag:
            raise HTTPException(404, "采集点不存在")
        existing = con.execute("SELECT id FROM sensor_tags WHERE tag_code=?", (payload.tag_code.strip(),)).fetchone()
        if existing and int(existing["id"]) != tag_id:
            raise HTTPException(409, "采集点名称已存在，必须全系统唯一")
        if payload.plc_device_id is not None:
            device = con.execute("SELECT id FROM plc_devices WHERE id=?", (payload.plc_device_id,)).fetchone()
            if not device:
                raise HTTPException(422, "数据源 PLC 设备不存在")
        con.execute(
            """
            UPDATE sensor_tags
            SET tag_code=?, name=?, data_type=?, plc_device_id=?, data_address=?, poll_interval_seconds=?,
                history_enabled=?, history_interval_minutes=?, enabled=?, source='s7comm',
                last_quality=CASE WHEN data_address<>? OR data_type<>? OR plc_device_id IS NOT ? THEN 'unknown' ELSE last_quality END,
                last_error=CASE WHEN data_address<>? OR data_type<>? OR plc_device_id IS NOT ? THEN NULL ELSE last_error END
            WHERE id=?
            """,
            (
                payload.tag_code.strip(),
                payload.tag_code.strip(),
                payload.data_type.upper(),
                payload.plc_device_id,
                payload.data_address.strip().upper(),
                payload.poll_interval_seconds,
                int(payload.history_enabled),
                payload.history_interval_minutes,
                int(payload.enabled),
                payload.data_address.strip().upper(),
                payload.data_type.upper(),
                payload.plc_device_id,
                payload.data_address.strip().upper(),
                payload.data_type.upper(),
                payload.plc_device_id,
                tag_id,
            ),
        )
        audit(con, "local", "update", "collection_tag", str(tag_id), payload.model_dump())
        updated = collection_tag_row(con, tag_id)
    return {"ok": True, "tag": updated}


@router.delete("/api/collection/tags/{tag_id}")
def delete_collection_tag(tag_id: int) -> dict[str, Any]:
    with db_session() as con:
        tag = con.execute("SELECT * FROM sensor_tags WHERE id=?", (tag_id,)).fetchone()
        if not tag:
            raise HTTPException(404, "采集点不存在")
        con.execute("DELETE FROM manual_samples WHERE tag_id=?", (tag_id,))
        con.execute("DELETE FROM sensor_samples WHERE tag_id=?", (tag_id,))
        con.execute("DELETE FROM sensor_tags WHERE id=?", (tag_id,))
        audit(con, "local", "delete", "collection_tag", str(tag_id), row_to_dict(tag))
    return {"ok": True, "deleted_id": tag_id}


@router.post("/api/collection/poll")
def poll_collection(dosing_point_id: int | None = None, scope: str | None = None) -> dict[str, Any]:
    with db_session() as con:
        rows = collection_due_rows(con, dosing_point_id=dosing_point_id, public_only=scope == "public", force=True)
        result = poll_collection_rows(con, rows, force_history=True)
    return {"ok": True, **result}


@router.get("/api/samples/history")
def sample_history(tag_code: str, limit: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
    with db_session() as con:
        tag = con.execute("SELECT * FROM sensor_tags WHERE tag_code=?", (tag_code,)).fetchone()
        if not tag:
            raise HTTPException(404, "标签不存在")
        rows = con.execute(
            """
            SELECT value, unit, sample_time, receive_time, quality, source
            FROM sensor_samples
            WHERE tag_id=?
            ORDER BY sample_time DESC
            LIMIT ?
            """,
            (tag["id"], limit),
        ).fetchall()
    return {"tag": row_to_dict(tag), "samples": [row_to_dict(row) for row in rows]}


@router.get("/api/history-data")
def history_data(
    tag_ids: str = Query(""),
    start_time: str | None = None,
    end_time: str | None = None,
    limit_per_tag: int = Query(5000, ge=1, le=20000),
) -> dict[str, Any]:
    ids = sorted({int(item) for item in tag_ids.split(",") if item.strip().isdigit()})
    if not ids:
        return {"series": []}
    start = start_time or (datetime.now() - timedelta(days=1)).isoformat()
    end = end_time or datetime.now().isoformat()
    with db_session() as con:
        series = []
        for tag_id in ids:
            tag = con.execute(
                """
                SELECT st.*, dp.name AS dosing_point_name
                FROM sensor_tags st
                LEFT JOIN dosing_points dp ON dp.id=st.dosing_point_id
                WHERE st.id=?
                """,
                (tag_id,),
            ).fetchone()
            if not tag:
                continue
            rows = con.execute(
                """
                SELECT value, unit, sample_time, receive_time, quality, source
                FROM sensor_samples
                WHERE tag_id=? AND sample_time>=? AND sample_time<=?
                ORDER BY sample_time ASC
                LIMIT ?
                """,
                (tag_id, start, end, limit_per_tag),
            ).fetchall()
            series.append(
                {
                    "tag": row_to_dict(tag),
                    "points": [row_to_dict(row) for row in rows],
                }
            )
    return {"start_time": start, "end_time": end, "series": series}


@router.post("/api/history-data/purge")
def purge_history_data(payload: HistoryPurgeIn) -> dict[str, Any]:
    cutoff = (datetime.now() - timedelta(days=payload.days)).replace(microsecond=0).isoformat()
    with db_session() as con:
        sensor_count = int(con.execute("SELECT COUNT(*) FROM sensor_samples WHERE sample_time<?", (cutoff,)).fetchone()[0])
        manual_count = int(con.execute("SELECT COUNT(*) FROM manual_samples WHERE sample_time<?", (cutoff,)).fetchone()[0])
        con.execute("DELETE FROM sensor_samples WHERE sample_time<?", (cutoff,))
        con.execute("DELETE FROM manual_samples WHERE sample_time<?", (cutoff,))
        audit(
            con,
            "local",
            "purge",
            "history_data",
            cutoff,
            {"days": payload.days, "cutoff": cutoff, "sensor_samples_deleted": sensor_count, "manual_samples_deleted": manual_count},
        )
    return {
        "ok": True,
        "days": payload.days,
        "cutoff": cutoff,
        "sensor_samples_deleted": sensor_count,
        "manual_samples_deleted": manual_count,
    }
