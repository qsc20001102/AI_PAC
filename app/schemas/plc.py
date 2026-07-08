from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PlcDeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    protocol: str = "s7_1500"
    ip_address: str = Field(min_length=1, max_length=120)
    port: int = Field(default=102, ge=1, le=65535)
    timeout_ms: int = Field(default=5000, ge=500, le=60000)
    rack: int | None = Field(default=None, ge=0, le=32)
    slot: int | None = Field(default=None, ge=0, le=32)
    unit_id: int = Field(default=1, ge=1, le=255)
    byte_order: str = Field(default="ABCD")
    enabled: bool = True
    reconnect_enabled: bool = False
    reconnect_interval_seconds: int = Field(default=10, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_protocol_params(self) -> "PlcDeviceCreate":
        if self.protocol == "s7_1500":
            # S7-1500 协议：rack/slot 必须提供（默认 0），byte_order/unit_id 忽略
            if self.rack is None:
                self.rack = 0
            if self.slot is None:
                self.slot = 0
        elif self.protocol == "modbus_tcp":
            # Modbus TCP 协议：byte_order 必须在允许值中
            valid_byte_orders = {"ABCD", "DCBA", "BADC", "CDAB"}
            if self.byte_order not in valid_byte_orders:
                raise ValueError(f"byte_order 必须为 {valid_byte_orders} 之一")
        return self


class PlcDeviceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    protocol: str = "s7_1500"
    ip_address: str = Field(min_length=1, max_length=120)
    port: int = Field(default=102, ge=1, le=65535)
    timeout_ms: int = Field(default=5000, ge=500, le=60000)
    rack: int | None = Field(default=None, ge=0, le=32)
    slot: int | None = Field(default=None, ge=0, le=32)
    unit_id: int = Field(default=1, ge=1, le=255)
    byte_order: str = Field(default="ABCD")
    enabled: bool = True
    reconnect_enabled: bool = False
    reconnect_interval_seconds: int = Field(default=10, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_protocol_params(self) -> "PlcDeviceUpdate":
        if self.protocol == "s7_1500":
            # S7-1500 协议：rack/slot 必须提供（默认 0），byte_order/unit_id 忽略
            if self.rack is None:
                self.rack = 0
            if self.slot is None:
                self.slot = 0
        elif self.protocol == "modbus_tcp":
            # Modbus TCP 协议：byte_order 必须在允许值中
            valid_byte_orders = {"ABCD", "DCBA", "BADC", "CDAB"}
            if self.byte_order not in valid_byte_orders:
                raise ValueError(f"byte_order 必须为 {valid_byte_orders} 之一")
        return self