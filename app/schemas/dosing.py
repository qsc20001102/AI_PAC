from __future__ import annotations

from pydantic import BaseModel, Field


class DosingPointBase(BaseModel):
    """投加点公共字段：tag_id 引用、权重、模型关联等。"""

    process_line_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=60)
    in_flow_tag_id: int | None = None
    in_tp_tag_id: int | None = None
    in_ph_tag_id: int | None = None
    out_flow_tag_id: int | None = None
    out_tp_tag_id: int | None = None
    in_flow_weight: float = Field(default=1.0, ge=0)
    reflux_flow_1_tag_id: int | None = None
    reflux_flow_2_tag_id: int | None = None
    pac_flow_tag_id: int | None = None
    bio_orp1_tag_id: int | None = None
    bio_orp2_tag_id: int | None = None
    bio_orp3_tag_id: int | None = None
    bio_orp4_tag_id: int | None = None
    bio_do1_tag_id: int | None = None
    bio_do2_tag_id: int | None = None
    bio_mlss1_tag_id: int | None = None
    bio_mlss2_tag_id: int | None = None
    tp_model_id: int | None = None
    pac_flow_model_id: int | None = None
    dual_model_id: int | None = None
    process_parameter_group_id: int | None = None


# P2-3 修复：原 DosingPointCreate 与 DosingPointUpdate 95%+ 字段重复。
# 抽取 DosingPointBase 承载公共字段；Create 使用业务默认值，Update 用 None 表示"不修改"。
class DosingPointCreate(DosingPointBase):
    enabled: bool = True
    flow_source: str | None = "line"
    display_order: int | None = Field(default=0, ge=0, le=10000)
    write_enabled: bool = False


class DosingPointUpdate(DosingPointBase):
    enabled: bool
    flow_source: str | None = None
    display_order: int | None = Field(default=None, ge=0, le=10000)
    write_enabled: bool | None = None


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
