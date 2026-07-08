from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any


# P2-5 修复：原 PlcConnectResult/ModbusConnectResult 和 PlcReadResult/ModbusReadResult 结构几乎一致，
# 统一为 ConnectResult/ReadResult。旧名称保留为别名以兼容已有导入（如测试）。
@dataclass
class ConnectResult:
    ok: bool
    status: str
    message: str
    pdu_length: int | None = None
    client: Any | None = None


@dataclass
class ReadResult:
    value: bool | int | float
    value_text: str
    numeric_value: float
    address: str
    data_type: str
    byte_length: int


# 兼容别名：旧代码（含测试）按协议导入不同名称，此处保持向后兼容
PlcConnectResult = ConnectResult
ModbusConnectResult = ConnectResult
PlcReadResult = ReadResult
ModbusReadResult = ReadResult


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
        raise ValueError("S7-1500 地址格式错误，示例：M1.0、DB2.1186.0、I0.0、Q4.0")
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


def parse_modbus_address(address: str, data_type: str) -> dict[str, Any]:
    normalized_type = data_type.strip().upper()
    address_text = address.strip().upper()
    if not address_text:
        raise ValueError("Modbus 地址不能为空")

    # 支持两种格式：
    # 1. 标准 5 位地址：40001~4xxxx(保持寄存器)、30001~3xxxx(输入寄存器)、00001~0xxxx(线圈)、10001~1xxxx(离散输入)
    # 2. 简写前缀：H1000、I1000、C1000、D1000
    five_digit_match = re.fullmatch(r"(\d)(\d{4,5})", address_text)
    if five_digit_match:
        type_digit = five_digit_match.group(1)
        address_number = int(five_digit_match.group(2))
        # 5 位地址中后几位减 1 得到 0-based 地址
        register_number = address_number - 1
        if type_digit == "4":
            register_type = "holding"
        elif type_digit == "3":
            register_type = "input"
        elif type_digit == "0":
            register_type = "coil"
        elif type_digit == "1":
            register_type = "discrete"
        else:
            raise ValueError(
                "Modbus 5 位地址格式错误，示例：40001(保持寄存器)、30001(输入寄存器)、00001(线圈)、10001(离散输入)"
            )
    else:
        # 简写前缀格式
        prefix = address_text[0]
        number_part = address_text[1:] if len(address_text) > 1 else ""
        if not number_part.isdigit():
            raise ValueError(
                "Modbus 地址格式错误，示例：40001(保持寄存器)、30001(输入寄存器)、00001(线圈)、10001(离散输入)"
            )
        register_number = int(number_part)

        if prefix == "H":
            register_type = "holding"
        elif prefix == "I":
            register_type = "input"
        elif prefix == "C":
            register_type = "coil"
        elif prefix == "D":
            register_type = "discrete"
        else:
            raise ValueError(
                "Modbus 地址格式错误，示例：40001(保持寄存器)、30001(输入寄存器)、00001(线圈)、10001(离散输入)"
            )

    type_size = {"REAL": 2, "BOOL": 1, "INT": 1, "DINT": 2, "UINT": 1}[normalized_type]

    # 数据类型与寄存器类型校验
    if normalized_type in {"REAL", "INT", "DINT", "UINT"}:
        if register_type not in {"holding", "input"}:
            raise ValueError(f"{normalized_type} 类型只能使用保持寄存器(4xxxx)或输入寄存器(3xxxx)地址")
    elif normalized_type == "BOOL":
        if register_type not in {"coil", "discrete"}:
            raise ValueError("BOOL 类型只能使用线圈(0xxxx)或离散输入(1xxxx)地址")

    return {
        "register_type": register_type,
        "register_number": register_number,
        "data_type": normalized_type,
        "register_count": type_size,
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


def connect_modbus_tcp(
    *,
    ip_address: str,
    port: int = 502,
    timeout_ms: int = 5000,
) -> ModbusConnectResult:
    """连接 Modbus TCP 设备，使用 pymodbus 库

    注意：站号（unit_id/slave）在每次读取操作时指定，不在连接时设置。
    """
    try:
        from pymodbus.client import ModbusTcpClient
    except Exception as exc:
        return ModbusConnectResult(
            ok=False,
            status="error",
            message=f"pymodbus 未安装：{exc}",
        )

    try:
        client = ModbusTcpClient(ip_address, port=port, timeout=timeout_ms / 1000)
        if client.connect():
            return ModbusConnectResult(
                ok=True,
                status="connected",
                message="Modbus TCP 已连接",
                client=client,
            )
        return ModbusConnectResult(
            ok=False,
            status="error",
            message="Modbus TCP 连接失败",
        )
    except Exception as exc:
        return ModbusConnectResult(
            ok=False,
            status="error",
            message=f"连接异常：{exc}",
        )


def read_modbus_value(
    client: Any,
    address: str,
    data_type: str,
    byte_order: str = "ABCD",
    unit_id: int = 1,
) -> ModbusReadResult:
    """读取 Modbus 寄存器值

    address 格式：
    - 标准 5 位地址：40001~4xxxx(保持寄存器)、30001~3xxxx(输入寄存器)、00001~0xxxx(线圈)、10001~1xxxx(离散输入)
    - 简写前缀：H1000(保持寄存器)、I1000(输入寄存器)、C1000(线圈)、D1000(离散输入)

    data_type: REAL(32位浮点), INT(16位有符号), DINT(32位有符号), UINT(16位无符号), BOOL

    byte_order: ABCD(大端), DCBA(小端), BADC, CDAB

    unit_id: Modbus 站号/从站地址（Slave ID），范围 1-255
    """
    # 使用统一地址解析函数
    spec = parse_modbus_address(address, data_type)
    register_type = spec["register_type"]
    register_number = spec["register_number"]
    normalized_type = spec["data_type"]
    register_count = spec["register_count"]

    is_holding = register_type == "holding"
    is_input = register_type == "input"
    is_coil = register_type == "coil"
    is_discrete = register_type == "discrete"

    # 根据数据类型确定字节长度
    if normalized_type == "BOOL":
        byte_length = 1
    elif normalized_type == "INT":
        byte_length = 2
    elif normalized_type == "UINT":
        byte_length = 2
    elif normalized_type == "DINT":
        byte_length = 4
    elif normalized_type == "REAL":
        byte_length = 4
    else:
        raise ValueError("Modbus 数据类型只支持 BOOL、INT、UINT、DINT、REAL")

    # 数据类型与寄存器类型校验
    if normalized_type in {"REAL", "INT", "DINT", "UINT"}:
        if not (is_holding or is_input):
            raise ValueError(f"{normalized_type} 类型只能使用保持寄存器(4xxxx)或输入寄存器(3xxxx)地址")
    elif normalized_type == "BOOL":
        if not (is_coil or is_discrete):
            raise ValueError("BOOL 类型只能使用线圈(0xxxx)或离散输入(1xxxx)地址")

    # 读取数据
    if is_coil:
        # 读取线圈（Function Code 01）
        result = client.read_coils(address=register_number, count=register_count, device_id=unit_id)
        if result.isError():
            raise ValueError(f"读取线圈失败：{result}")
        coil_values = result.bits[:register_count]
        value = bool(coil_values[0])
    elif is_discrete:
        # 读取离散输入（Function Code 02）
        result = client.read_discrete_inputs(address=register_number, count=register_count, device_id=unit_id)
        if result.isError():
            raise ValueError(f"读取离散输入失败：{result}")
        discrete_values = result.bits[:register_count]
        value = bool(discrete_values[0])
    elif is_holding:
        # 读取保持寄存器（Function Code 03）
        result = client.read_holding_registers(address=register_number, count=register_count, device_id=unit_id)
        if result.isError():
            raise ValueError(f"读取保持寄存器失败：{result}")
        registers = result.registers
        value = decode_modbus_registers(registers, normalized_type, byte_order)
    elif is_input:
        # 读取输入寄存器（Function Code 04）
        result = client.read_input_registers(address=register_number, count=register_count, device_id=unit_id)
        if result.isError():
            raise ValueError(f"读取输入寄存器失败：{result}")
        registers = result.registers
        value = decode_modbus_registers(registers, normalized_type, byte_order)
    else:
        raise ValueError("未知寄存器类型")

    # 格式化输出
    if isinstance(value, bool):
        value_text = "true" if value else "false"
        numeric_value = 1.0 if value else 0.0
    elif isinstance(value, int):
        value_text = str(value)
        numeric_value = float(value)
    else:
        value_text = f"{value:.6g}"
        numeric_value = float(value)

    return ModbusReadResult(
        value=value,
        value_text=value_text,
        numeric_value=numeric_value,
        address=address,
        data_type=normalized_type,
        byte_length=byte_length,
    )


def decode_modbus_registers(
    registers: list[int],
    data_type: str,
    byte_order: str,
) -> bool | int | float:
    """解码 Modbus 寄存器值

    byte_order:
    - ABCD: 大端（Motorola格式），字节顺序 A B C D
    - DCBA: 小端（Intel格式），字节顺序 D C B A
    - BADC: 中间字节交换，字节顺序 B A D C
    - CDAB: 中间字交换，字节顺序 C D A B
    """
    if data_type == "BOOL":
        # 从寄存器的第0位读取布尔值
        return bool(registers[0] & 0x01)

    if data_type in ("INT", "UINT"):
        # 16位数据，单个寄存器
        raw_bytes = registers[0].to_bytes(2, byteorder="big", signed=False)
        # 根据字节序重组（对于16位数据，ABCD/DCBA效果相同）
        if byte_order in ("ABCD", "BADC"):
            # 大端
            if data_type == "INT":
                return int.from_bytes(raw_bytes, byteorder="big", signed=True)
            else:  # UINT
                return int.from_bytes(raw_bytes, byteorder="big", signed=False)
        else:  # DCBA, CDAB
            # 小端（16位数据需要交换字节）
            swapped = raw_bytes[::-1]
            if data_type == "INT":
                return int.from_bytes(swapped, byteorder="big", signed=True)
            else:  # UINT
                return int.from_bytes(swapped, byteorder="big", signed=False)

    if data_type in ("DINT", "REAL"):
        # 32位数据，2个寄存器
        # 每个寄存器是16位，按大端顺序读取
        byte_a = (registers[0] >> 8) & 0xFF
        byte_b = registers[0] & 0xFF
        byte_c = (registers[1] >> 8) & 0xFF
        byte_d = registers[1] & 0xFF

        # 根据字节序重组4字节
        if byte_order == "ABCD":
            reordered = bytes([byte_a, byte_b, byte_c, byte_d])
        elif byte_order == "DCBA":
            reordered = bytes([byte_d, byte_c, byte_b, byte_a])
        elif byte_order == "BADC":
            reordered = bytes([byte_b, byte_a, byte_d, byte_c])
        elif byte_order == "CDAB":
            reordered = bytes([byte_c, byte_d, byte_a, byte_b])
        else:
            raise ValueError(f"无效的字节序：{byte_order}")

        if data_type == "DINT":
            return int.from_bytes(reordered, byteorder="big", signed=True)
        else:  # REAL
            return float(struct.unpack(">f", reordered)[0])

    raise ValueError(f"不支持的数据类型：{data_type}")


def disconnect_modbus_client(client: Any) -> None:
    """断开 Modbus TCP 连接"""
    if client is None:
        return
    try:
        client.close()
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
