"""投加点过程变量统一定义（P1-6 单一数据源）。

历史上 `model_training.MODEL_INPUT_FEATURES` / `DUAL_TASK_INPUT_FEATURES`、
`recommendation.PROCESS_SOURCE_MAP`、`wwtp_ai_engine.RAW_COLS` / `TAG_TO_RAW_MAP`
各自维护了一份过程变量映射，存在三处重复且容易漂移。本模块作为唯一数据源，
其余模块均派生引用，技术字段（dosing_field / tag_type / logical_type / raw_col / unit）
不再分散定义；展示用 label 按场景保留（`label` 用于推荐/采集展示，`dual_label`
用于模型训练配置 UI）。
"""
from __future__ import annotations

from typing import NamedTuple


class ProcessVariable(NamedTuple):
    dosing_field: str   # dosing_points 表的外键字段，如 in_flow_tag_id
    tag_type: str       # sensor_tags.tag_type，如 Q
    logical_type: str   # recommendation 逻辑类型，如 IN_Q
    raw_col: str        # wwtp_ai_engine 原始列名，如 inflow_flow
    unit: str           # 工程单位
    label: str          # 推荐/采集场景展示名
    dual_label: str     # 模型训练配置 UI 展示名


# 顺序与 wwtp_ai_engine.RAW_COLS 保持一致（决定 CSV 导入/导出列顺序）。
PROCESS_VARIABLES: list[ProcessVariable] = [
    ProcessVariable("in_flow_tag_id", "Q", "IN_Q", "inflow_flow", "m3/h", "进水流量", "生化池A进水流量过程值"),
    ProcessVariable("in_tp_tag_id", "TP_BEFORE", "TP_BEFORE", "inflow_tp", "mg/L", "进水TP", "进水总磷过程值"),
    ProcessVariable("in_ph_tag_id", "PH", "PH", "inflow_ph", "", "进水PH", "进水在线PH过程值"),
    ProcessVariable("out_tp_tag_id", "TP_OUT", "TP_OUT", "outflow_tp", "mg/L", "出水TP", "出水总磷过程值"),
    ProcessVariable("reflux_flow_1_tag_id", "REFLUX_Q1", "REFLUX_Q1", "high_density_a1_return", "m3/h", "回流流量1", "高密A1回流流量过程值"),
    ProcessVariable("reflux_flow_2_tag_id", "REFLUX_Q2", "REFLUX_Q2", "high_density_a2_return", "m3/h", "回流流量2", "高密A2回流流量过程值"),
    ProcessVariable("bio_orp1_tag_id", "BIO_ORP1", "BIO_ORP1", "orp_east_1", "mV", "生化池ORP1", "生化池A东ORP1过程值"),
    ProcessVariable("bio_orp2_tag_id", "BIO_ORP2", "BIO_ORP2", "orp_east_2", "mV", "生化池ORP2", "生化池A东ORP2过程值"),
    ProcessVariable("bio_orp3_tag_id", "BIO_ORP3", "BIO_ORP3", "orp_west_1", "mV", "生化池ORP3", "生化池A西ORP1过程值"),
    ProcessVariable("bio_orp4_tag_id", "BIO_ORP4", "BIO_ORP4", "orp_west_2", "mV", "生化池ORP4", "生化池A西ORP2过程值"),
    ProcessVariable("bio_mlss1_tag_id", "BIO_MLSS1", "BIO_MLSS1", "mlss_east", "mg/L", "生化池MLSS1", "生化池A东MLSS过程值"),
    ProcessVariable("bio_mlss2_tag_id", "BIO_MLSS2", "BIO_MLSS2", "mlss_west", "mg/L", "生化池MLSS2", "生化池A西MLSS过程值"),
    ProcessVariable("pac_flow_tag_id", "PAC_ACTUAL", "PAC_ACTUAL", "pac_dosage", "L/h", "加药流量", "PAC1加药流量过程值"),
]


def raw_cols() -> list[str]:
    """wwtp_ai_engine 期望的原始列名顺序（首列为 timestamp）。"""
    return ["timestamp", *[pv.raw_col for pv in PROCESS_VARIABLES]]


def tag_to_raw_map() -> dict[str, str]:
    return {pv.tag_type: pv.raw_col for pv in PROCESS_VARIABLES}


def process_source_map() -> list[tuple[str, str, str, str]]:
    """recommendation.PROCESS_SOURCE_MAP 派生： (dosing_field, logical_type, label, unit)。"""
    return [(pv.dosing_field, pv.logical_type, pv.label, pv.unit) for pv in PROCESS_VARIABLES]


def dual_task_input_features() -> list[tuple[str, str, str, str]]:
    """model_training.DUAL_TASK_INPUT_FEATURES 派生： (raw_col, dosing_field, dual_label, unit)。"""
    return [(pv.raw_col, pv.dosing_field, pv.dual_label, pv.unit) for pv in PROCESS_VARIABLES]
