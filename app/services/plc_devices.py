from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.api.common import row_to_dict
from app.database import utc_now_iso
from app.schemas import PlcDeviceCreate, PlcDeviceUpdate
from app.services.plc import connect_s7_1500, disconnect_client


_plc_clients: dict[int, Any] = {}


def plc_client_store() -> dict[int, Any]:
    return _plc_clients


def plc_device_rows(con) -> list[dict[str, Any]]:
    clients = plc_client_store()
    rows = con.execute("SELECT * FROM plc_devices ORDER BY id").fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = row_to_dict(row)
        runtime_connected = int(row["id"]) in clients
        item["runtime_connected"] = runtime_connected
        if item["status"] == "connected" and not runtime_connected:
            item["status"] = "disconnected"
            item["last_error"] = item.get("last_error") or "运行时连接已释放，请重新连接"
        result.append(item)
    return result


def ensure_plc_runtime_client(con, device_id: int) -> Any | None:
    clients = plc_client_store()
    client = clients.get(device_id)
    if client is not None:
        if plc_client_connected(client):
            return client
        clients.pop(device_id, None)
        disconnect_client(client)
        now = utc_now_iso()
        con.execute(
            """
            UPDATE plc_devices
            SET status='disconnected', last_disconnected_at=?, last_error='PLC 运行时连接已断开', updated_at=?
            WHERE id=?
            """,
            (now, now, device_id),
        )
        log_plc_device_event(con, device_id, "disconnect", "disconnected", "PLC 运行时连接已断开")
        return None

    device = con.execute("SELECT * FROM plc_devices WHERE id=?", (device_id,)).fetchone()
    if not device or not bool(device["enabled"]) or device["status"] != "connected":
        return None
    if device["protocol"] != "s7_1500":
        return None

    result = connect_s7_1500(
        ip_address=device["ip_address"],
        port=int(device["port"]),
        rack=int(device["rack"]),
        slot=int(device["slot"]),
        timeout_ms=int(device["timeout_ms"]),
    )
    now = utc_now_iso()
    if result.ok and result.client is not None:
        clients[device_id] = result.client
        con.execute(
            """
            UPDATE plc_devices
            SET status='connected', pdu_length=?, last_connected_at=?, last_error=NULL, updated_at=?
            WHERE id=?
            """,
            (result.pdu_length, now, now, device_id),
        )
        log_plc_device_event(con, device_id, "reconnect", "connected", "采集轮询自动恢复 PLC 连接", result.pdu_length)
        return result.client

    con.execute(
        """
        UPDATE plc_devices
        SET status='error', pdu_length=NULL, last_error=?, updated_at=?
        WHERE id=?
        """,
        (result.message, now, device_id),
    )
    log_plc_device_event(con, device_id, "reconnect", "error", result.message)
    return None


def auto_connect_enabled_plc_devices(con) -> dict[str, int]:
    clients = plc_client_store()
    rows = con.execute("SELECT * FROM plc_devices WHERE enabled=1 ORDER BY id").fetchall()
    summary = {"attempted": 0, "connected": 0, "failed": 0, "skipped": 0}
    for device in rows:
        device_id = int(device["id"])
        if device["protocol"] != "s7_1500":
            summary["skipped"] += 1
            continue
        old_client = clients.pop(device_id, None)
        if old_client is not None:
            disconnect_client(old_client)
        summary["attempted"] += 1
        result = connect_s7_1500(
            ip_address=device["ip_address"],
            port=int(device["port"]),
            rack=int(device["rack"]),
            slot=int(device["slot"]),
            timeout_ms=int(device["timeout_ms"]),
        )
        now = utc_now_iso()
        if result.ok and result.client is not None:
            clients[device_id] = result.client
            con.execute(
                """
                UPDATE plc_devices
                SET status='connected', pdu_length=?, last_connected_at=?, last_error=NULL, updated_at=?
                WHERE id=?
                """,
                (result.pdu_length, now, now, device_id),
            )
            log_plc_device_event(con, device_id, "auto_connect", "connected", "项目启动自动连接 PLC 成功", result.pdu_length)
            summary["connected"] += 1
            continue

        con.execute(
            """
            UPDATE plc_devices
            SET status='error', pdu_length=NULL, last_error=?, updated_at=?
            WHERE id=?
            """,
            (result.message, now, device_id),
        )
        log_plc_device_event(con, device_id, "auto_connect", "error", result.message)
        summary["failed"] += 1
    return summary


def plc_client_connected(client: Any) -> bool:
    if not hasattr(client, "get_connected"):
        return True
    try:
        return bool(client.get_connected())
    except Exception:
        return False


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
