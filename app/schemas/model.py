from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ModelKind = Literal["tp_out_response", "pac_flow_predict"]


class ModelProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dosing_point_id: int | None = None
    model_kind: ModelKind = "tp_out_response"
    training_config: dict[str, Any] = Field(default_factory=dict)


class ModelProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    training_config: dict[str, Any] = Field(default_factory=dict)


class ModelSampleImportIn(BaseModel):
    csv_text: str | None = None
    csv_base64: str | None = None
    encoding: str | None = None


class ModelSampleBulkDeleteIn(BaseModel):
    sample_ids: list[int] = Field(min_length=1)


class ModelDeployIn(BaseModel):
    enabled: bool
    actor: str = "local"
