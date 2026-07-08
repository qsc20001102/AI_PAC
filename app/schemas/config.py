from __future__ import annotations

from pydantic import BaseModel, Field


class UnitDoseCurvePoint(BaseModel):
    tp_mg_l: float = Field(ge=0, le=20)
    dose_mg_l: float = Field(ge=0, le=10000)


class ProcessParameterGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    tp_target_mg_l: float = Field(ge=0, le=5)
    tp_upper_mg_l: float = Field(ge=0, le=10)
    pac_min_l_h: float = Field(ge=0, le=500)
    pac_max_l_h: float = Field(ge=0, le=1000)
    calculation_interval_seconds: int = Field(ge=5, le=86400)
    pac_density_kg_l: float = Field(gt=0, le=2)
    unit_dose_curve: list[UnitDoseCurvePoint] = Field(min_length=2)
    tp_hrt_minutes: float | None = Field(default=None, ge=1, le=1440)


class SettingUpdate(BaseModel):
    value: str
