from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ModelKind = Literal["tp_out_response", "pac_flow_predict"]


class ModelPublishIn(BaseModel):
    version_id: int
    actor: str = "local"


class ModelProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dosing_point_id: int | None = None
    sample_interval_minutes: int = Field(default=5, ge=1, le=1440)
    model_kind: ModelKind = "tp_out_response"
    training_config: dict[str, Any] = Field(default_factory=dict)


class ModelProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sample_interval_minutes: int = Field(ge=1, le=1440)
    training_config: dict[str, Any] = Field(default_factory=dict)


class ModelSampleImportIn(BaseModel):
    csv_text: str | None = None
    csv_base64: str | None = None
    encoding: str | None = None


class ModelSampleBulkDeleteIn(BaseModel):
    sample_ids: list[int] = Field(min_length=1)


class ModelRecordingIn(BaseModel):
    sample_interval_minutes: int = Field(default=5, ge=1, le=1440)


class ModelDeployIn(BaseModel):
    enabled: bool
    actor: str = "local"
