from __future__ import annotations

from pydantic import BaseModel, Field


class ModelPublishIn(BaseModel):
    version_id: int
    actor: str = "local"


class ModelProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dosing_point_id: int
    sample_interval_minutes: int = Field(default=5, ge=1, le=1440)


class ModelProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sample_interval_minutes: int = Field(ge=1, le=1440)
    output_min: float = Field(ge=0.1, le=5)
    output_max: float = Field(ge=0.1, le=5)


class ModelSampleImportIn(BaseModel):
    csv_text: str | None = None
    csv_base64: str | None = None
    encoding: str | None = None


class ModelSampleBulkDeleteIn(BaseModel):
    sample_ids: list[int] = Field(min_length=1)


class ModelDeployIn(BaseModel):
    enabled: bool
    output_min: float = Field(ge=0.1, le=5)
    output_max: float = Field(ge=0.1, le=5)
    actor: str = "local"
