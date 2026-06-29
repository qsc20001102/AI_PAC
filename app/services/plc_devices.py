from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.api.common import row_to_dict
from app.database import utc_now_iso
from app.schemas import PlcDeviceCreate, PlcDeviceUpdate


_plc_clients: dict[int, Any] = {}


def plc_client_store() -> dict[int, Any]:
    return _plc_clients


def plc_device_rows(con) -> list[dict[str, Any]]:
    clients = plc_client_store()
    rows = con.execute("SELECT * FROM plc_devices ORDER BY id").fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = row_to_dict(row)
        item["runtime_connected"] = int(row["id"]) in clients
        result.append(item)
    return result


def get_plc_device_or_404(con, device_id: int):
    device = con.execute("SELECT * FROM plc_devices WHERE id=?", (device_id,)).fetchone()
    if not device:
        raise HTTPException(404, "PLC 设备不存在")
    return device


def validate_plc_device_payload(payload: PlcDeviceCreate | PlcDeviceUpdate) -> None:
    if payload.protocol != "s7_1500":
        raise HTTPException(422, "当前只支持 S7-1500 协议")
    if not payload.name.strip():
        raise HTTPException(422, "PLC 设备名称不能为空")
    if not payload.ip_address.strip():
        raise HTTPException(422, "PLC IP 地址不能为空")


def log_plc_device_event(
    con,
    device_id: int,
    event_type: str,
    status: str,
    message: str,
    pdu_length: int | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO plc_device_events(device_id,event_type,status,message,pdu_length,created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (device_id, event_type, status, message, pdu_length, utc_now_iso()),
    )
