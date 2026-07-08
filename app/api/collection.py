from __future__ import annotations

import sqlite3  # P0-4 修复：_forward_fill_grid 类型注解使用 sqlite3.Connection 但缺失导入
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.common import row_to_dict
from app.database import db_session, utc_now, utc_now_iso
from app.schemas import CollectionTagCreate, CollectionTagUpdate, HistoryPurgeIn
from app.services.audit import audit
from app.services.collection_runtime import (
    collection_due_rows,
    collection_tag_row,
    poll_collection_rows,
    validate_collection_payload,
)
from app.services.plc_devices import plc_device_rows


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
        devices = plc_device_rows(con)
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


def _insert_collection_tag(con, payload: CollectionTagCreate, dosing_point_id: int | None) -> int:
    """P2-4 修复：create_public_collection_tag 与 create_collection_tag 的插入逻辑 90%+ 重复，抽取公共函数。"""
    now = utc_now_iso()
    tag_type = payload.tag_type.strip().upper()
    if not all((char.isascii() and (char.isalnum() or char in "_-")) for char in tag_type):
        raise HTTPException(422, "采集类型只能包含字母、数字、下划线和中划线")
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
            dosing_point_id,
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
    audit(con, "local", "create", "collection_tag", str(tag_id), payload.model_dump() | {"dosing_point_id": dosing_point_id})
    return tag_id


@router.post("/api/collection/public/tags")
def create_public_collection_tag(payload: CollectionTagCreate) -> dict[str, Any]:
    validate_collection_payload(payload)
    with db_session() as con:
        tag_id = _insert_collection_tag(con, payload, None)
        created = collection_tag_row(con, tag_id)
    return {"ok": True, "id": tag_id, "tag": created}


@router.post("/api/collection/points/{point_id}/tags")
def create_collection_tag(point_id: int, payload: CollectionTagCreate) -> dict[str, Any]:
    validate_collection_payload(payload)
    with db_session() as con:
        point = con.execute("SELECT * FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not point:
            raise HTTPException(404, "投加点不存在")
        tag_id = _insert_collection_tag(con, payload, point_id)
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


def _build_time_grid(start: datetime, end: datetime, interval_minutes: int) -> list[datetime]:
    grid: list[datetime] = []
    cur = start
    while cur <= end:
        grid.append(cur)
        cur += timedelta(minutes=interval_minutes)
    return grid


def _forward_fill_grid(
    con: sqlite3.Connection,
    tag_id: int,
    grid: list[datetime],
    interval_minutes: int,
) -> list[dict[str, Any]]:
    if not grid:
        return []
    end_iso = grid[-1].isoformat()
    lookback = timedelta(minutes=interval_minutes)
    rows = con.execute(
        """
        SELECT value, sample_time
        FROM sensor_samples
        WHERE tag_id=? AND sample_time<=?
        ORDER BY sample_time ASC
        """,
        (tag_id, end_iso),
    ).fetchall()
    row_idx = 0
    points: list[dict[str, Any]] = []
    for t in grid:
        t_iso = t.isoformat()
        window_start = (t - lookback).isoformat()
        best_value = None
        while row_idx < len(rows) and rows[row_idx]["sample_time"] <= t_iso:
            if rows[row_idx]["sample_time"] >= window_start:
                best_value = rows[row_idx]["value"]
            row_idx += 1
        points.append({"sample_time": t_iso, "value": best_value})
    return points


@router.get("/api/history-data")
def history_data(
    tag_ids: str = Query(""),
    start_time: str | None = None,
    end_time: str | None = None,
    limit_per_tag: int = Query(5000, ge=1, le=20000),
    interval_minutes: int | None = Query(None, ge=1, le=1440),
) -> dict[str, Any]:
    ids = sorted({int(item) for item in tag_ids.split(",") if item.strip().isdigit()})
    if not ids:
        return {"series": []}
    start = start_time or (utc_now() - timedelta(days=1)).isoformat()  # P1-1: 统一 UTC
    end = end_time or utc_now().isoformat()
    grid: list[datetime] | None = None
    if interval_minutes is not None:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            grid = _build_time_grid(start_dt, end_dt, interval_minutes)
        except (ValueError, TypeError):
            grid = None
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
            if grid is not None:
                points = _forward_fill_grid(con, tag_id, grid, interval_minutes)
            else:
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
                points = [row_to_dict(row) for row in rows]
            series.append(
                {
                    "tag": row_to_dict(tag),
                    "points": points,
                }
            )
    return {"start_time": start, "end_time": end, "interval_minutes": interval_minutes, "series": series}


@router.post("/api/history-data/purge")
def purge_history_data(payload: HistoryPurgeIn) -> dict[str, Any]:
    cutoff = (utc_now() - timedelta(days=payload.days)).replace(microsecond=0).isoformat()  # P1-1: 统一 UTC
    with db_session() as con:
        sensor_count = int(con.execute("SELECT COUNT(*) FROM sensor_samples WHERE sample_time<?", (cutoff,)).fetchone()[0])
        con.execute("DELETE FROM sensor_samples WHERE sample_time<?", (cutoff,))
        audit(
            con,
            "local",
            "purge",
            "history_data",
            cutoff,
            {"days": payload.days, "cutoff": cutoff, "sensor_samples_deleted": sensor_count},
        )
    return {
        "ok": True,
        "days": payload.days,
        "cutoff": cutoff,
        "sensor_samples_deleted": sensor_count,
    }
