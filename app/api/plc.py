from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.common import row_to_dict
from app.database import db_session, utc_now_iso
from app.schemas import PlcDeviceCreate, PlcDeviceUpdate
from app.services.audit import audit
from app.services.plc import connect_s7_1500, disconnect_client
from app.services.plc_devices import (
    get_plc_device_or_404,
    log_plc_device_event,
    plc_client_store,
    plc_device_rows,
    validate_plc_device_payload,
)


router = APIRouter()


@router.get("/api/plc")
def plc_status() -> dict[str, Any]:
    with db_session() as con:
        devices = plc_device_rows(con)
        events = [
            row_to_dict(row)
            for row in con.execute(
                """
                SELECT e.*, d.name AS device_name
                FROM plc_device_events e
                JOIN plc_devices d ON d.id=e.device_id
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT 30
                """
            ).fetchall()
        ]
    return {
        "devices": devices,
        "events": events,
        "supported_protocols": [{"value": "s7_1500", "label": "S7-1500"}],
    }


@router.post("/api/plc/devices")
def create_plc_device(payload: PlcDeviceCreate) -> dict[str, Any]:
    validate_plc_device_payload(payload)
    now = utc_now_iso()
    with db_session() as con:
        cur = con.execute(
            """
            INSERT INTO plc_devices(
                name,protocol,ip_address,port,timeout_ms,rack,slot,pdu_length,status,
                last_connected_at,last_disconnected_at,last_error,enabled,
                reconnect_enabled,reconnect_interval_seconds,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.name.strip(),
                payload.protocol,
                payload.ip_address.strip(),
                payload.port,
                payload.timeout_ms,
                payload.rack,
                payload.slot,
                None,
                "disconnected",
                None,
                None,
                "pending connection",
                int(payload.enabled),
                int(payload.reconnect_enabled),
                payload.reconnect_interval_seconds,
                now,
                now,
            ),
        )
        device_id = int(cur.lastrowid)
        log_plc_device_event(con, device_id, "create", "disconnected", "PLC device created")
        audit(con, "local", "create", "plc_device", str(device_id), payload.model_dump())
        device = row_to_dict(con.execute("SELECT * FROM plc_devices WHERE id=?", (device_id,)).fetchone())
        device["runtime_connected"] = False
    return {"ok": True, "device": device}


@router.put("/api/plc/devices/{device_id}")
def update_plc_device(device_id: int, payload: PlcDeviceUpdate) -> dict[str, Any]:
    validate_plc_device_payload(payload)
    now = utc_now_iso()
    with db_session() as con:
        device = get_plc_device_or_404(con, device_id)
        active_client = plc_client_store().pop(device_id, None)
        if active_client is not None:
            disconnect_client(active_client)
            log_plc_device_event(con, device_id, "disconnect", "disconnected", "Configuration changed; connection closed", device["pdu_length"])
        con.execute(
            """
            UPDATE plc_devices
            SET name=?, protocol=?, ip_address=?, port=?, timeout_ms=?, rack=?, slot=?,
                status='disconnected', last_disconnected_at=?, last_error=NULL, enabled=?,
                reconnect_enabled=?, reconnect_interval_seconds=?,
                updated_at=?
            WHERE id=?
            """,
            (
                payload.name.strip(),
                payload.protocol,
                payload.ip_address.strip(),
                payload.port,
                payload.timeout_ms,
                payload.rack,
                payload.slot,
                now,
                int(payload.enabled),
                int(payload.reconnect_enabled),
                payload.reconnect_interval_seconds,
                now,
                device_id,
            ),
        )
        log_plc_device_event(con, device_id, "update", "disconnected", "PLC device updated")
        audit(con, "local", "update", "plc_device", str(device_id), payload.model_dump())
        updated = row_to_dict(con.execute("SELECT * FROM plc_devices WHERE id=?", (device_id,)).fetchone())
        updated["runtime_connected"] = False
    return {"ok": True, "device": updated}


@router.delete("/api/plc/devices/{device_id}")
def delete_plc_device(device_id: int) -> dict[str, Any]:
    with db_session() as con:
        device = get_plc_device_or_404(con, device_id)
        active_client = plc_client_store().pop(device_id, None)
        if active_client is not None:
            disconnect_client(active_client)
        con.execute("DELETE FROM plc_devices WHERE id=?", (device_id,))
        audit(con, "local", "delete", "plc_device", str(device_id), row_to_dict(device))
    return {"ok": True, "deleted_id": device_id}


@router.post("/api/plc/devices/{device_id}/connect")
def connect_plc_device(device_id: int) -> dict[str, Any]:
    with db_session() as con:
        device = get_plc_device_or_404(con, device_id)
        if not bool(device["enabled"]):
            raise HTTPException(409, "PLC device is disabled")
        if device["protocol"] != "s7_1500":
            raise HTTPException(422, "Only S7-1500 is supported")

        clients = plc_client_store()
        old_client = clients.pop(device_id, None)
        if old_client is not None:
            disconnect_client(old_client)

        result = connect_s7_1500(
            ip_address=device["ip_address"],
            port=int(device["port"]),
            rack=int(device["rack"]),
            slot=int(device["slot"]),
            timeout_ms=int(device["timeout_ms"]),
        )
        now = utc_now_iso()
        if result.ok:
            clients[device_id] = result.client
            con.execute(
                """
                UPDATE plc_devices
                SET status='connected', pdu_length=?, last_connected_at=?, last_error=NULL, updated_at=?
                WHERE id=?
                """,
                (result.pdu_length, now, now, device_id),
            )
            log_plc_device_event(con, device_id, "connect", "connected", result.message, result.pdu_length)
            audit(con, "local", "connect", "plc_device", str(device_id), {"pdu_length": result.pdu_length})
        else:
            con.execute(
                """
                UPDATE plc_devices
                SET status='error', pdu_length=NULL, last_error=?, updated_at=?
                WHERE id=?
                """,
                (result.message, now, device_id),
            )
            log_plc_device_event(con, device_id, "connect", "error", result.message)
            audit(con, "local", "connect_failed", "plc_device", str(device_id), {"message": result.message})
        updated = row_to_dict(con.execute("SELECT * FROM plc_devices WHERE id=?", (device_id,)).fetchone())
        updated["runtime_connected"] = device_id in clients
    return {"ok": result.ok, "message": result.message, "device": updated}


@router.post("/api/plc/devices/{device_id}/disconnect")
def disconnect_plc_device(device_id: int) -> dict[str, Any]:
    with db_session() as con:
        device = get_plc_device_or_404(con, device_id)
        active_client = plc_client_store().pop(device_id, None)
        if active_client is not None:
            disconnect_client(active_client)
            message = "PLC connection closed"
        else:
            message = "No active runtime connection; device marked disconnected"
        now = utc_now_iso()
        con.execute(
            """
            UPDATE plc_devices
            SET status='disconnected', last_disconnected_at=?, last_error=NULL, updated_at=?
            WHERE id=?
            """,
            (now, now, device_id),
        )
        log_plc_device_event(con, device_id, "disconnect", "disconnected", message, device["pdu_length"])
        audit(con, "local", "disconnect", "plc_device", str(device_id), {})
        updated = row_to_dict(con.execute("SELECT * FROM plc_devices WHERE id=?", (device_id,)).fetchone())
        updated["runtime_connected"] = False
    return {"ok": True, "message": message, "device": updated}
