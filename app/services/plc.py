from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any


@dataclass
class PlcConnectResult:
    ok: bool
    status: str
    message: str
    pdu_length: int | None = None
    client: Any | None = None


@dataclass
class PlcReadResult:
    value: bool | int | float
    value_text: str
    numeric_value: float
    address: str
    data_type: str
    byte_length: int


def connect_s7_1500(
    *,
    ip_address: str,
    port: int = 102,
    rack: int = 0,
    slot: int = 0,
    timeout_ms: int = 5000,
) -> PlcConnectResult:
    try:
        import snap7  # type: ignore
    except Exception as exc:
        return PlcConnectResult(
            ok=False,
            status="error",
            message=f"python-snap7 未安装或不可用：{exc}",
        )

    client = None
    try:
        client = snap7.client.Client()
        _set_timeout(client, timeout_ms)
        _connect_client(client, ip_address, rack, slot, port)
        connected = bool(client.get_connected()) if hasattr(client, "get_connected") else True
        if not connected:
            return PlcConnectResult(ok=False, status="error", message="S7 连接未建立")
        pdu = _get_pdu_length(client)
        return PlcConnectResult(
            ok=True,
            status="connected",
            message="S7-1500 已连接",
            pdu_length=pdu,
            client=client,
        )
    except Exception as exc:
        disconnect_client(client)
        return PlcConnectResult(ok=False, status="error", message=f"S7 连接失败：{exc}")


def read_s7_value(client: Any, address: str, data_type: str) -> PlcReadResult:
    spec = parse_s7_address(address, data_type)
    if spec["area"] == "DB":
        raw = client.db_read(spec["db_number"], spec["byte_offset"], spec["byte_length"])
    elif spec["area"] == "M":
        raw = client.mb_read(spec["byte_offset"], spec["byte_length"])
    elif spec["area"] == "I":
        raw = client.eb_read(spec["byte_offset"], spec["byte_length"])
    elif spec["area"] == "Q":
        raw = client.ab_read(spec["byte_offset"], spec["byte_length"])
    else:
        raise ValueError("数据地址只支持 M、DB、I、Q")

    value = decode_s7_value(bytes(raw), spec["data_type"], spec["bit_offset"])
    if isinstance(value, bool):
        value_text = "true" if value else "false"
        numeric_value = 1.0 if value else 0.0
    elif isinstance(value, int):
        value_text = str(value)
        numeric_value = float(value)
    else:
        value_text = f"{value:.6g}"
        numeric_value = float(value)
    return PlcReadResult(
        value=value,
        value_text=value_text,
        numeric_value=numeric_value,
        address=address,
        data_type=spec["data_type"],
        byte_length=spec["byte_length"],
    )


def parse_s7_address(address: str, data_type: str) -> dict[str, Any]:
    normalized_type = data_type.strip().upper()
    if normalized_type not in {"REAL", "BOOL", "INT"}:
        raise ValueError("数据类型只支持 REAL、BOOL、INT")
    byte_length = {"REAL": 4, "BOOL": 1, "INT": 2}[normalized_type]
    text = address.strip().upper()
    db_match = re.fullmatch(r"DB(\d+)\.(\d+)(?:\.(\d+))?", text)
    area_match = re.fullmatch(r"([MIQ])(\d+)(?:\.(\d+))?", text)
    if db_match:
        db_number = int(db_match.group(1))
        byte_offset = int(db_match.group(2))
        bit_offset = int(db_match.group(3) or 0)
        area = "DB"
    elif area_match:
        db_number = None
        area = area_match.group(1)
        byte_offset = int(area_match.group(2))
        bit_offset = int(area_match.group(3) or 0)
    else:
        raise ValueError("数据地址格式错误，示例：M1.0、DB2.1186.0、I0.0、Q4.0")
    if byte_offset < 0 or bit_offset < 0 or bit_offset > 7:
        raise ValueError("数据地址偏移量无效")
    if normalized_type == "BOOL" and bit_offset > 7:
        raise ValueError("BOOL 位偏移必须为 0-7")
    return {
        "area": area,
        "db_number": db_number,
        "byte_offset": byte_offset,
        "bit_offset": bit_offset,
        "data_type": normalized_type,
        "byte_length": byte_length,
    }


def decode_s7_value(raw: bytes, data_type: str, bit_offset: int = 0) -> bool | int | float:
    if data_type == "BOOL":
        if not raw:
            raise ValueError("BOOL 读取结果为空")
        return bool(raw[0] & (1 << bit_offset))
    if data_type == "INT":
        if len(raw) < 2:
            raise ValueError("INT 至少需要 2 字节")
        return int.from_bytes(raw[:2], byteorder="big", signed=True)
    if data_type == "REAL":
        if len(raw) < 4:
            raise ValueError("REAL 至少需要 4 字节")
        return float(struct.unpack(">f", raw[:4])[0])
    raise ValueError("数据类型只支持 REAL、BOOL、INT")


def disconnect_client(client: Any) -> None:
    if client is None:
        return
    try:
        client.disconnect()
    except Exception:
        pass
    try:
        client.destroy()
    except Exception:
        pass


def _connect_client(client: Any, ip_address: str, rack: int, slot: int, port: int) -> None:
    try:
        client.connect(ip_address, rack, slot, tcp_port=port)
    except TypeError as exc:
        if "tcp_port" not in str(exc):
            raise
        client.connect(ip_address, rack, slot, tcpport=port)


def _set_timeout(client: Any, timeout_ms: int) -> None:
    # python-snap7 versions expose timeout controls differently. Use what is available.
    if not hasattr(client, "set_param"):
        return
    try:
        import snap7  # type: ignore

        if hasattr(snap7, "types") and hasattr(snap7.types, "Parameter"):
            client.set_param(snap7.types.Parameter.RemotePort, 102)
            client.set_param(snap7.types.Parameter.RecvTimeout, int(timeout_ms))
            client.set_param(snap7.types.Parameter.SendTimeout, int(timeout_ms))
    except Exception:
        return


def _get_pdu_length(client: Any) -> int | None:
    for method_name in ("get_pdu_length", "get_pdu_requested"):
        if hasattr(client, method_name):
            try:
                value = getattr(client, method_name)()
                if isinstance(value, tuple):
                    value = value[0]
                return int(value)
            except Exception:
                continue
    return None
