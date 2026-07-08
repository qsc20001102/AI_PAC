from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException

from app.api.common import row_to_dict
from app.database import utc_now_iso
from app.schemas import PlcDeviceCreate, PlcDeviceUpdate
from app.services.plc import (
    connect_modbus_tcp,
    connect_s7_1500,
    disconnect_client,
    disconnect_modbus_client,
)


_plc_clients: dict[int, Any] = {}
_last_reconnect_attempt: dict[int, float] = {}


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


def _connect_and_record(con, device, event_type: str, success_message: str) -> tuple[bool, Any | None]:
    """P2-5 修复：ensure_plc_runtime_client 与 auto_connect_enabled_plc_devices 的连接+DB更新+日志逻辑重复，抽取公共方法。
    返回 (ok, client)。调用方需保证 device["protocol"] 已校验为 s7_1500 或 modbus_tcp。"""
    protocol = device["protocol"]
    if protocol == "s7_1500":
        result = connect_s7_1500(
            ip_address=device["ip_address"],
            port=int(device["port"]),
            rack=int(device["rack"]),
            slot=int(device["slot"]),
            timeout_ms=int(device["timeout_ms"]),
        )
    elif protocol == "modbus_tcp":
        result = connect_modbus_tcp(
            ip_address=device["ip_address"],
            port=int(device["port"]),
            timeout_ms=int(device["timeout_ms"]),
        )
    else:
        return False, None

    now = utc_now_iso()
    device_id = int(device["id"])
    if result.ok and result.client is not None:
        pdu_length = getattr(result, "pdu_length", None)
        con.execute(
            """
            UPDATE plc_devices
            SET status='connected', pdu_length=?, last_connected_at=?, last_error=NULL, updated_at=?
            WHERE id=?
            """,
            (pdu_length, now, now, device_id),
        )
        log_plc_device_event(con, device_id, event_type, "connected", success_message, pdu_length)
        return True, result.client

    con.execute(
        """
        UPDATE plc_devices
        SET status='error', pdu_length=NULL, last_error=?, updated_at=?
        WHERE id=?
        """,
        (result.message, now, device_id),
    )
    log_plc_device_event(con, device_id, event_type, "error", result.message)
    return False, None


def ensure_plc_runtime_client(con, device_id: int) -> Any | None:
    clients = plc_client_store()
    client = clients.get(device_id)
    if client is not None:
        if plc_client_connected(client, device_id):
            return client
        clients.pop(device_id, None)
        disconnect_plc_client(client, device_id)
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
    if not device or not bool(device["enabled"]):
        return None

    protocol = device["protocol"]
    if protocol not in ("s7_1500", "modbus_tcp"):
        return None

    # 判断是否应该尝试连接
    should_try = device["status"] == "connected"
    if not should_try and bool(device["reconnect_enabled"]):
        last_attempt = _last_reconnect_attempt.get(device_id, 0)
        interval = int(device["reconnect_interval_seconds"])
        if time.monotonic() - last_attempt >= interval:
            should_try = True

    if not should_try:
        return None

    _last_reconnect_attempt[device_id] = time.monotonic()

    # P2-5 修复：连接+DB更新+日志逻辑抽取到 _connect_and_record。
    ok, client = _connect_and_record(con, device, "reconnect", "断线重连成功，PLC 连接已恢复")
    if ok:
        clients[device_id] = client
        _last_reconnect_attempt.pop(device_id, None)
        return client
    return None


def auto_connect_enabled_plc_devices(con) -> dict[str, int]:
    clients = plc_client_store()
    rows = con.execute("SELECT * FROM plc_devices WHERE enabled=1 ORDER BY id").fetchall()
    summary = {"attempted": 0, "connected": 0, "failed": 0, "skipped": 0}
    for device in rows:
        device_id = int(device["id"])
        protocol = device["protocol"]
        if protocol not in ("s7_1500", "modbus_tcp"):
            summary["skipped"] += 1
            continue
        old_client = clients.pop(device_id, None)
        if old_client is not None:
            disconnect_plc_client(old_client, device_id)
        summary["attempted"] += 1

        # P2-5 修复：连接+DB更新+日志逻辑抽取到 _connect_and_record。
        ok, client = _connect_and_record(con, device, "auto_connect", "项目启动自动连接 PLC 成功")
        if ok:
            clients[device_id] = client
            summary["connected"] += 1
        else:
            summary["failed"] += 1
    return summary


def plc_client_connected(client: Any, device_id: int | None = None) -> bool:
    """判断 PLC 客户端是否已连接

    支持两种协议：
    - S7-1500：通过 get_connected() 方法判断
    - Modbus TCP：通过 connected 属性判断
    """
    if client is None:
        return False

    # S7-1500 协议：有 get_connected 方法
    if hasattr(client, "get_connected"):
        try:
            return bool(client.get_connected())
        except Exception:
            return False

    # Modbus TCP 协议：有 connected 属性
    if hasattr(client, "connected"):
        try:
            return bool(client.connected)
        except Exception:
            return False

    # 无法判断时，假设已连接
    return True


def disconnect_plc_client(client: Any, device_id: int | None = None) -> None:
    """断开 PLC 客户端连接，根据协议类型分发

    支持两种协议：
    - S7-1500：调用 disconnect_client（disconnect + destroy）
    - Modbus TCP：调用 disconnect_modbus_client（close）
    """
    if client is None:
        return

    # S7-1500 协议：有 disconnect 和 destroy 方法
    if hasattr(client, "disconnect") and hasattr(client, "destroy"):
        disconnect_client(client)
        return

    # Modbus TCP 协议：有 close 方法
    if hasattr(client, "close"):
        disconnect_modbus_client(client)
        return

    # 未知类型，尝试通用断开
    try:
        if hasattr(client, "disconnect"):
            client.disconnect()
    except Exception:
        pass
    try:
        if hasattr(client, "close"):
            client.close()
    except Exception:
        pass


def get_plc_device_or_404(con, device_id: int):
    device = con.execute("SELECT * FROM plc_devices WHERE id=?", (device_id,)).fetchone()
    if not device:
        raise HTTPException(404, "PLC 设备不存在")
    return device


def validate_plc_device_payload(payload: PlcDeviceCreate | PlcDeviceUpdate) -> None:
    if payload.protocol not in ("s7_1500", "modbus_tcp"):
        raise HTTPException(422, "当前只支持 S7-1500 和 Modbus TCP 协议")
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
