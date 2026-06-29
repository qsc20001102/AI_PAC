from __future__ import annotations

from pydantic import BaseModel, Field


class PacConfigUpdate(BaseModel):
    pac_density_kg_l: float = Field(gt=0, le=2)
    al2o3_fraction: float = Field(gt=0, le=1)
    effective_factor: float = Field(gt=0, le=1.5)
    al_p_ratio: float = Field(ge=0.1, le=8)
    batch_id: str = Field(min_length=1, max_length=80)


class ControlConfigUpdate(BaseModel):
    tp_target_mg_l: float = Field(ge=0, le=5)
    tp_safe_target_mg_l: float = Field(ge=0, le=5)
    tp_limit_mg_l: float = Field(ge=0, le=10)
    pac_min_l_h: float = Field(ge=0, le=500)
    pac_max_l_h: float = Field(ge=0, le=1000)
    single_step_change_ratio: float = Field(ge=0, le=1)
    max_increase_l_h_per_min: float = Field(ge=0, le=100)
    max_decrease_l_h_per_min: float = Field(ge=0, le=100)
    lag_minutes: int = Field(ge=0, le=360)
    feedback_kp: float = Field(ge=0, le=2)
    feedback_min: float = Field(ge=0.1, le=2)
    feedback_max: float = Field(ge=0.1, le=2)
    feedback_window_minutes: int = Field(ge=5, le=720)


class ChemicalGroupIn(BaseModel):
    batch_id: str = Field(min_length=1, max_length=80)
    pac_density_kg_l: float = Field(gt=0, le=2)
    effective_factor: float = Field(gt=0, le=1.5)
    al_p_ratio: float = Field(ge=0.1, le=8)


class ProcessParameterGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    tp_target_mg_l: float = Field(ge=0, le=5)
    tp_limit_mg_l: float = Field(ge=0, le=10)
    pac_min_l_h: float = Field(ge=0, le=500)
    pac_max_l_h: float = Field(ge=0, le=1000)
    calculation_interval_seconds: int = Field(ge=5, le=86400)
    lag_minutes: int = Field(ge=0, le=360)
    feedback_kp: float = Field(ge=0, le=2)
    feedback_min: float = Field(ge=0.1, le=2)
    feedback_max: float = Field(ge=0.1, le=2)
    feedback_window_minutes: int = Field(ge=5, le=720)


class SettingUpdate(BaseModel):
    value: str
