from __future__ import annotations

from pydantic import BaseModel, Field


class DosingPointCreate(BaseModel):
    process_line_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=60)
    enabled: bool = True
    flow_source: str | None = "line"
    phosphorus_source: str | None = "po4_priority"
    feedback_source: str | None = "line_out"
    in_flow_tag_id: int | None = None
    in_tp_tag_id: int | None = None
    out_flow_tag_id: int | None = None
    out_tp_tag_id: int | None = None
    zone_flow_tag_id: int | None = None
    in_flow_weight: float = Field(default=1.0, ge=0, le=1)
    reflux_flow_1_tag_id: int | None = None
    reflux_flow_2_tag_id: int | None = None
    po4_tag_id: int | None = None
    pac_flow_tag_id: int | None = None
    chemical_group_id: int | None = None
    process_parameter_group_id: int | None = None
    manual_contribution_factor: float | None = Field(default=1.0, ge=0, le=5)
    display_order: int | None = Field(default=0, ge=0, le=10000)
    write_enabled: bool = False


class DosingPointUpdate(BaseModel):
    process_line_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=60)
    enabled: bool
    flow_source: str | None = None
    phosphorus_source: str | None = None
    feedback_source: str | None = None
    in_flow_tag_id: int | None = None
    in_tp_tag_id: int | None = None
    out_flow_tag_id: int | None = None
    out_tp_tag_id: int | None = None
    zone_flow_tag_id: int | None = None
    in_flow_weight: float = Field(default=1.0, ge=0, le=1)
    reflux_flow_1_tag_id: int | None = None
    reflux_flow_2_tag_id: int | None = None
    po4_tag_id: int | None = None
    pac_flow_tag_id: int | None = None
    chemical_group_id: int | None = None
    process_parameter_group_id: int | None = None
    manual_contribution_factor: float | None = Field(default=None, ge=0, le=5)
    display_order: int | None = Field(default=None, ge=0, le=10000)
    write_enabled: bool | None = None


class ManualSampleIn(BaseModel):
    dosing_point_id: int
    tag_type: str
    value: float
    sample_time: str | None = None
    operator: str = "local"
    note: str | None = None


class IngestSampleIn(BaseModel):
    tag_code: str
    value: float
    unit: str | None = None
    sample_time: str | None = None
    receive_time: str | None = None
    quality: str = "good"
    source: str = "api"


class IngestBatchIn(BaseModel):
    samples: list[IngestSampleIn]
    source_name: str = "外部采集 API"
    recalculate: bool = True


class CsvImportIn(BaseModel):
    csv_text: str
    source: str = "csv_import"
    recalculate: bool = True


class CollectionTagUpdate(BaseModel):
    tag_code: str = Field(min_length=1, max_length=80)
    data_type: str = "REAL"
    plc_device_id: int | None = None
    data_address: str = Field(default="", max_length=80)
    poll_interval_seconds: int = Field(default=5, ge=1, le=60)
    history_enabled: bool = True
    history_interval_minutes: int = Field(default=5, ge=1, le=60)
    enabled: bool = True


class CollectionTagCreate(CollectionTagUpdate):
    tag_type: str = Field(default="CUSTOM", min_length=1, max_length=40)
    unit: str = Field(default="", max_length=40)


class HistoryPurgeIn(BaseModel):
    days: int = Field(ge=1, le=3650)
