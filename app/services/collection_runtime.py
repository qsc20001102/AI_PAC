from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.api.common import row_to_dict
from app.database import db_session, utc_now_iso
from app.schemas import CollectionTagUpdate
from app.services.plc import parse_s7_address, read_s7_value
from app.services.plc_devices import plc_client_store
from app.services.recommendation import calculate_for_point


def validate_collection_payload(payload: CollectionTagUpdate) -> None:
    payload.data_type = payload.data_type.upper()
    if payload.data_type not in {"REAL", "BOOL", "INT"}:
        raise HTTPException(422, "数据类型只支持 REAL、BOOL、INT")
    address = payload.data_address.strip().upper()
    if address:
        try:
            parse_s7_address(address, payload.data_type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if not all((char.isascii() and (char.isalnum() or char in "_-")) for char in payload.tag_code.strip()):
        raise HTTPException(422, "采集点名称只能包含字母、数字、下划线和中划线")


def collection_tag_row(con, tag_id: int) -> dict[str, Any]:
    row = con.execute(
        """
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
        WHERE st.id=?
        """,
        (tag_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "采集点不存在")
    return row_to_dict(row)


async def collection_loop() -> None:
    while True:
        await asyncio.sleep(1)
        try:
            with db_session() as con:
                rows = collection_due_rows(con)
                if rows:
                    poll_collection_rows(con, rows)
        except asyncio.CancelledError:
            raise
        except Exception:
            continue


def collection_due_rows(
    con,
    dosing_point_id: int | None = None,
    public_only: bool = False,
    force: bool = False,
) -> list[Any]:
    where = "WHERE st.enabled=1"
    params: list[Any] = []
    if not force:
        where += " AND st.plc_device_id IS NOT NULL AND st.data_address<>''"
    if public_only:
        where += " AND st.dosing_point_id IS NULL"
    elif dosing_point_id is not None:
        where += " AND st.dosing_point_id=?"
        params.append(dosing_point_id)
    rows = con.execute(
        f"""
        SELECT st.*, d.name AS plc_device_name, d.status AS plc_status
        FROM sensor_tags st
        LEFT JOIN plc_devices d ON d.id=st.plc_device_id
        {where}
        ORDER BY st.id
        """,
        params,
    ).fetchall()
    if force:
        return rows
    now = datetime.now()
    due = []
    for row in rows:
        last_read = parse_iso_dt(row["last_read_at"])
        if last_read is None or (now - last_read).total_seconds() >= int(row["poll_interval_seconds"]):
            due.append(row)
    return due


def poll_collection_rows(con, rows: list[Any], force_history: bool = False) -> dict[str, Any]:
    read_ok = 0
    read_failed = 0
    history_written = 0
    affected_points: set[int] = set()
    now = datetime.now().replace(microsecond=0)
    now_iso = now.isoformat()
    clients = plc_client_store()
    for row in rows:
        tag_id = int(row["id"])
        point_id = int(row["dosing_point_id"]) if row["dosing_point_id"] is not None else None
        device_id = int(row["plc_device_id"]) if row["plc_device_id"] is not None else None
        address = (row["data_address"] or "").strip()
        data_type = (row["data_type"] or "REAL").upper()
        if not device_id or not address:
            update_collection_quality(con, tag_id, "unknown", None, now_iso, "未配置数据源或数据地址")
            read_failed += 1
            continue
        client = clients.get(device_id)
        if client is None:
            update_collection_quality(con, tag_id, "bad", None, now_iso, "PLC 设备未连接")
            read_failed += 1
            continue
        try:
            result = read_s7_value(client, address, data_type)
            con.execute(
                """
                UPDATE sensor_tags
                SET last_quality='good', last_value_text=?, last_read_at=?, last_error=NULL
                WHERE id=?
                """,
                (result.value_text, now_iso, tag_id),
            )
            read_ok += 1
            if should_write_history(row, now, force_history):
                con.execute(
                    """
                    INSERT OR REPLACE INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (tag_id, result.numeric_value, row["unit"], now_iso, now_iso, "good", "s7comm"),
                )
                con.execute("UPDATE sensor_tags SET last_history_at=? WHERE id=?", (now_iso, tag_id))
                history_written += 1
                if point_id is not None:
                    affected_points.add(point_id)
        except Exception as exc:
            update_collection_quality(con, tag_id, "bad", None, now_iso, str(exc))
            read_failed += 1
    for point_id in sorted(affected_points):
        calculate_for_point(con, point_id)
    return {
        "read_ok": read_ok,
        "read_failed": read_failed,
        "history_written": history_written,
        "affected_dosing_points": sorted(affected_points),
    }


def update_collection_quality(con, tag_id: int, quality: str, value_text: str | None, read_at: str, error: str | None) -> None:
    con.execute(
        """
        UPDATE sensor_tags
        SET last_quality=?, last_value_text=COALESCE(?, last_value_text), last_read_at=?, last_error=?
        WHERE id=?
        """,
        (quality, value_text, read_at, error, tag_id),
    )


def should_write_history(row: Any, now: datetime, force_history: bool) -> bool:
    if not bool(row["history_enabled"]):
        return False
    if force_history:
        return True
    last_history = parse_iso_dt(row["last_history_at"])
    if last_history is None:
        return True
    return (now - last_history).total_seconds() >= int(row["history_interval_minutes"]) * 60


def parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
