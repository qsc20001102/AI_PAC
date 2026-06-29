from __future__ import annotations

from pydantic import BaseModel, Field


class PlcWriteTestIn(BaseModel):
    dosing_point_id: int
    value_l_h: float = Field(ge=0, le=1000)
    quality: str = "test"
    mode: str = "simulation"


class PlcDeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    protocol: str = "s7_1500"
    ip_address: str = Field(min_length=1, max_length=120)
    port: int = Field(default=102, ge=1, le=65535)
    timeout_ms: int = Field(default=5000, ge=500, le=60000)
    rack: int = Field(default=0, ge=0, le=32)
    slot: int = Field(default=0, ge=0, le=32)
    enabled: bool = True


class PlcDeviceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    protocol: str = "s7_1500"
    ip_address: str = Field(min_length=1, max_length=120)
    port: int = Field(default=102, ge=1, le=65535)
    timeout_ms: int = Field(default=5000, ge=500, le=60000)
    rack: int = Field(default=0, ge=0, le=32)
    slot: int = Field(default=0, ge=0, le=32)
    enabled: bool = True
