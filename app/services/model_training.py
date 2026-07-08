from __future__ import annotations

import base64
import csv
import io
import math
from datetime import datetime
from typing import Any

import lightgbm as lgb
import numpy as np
from fastapi import HTTPException

from app.api.common import row_to_dict
from app.database import db_session, dumps_json, loads_json, utc_now_iso
from app.schemas import ModelSampleImportIn
from app.services import wwtp_ai_engine


MODEL_SAMPLE_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
MODEL_SAMPLE_TIME_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)

MODEL_KIND_AI_PAC_DUAL_TASK = "ai_pac_dual_task"
SUPPORTED_MODEL_KINDS = {MODEL_KIND_AI_PAC_DUAL_TASK}
TP_FORECAST_LEGACY_TARGET_ALIASES = (
    "下一次出水TP检测数据",
    "下一次出水TP",
    "下次出水TP",
    "未来出水TP",
    "目标出水TP",
    "TP_OUT_NEXT",
    "target_tp_out_next",
    "_training_target_tp_out_next",
    "未来60分钟出水TP",
    "TP_OUT_60",
    "target_tp_out_60",
    "_training_target_tp_out_60",
)
PAC_FLOW_TARGET_ALIASES = (
    "实际加药流量",
    "加药流量",
    "PAC_ACTUAL",
    "target_pac_actual",
    "_training_target_pac_actual",
)
MODEL_INPUT_FEATURES = [
    ("Q", None, "参考流量", "m3/h"),
    ("TP_BEFORE", "in_tp_tag_id", "进水TP", "mg/L"),
    ("PH", "in_ph_tag_id", "进水PH", ""),
    ("TP_OUT", "out_tp_tag_id", "出水TP", "mg/L"),
    ("REFLUX_Q1", "reflux_flow_1_tag_id", "回流流量1", "m3/h"),
    ("REFLUX_Q2", "reflux_flow_2_tag_id", "回流流量2", "m3/h"),
    ("BIO_ORP1", "bio_orp1_tag_id", "生化池A东ORP1", "mV"),
    ("BIO_ORP2", "bio_orp2_tag_id", "生化池A东ORP2", "mV"),
    ("BIO_ORP3", "bio_orp3_tag_id", "生化池A西ORP1", "mV"),
    ("BIO_ORP4", "bio_orp4_tag_id", "生化池A西ORP2", "mV"),
    ("BIO_MLSS1", "bio_mlss1_tag_id", "生化池MLSS1", "mg/L"),
    ("BIO_MLSS2", "bio_mlss2_tag_id", "生化池MLSS2", "mg/L"),
]
SPLIT_METHODS = {"time", "random"}
OBJECTIVES = {"huber", "regression_l2", "regression_l1"}
METRICS = {"rmse", "mae", "mse", "l1", "l2", "huber"}
BOOSTING_TYPES = {"gbdt", "dart", "rf"}


def model_row_value(model, key: str, default: Any = None) -> Any:
    if isinstance(model, dict):
        return model.get(key, default)
    return model[key] if key in model.keys() else default


def model_kind(model) -> str:
    return model_row_value(model, "model_kind", MODEL_KIND_TP_OUT_RESPONSE) or MODEL_KIND_TP_OUT_RESPONSE


def default_training_config(kind: str, schema: list[dict[str, Any]]) -> dict[str, Any]:
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return wwtp_ai_engine.DEFAULT_TRAIN_CONFIG.copy()
    _target_name, target_key, _target_label = target_definition_for_kind(kind)
    feature_columns = [str(item["key"]) for item in schema]
    return {
        "target_column": target_key,
        "feature_columns": feature_columns,
        "valid_ratio": 0.2,
        "split_method": "time",
        "objective": "huber",
        "metric": ["rmse"],
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_boost_round": 300,
        "early_stopping_rounds": 50,
        "num_leaves": 15,
        "max_depth": 4,
        "min_data_in_leaf": 20,
        "min_sum_hessian_in_leaf": 0.001,
        "max_delta_step": 0,
        "max_bin": 255,
        "min_data_in_bin": 3,
        "bin_construct_sample_cnt": 200000,
        "lambda_l1": 0.3,
        "lambda_l2": 20.0,
        "min_gain_to_split": 0.02,
        "path_smooth": 0,
        "linear_lambda": 0,
        "feature_fraction": 0.9,
        "feature_fraction_bynode": 1.0,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "extra_trees": False,
        "monotone_constraints": {key: 0 for key in feature_columns},
        "seed": 42,
        "feature_fraction_seed": 42,
        "bagging_seed": 42,
        "data_random_seed": 42,
        "extra_seed": 42,
        "deterministic": True,
    }


def _config_float(value: Any, default: float, min_value: float, max_value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return min(max(number, min_value), max_value)


def _config_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return min(max(number, min_value), max_value)


def normalize_training_config(raw: Any, kind: str, schema: list[dict[str, Any]]) -> dict[str, Any]:
    if kind not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return wwtp_ai_engine.normalize_training_config(raw)
    base = default_training_config(kind, schema)
    raw = raw if isinstance(raw, dict) else {}
    schema_keys = [str(item["key"]) for item in schema]
    requested_features = raw.get("feature_columns", base["feature_columns"])
    if not isinstance(requested_features, list):
        requested_features = base["feature_columns"]
    feature_columns = [str(key) for key in requested_features if str(key) in schema_keys]
    if not feature_columns:
        raise HTTPException(422, "至少需要选择 1 个输入字段")

    raw_constraints = raw.get("monotone_constraints", {})
    if isinstance(raw_constraints, list):
        raw_constraints = {
            key: raw_constraints[index]
            for index, key in enumerate(schema_keys)
            if index < len(raw_constraints)
        }
    if not isinstance(raw_constraints, dict):
        raw_constraints = {}
    constraints: dict[str, int] = {}
    for key in schema_keys:
        try:
            constraint = int(raw_constraints.get(key, base["monotone_constraints"][key]))
        except (TypeError, ValueError):
            constraint = 0
        constraints[key] = constraint if constraint in {-1, 0, 1} else 0

    split_method = str(raw.get("split_method", base["split_method"]))
    objective = str(raw.get("objective", base["objective"]))
    raw_metric = raw.get("metric", base["metric"])
    if isinstance(raw_metric, list):
        metric = [str(m) for m in raw_metric if str(m) in METRICS]
    else:
        metric = [str(raw_metric)] if str(raw_metric) in METRICS else base["metric"]
    if not metric:
        metric = base["metric"]
    boosting_type = str(raw.get("boosting_type", base["boosting_type"]))

    return {
        "target_column": target_definition_for_kind(kind)[1],
        "feature_columns": feature_columns,
        "valid_ratio": _config_float(raw.get("valid_ratio"), base["valid_ratio"], 0.05, 0.5),
        "split_method": split_method if split_method in SPLIT_METHODS else base["split_method"],
        "objective": objective if objective in OBJECTIVES else base["objective"],
        "metric": metric,
        "boosting_type": boosting_type if boosting_type in BOOSTING_TYPES else base["boosting_type"],
        "learning_rate": _config_float(raw.get("learning_rate"), base["learning_rate"], 0.001, 1.0),
        "num_boost_round": _config_int(raw.get("num_boost_round"), base["num_boost_round"], 10, 2000),
        "early_stopping_rounds": _config_int(raw.get("early_stopping_rounds"), base["early_stopping_rounds"], 0, 300),
        "num_leaves": _config_int(raw.get("num_leaves"), base["num_leaves"], 2, 255),
        "max_depth": _config_int(raw.get("max_depth"), base["max_depth"], -1, 32),
        "min_data_in_leaf": _config_int(raw.get("min_data_in_leaf"), base["min_data_in_leaf"], 1, 10000),
        "min_sum_hessian_in_leaf": _config_float(raw.get("min_sum_hessian_in_leaf"), base["min_sum_hessian_in_leaf"], 0.0, 10.0),
        "max_delta_step": _config_float(raw.get("max_delta_step"), base["max_delta_step"], 0.0, 100.0),
        "max_bin": _config_int(raw.get("max_bin"), base["max_bin"], 2, 255),
        "min_data_in_bin": _config_int(raw.get("min_data_in_bin"), base["min_data_in_bin"], 1, 100),
        "bin_construct_sample_cnt": _config_int(raw.get("bin_construct_sample_cnt"), base["bin_construct_sample_cnt"], 100, 1_000_000),
        "lambda_l1": _config_float(raw.get("lambda_l1"), base["lambda_l1"], 0.0, 1000.0),
        "lambda_l2": _config_float(raw.get("lambda_l2"), base["lambda_l2"], 0.0, 1000.0),
        "min_gain_to_split": _config_float(raw.get("min_gain_to_split"), base["min_gain_to_split"], 0.0, 10.0),
        "path_smooth": _config_float(raw.get("path_smooth"), base["path_smooth"], 0.0, 100.0),
        "linear_lambda": _config_float(raw.get("linear_lambda"), base["linear_lambda"], 0.0, 1000.0),
        "feature_fraction": _config_float(raw.get("feature_fraction"), base["feature_fraction"], 0.1, 1.0),
        "feature_fraction_bynode": _config_float(raw.get("feature_fraction_bynode"), base["feature_fraction_bynode"], 0.1, 1.0),
        "bagging_fraction": _config_float(raw.get("bagging_fraction"), base["bagging_fraction"], 0.1, 1.0),
        "bagging_freq": _config_int(raw.get("bagging_freq"), base["bagging_freq"], 0, 100),
        "extra_trees": bool(raw.get("extra_trees", base["extra_trees"])),
        "monotone_constraints": constraints,
        "seed": _config_int(raw.get("seed"), base["seed"], 0, 999999),
        "feature_fraction_seed": _config_int(raw.get("feature_fraction_seed"), base["feature_fraction_seed"], 0, 999999),
        "bagging_seed": _config_int(raw.get("bagging_seed"), base["bagging_seed"], 0, 999999),
        "data_random_seed": _config_int(raw.get("data_random_seed"), base["data_random_seed"], 0, 999999),
        "extra_seed": _config_int(raw.get("extra_seed"), base["extra_seed"], 0, 999999),
        "deterministic": bool(raw.get("deterministic", base["deterministic"])),
    }


def training_config_for_model(model, kind: str, schema: list[dict[str, Any]]) -> dict[str, Any]:
    raw = loads_json(model_row_value(model, "training_config_json", "{}"), {})
    return normalize_training_config(raw, kind, schema)


def training_target_column(con) -> str:
    return "target_value"


def insert_training_sample(
    con,
    model_project_id: int,
    sample_time: str,
    values: dict[str, Any],
    suggested_l_h: float | None,
    target_value: float | None,
    source: str,
) -> int:
    target_column = training_target_column(con)
    cur = con.execute(
        f"""
        INSERT INTO model_training_samples(model_project_id,sample_time,values_json,suggested_l_h,{target_column},source,created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (model_project_id, sample_time, dumps_json(values), suggested_l_h, target_value, source, utc_now_iso()),
    )
    return int(cur.lastrowid)


def model_sample_value(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


DUAL_TASK_INPUT_FEATURES = [
    ("inflow_flow", "in_flow_tag_id", "生化池A进水流量过程值", "m3/h"),
    ("inflow_tp", "in_tp_tag_id", "进水总磷过程值", "mg/L"),
    ("inflow_ph", "in_ph_tag_id", "进水在线PH过程值", ""),
    ("outflow_tp", "out_tp_tag_id", "出水总磷过程值", "mg/L"),
    ("high_density_a1_return", "reflux_flow_1_tag_id", "高密A1回流流量过程值", "m3/h"),
    ("high_density_a2_return", "reflux_flow_2_tag_id", "高密A2回流流量过程值", "m3/h"),
    ("orp_east_1", "bio_orp1_tag_id", "生化池A东ORP1过程值", "mV"),
    ("orp_east_2", "bio_orp2_tag_id", "生化池A东ORP2过程值", "mV"),
    ("orp_west_1", "bio_orp3_tag_id", "生化池A西ORP1过程值", "mV"),
    ("orp_west_2", "bio_orp4_tag_id", "生化池A西ORP2过程值", "mV"),
    ("mlss_east", "bio_mlss1_tag_id", "生化池A东MLSS过程值", "mg/L"),
    ("mlss_west", "bio_mlss2_tag_id", "生化池A西MLSS过程值", "mg/L"),
    ("pac_dosage", "pac_flow_tag_id", "PAC1加药流量过程值", "L/h"),
]


def default_model_feature_schema(kind: str | None = None) -> list[dict[str, Any]]:
    kind = kind or MODEL_KIND_TP_OUT_RESPONSE
    if kind not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return [
            {
                "key": key,
                "field": field_name,
                "label": label,
                "unit": default_unit,
                "tag_id": None,
                "tag_code": None,
            }
            for key, field_name, label, default_unit in DUAL_TASK_INPUT_FEATURES
        ]
    return [
        {
            "key": key,
            "field": field_name,
            "label": label,
            "unit": default_unit,
            "tag_id": None,
            "tag_code": None,
        }
        for key, field_name, label, default_unit in MODEL_INPUT_FEATURES
    ]


def current_model_feature_schema(con, dosing_point_id: int | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    kind = kind or MODEL_KIND_TP_OUT_RESPONSE
    if dosing_point_id is None:
        return default_model_feature_schema(kind)
    point = con.execute("SELECT * FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if not point:
        raise HTTPException(404, "投加点不存在")
    if kind not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return model_input_feature_schema_dual(con, point)
    return model_input_feature_schema(con, point)


def model_input_feature_schema(con, point) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    for key, field_name, label, default_unit in MODEL_INPUT_FEATURES:
        tag_id = point[field_name] if field_name else None
        tag = con.execute("SELECT id,tag_code,unit FROM sensor_tags WHERE id=?", (tag_id,)).fetchone() if tag_id else None
        schema.append(
            {
                "key": key,
                "field": field_name,
                "label": label,
                "unit": (tag["unit"] if tag else default_unit) or default_unit,
                "tag_id": int(tag["id"]) if tag else None,
                "tag_code": None,
            }
        )
    return schema


def model_input_feature_schema_dual(con, point) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    for key, field_name, label, default_unit in DUAL_TASK_INPUT_FEATURES:
        tag_id = point[field_name] if field_name else None
        tag = con.execute("SELECT id,tag_code,unit FROM sensor_tags WHERE id=?", (tag_id,)).fetchone() if tag_id else None
        schema.append(
            {
                "key": key,
                "field": field_name,
                "label": label,
                "unit": (tag["unit"] if tag else default_unit) or default_unit,
                "tag_id": int(tag["id"]) if tag else None,
                "tag_code": None,
            }
        )
    return schema


def sync_model_feature_schema(con, model) -> list[dict[str, Any]]:
    dosing_point_id = model_row_value(model, "dosing_point_id")
    schema = current_model_feature_schema(con, int(dosing_point_id) if dosing_point_id is not None else None, model_kind(model))
    if loads_json(model["feature_schema_json"], []) != schema:
        con.execute(
            "UPDATE model_projects SET feature_schema_json=?,updated_at=? WHERE id=?",
            (dumps_json(schema), utc_now_iso(), model["id"]),
        )
    return schema


def _model_csv_float(value: Any, label: str, row_number: int) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError as exc:
        raise HTTPException(422, f"CSV 第 {row_number} 行 {label} 不是有效数值") from exc
    if not math.isfinite(parsed):
        raise HTTPException(422, f"CSV 第 {row_number} 行 {label} 不是有限数值")
    return parsed


def decode_model_sample_csv_payload(payload: ModelSampleImportIn) -> str:
    if payload.csv_base64:
        try:
            raw = base64.b64decode(payload.csv_base64)
        except Exception as exc:
            raise HTTPException(422, "CSV 文件内容不是有效的 base64") from exc
        encodings = [payload.encoding, *MODEL_SAMPLE_CSV_ENCODINGS]
        seen: set[str] = set()
        for encoding in encodings:
            if not encoding or encoding.lower() in seen:
                continue
            seen.add(encoding.lower())
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise HTTPException(422, "CSV 编码无法识别，请另存为 UTF-8 或 GB18030 后再导入")
    if payload.csv_text:
        return payload.csv_text
    raise HTTPException(422, "CSV 内容不能为空")


def _model_csv_header_map(headers: list[str]) -> dict[str, str]:
    return {str(header).strip(): header for header in headers if header}


def _model_csv_column(row: dict[str, Any], headers: dict[str, str], *names: str) -> Any:
    for name in names:
        if name in headers:
            return row.get(headers[name])
    return None


def _model_csv_time_header(headers: dict[str, str]) -> str | None:
    for name in ("时间", "sample_time", "time", "Time", "采样时间", "数据时间"):
        if name in headers:
            return name
    return None


def parse_model_csv_sample_time(value: Any, row_number: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise HTTPException(422, f"CSV 第 {row_number} 行时间不能为空")
    try:
        return datetime.fromisoformat(text).replace(microsecond=0).isoformat()
    except ValueError:
        pass
    for time_format in MODEL_SAMPLE_TIME_FORMATS:
        try:
            return datetime.strptime(text, time_format).replace(microsecond=0).isoformat()
        except ValueError:
            continue
    raise HTTPException(422, f"CSV 第 {row_number} 行时间格式无效")


def target_definition_for_kind(kind: str) -> tuple[str, str, str]:
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return ("DUAL_TASK", "_dual_task", "智能PAC双任务")
    if kind == MODEL_KIND_PAC_FLOW_PREDICT:
        return PAC_FLOW_TARGET
    return TP_FORECAST_TARGET


def target_aliases_for_kind(kind: str) -> tuple[str, ...]:
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return ()
    if kind == MODEL_KIND_PAC_FLOW_PREDICT:
        return PAC_FLOW_TARGET_ALIASES
    return TP_FORECAST_LEGACY_TARGET_ALIASES


def model_artifact_format(kind: str) -> str:
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return "ai_pac_dual_task_v2"
    if kind == MODEL_KIND_PAC_FLOW_PREDICT:
        return "ai_pac_flow_predict_v1"
    return "ai_pac_tp_forecast_v3"


def _model_target_header(headers: dict[str, str], kind: str) -> str | None:
    for name in target_aliases_for_kind(kind):
        if name in headers:
            return name
    return None


def _model_csv_feature_value(row: dict[str, Any], headers: dict[str, str], item: dict[str, Any], row_number: int) -> float | None:
    tag_code = item.get("tag_code")
    label = item.get("label")
    key = item.get("key")
    value = _model_csv_column(row, headers, *(str(name) for name in (tag_code, label, key) if name))
    return _model_csv_float(value, str(tag_code or label or key), row_number)


def import_model_csv_samples(con, model, csv_text: str) -> dict[str, int]:
    kind = model_kind(model)
    if kind not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")

    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return _import_dual_task_csv_samples(con, model, csv_text)

    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff\r\n\t ")))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV 缺少表头")
    schema = sync_model_feature_schema(con, model)
    headers = _model_csv_header_map(reader.fieldnames)
    time_header = _model_csv_time_header(headers)
    if not time_header:
        raise HTTPException(422, "CSV 必须包含“时间”列")
    target_header = _model_target_header(headers, kind)
    if not target_header:
        raise HTTPException(422, f"CSV 缺少标签列：{target_definition_for_kind(kind)[2]}")
    rows_to_insert: list[tuple[int, str, dict[str, Any], float | None, float | None, str]] = []
    for index, row in enumerate(reader, start=2):
        sample_time = parse_model_csv_sample_time(row.get(headers[time_header]), index)
        values: dict[str, float | None] = {}
        for item in schema:
            values[item["key"]] = model_sample_value(_model_csv_feature_value(row, headers, item, index))
        target = model_sample_value(_model_csv_float(row.get(headers[target_header]), target_header, index))
        values[target_definition_for_kind(kind)[1]] = target
        suggested_l_h = target if kind == MODEL_KIND_PAC_FLOW_PREDICT else values.get("PAC_ACTUAL")
        rows_to_insert.append((model["id"], sample_time, values, suggested_l_h, target, "csv_import"))
    if not rows_to_insert:
        raise HTTPException(422, "CSV 中没有可导入的数据行")
    for row in rows_to_insert:
        insert_training_sample(con, *row)
    con.execute("UPDATE model_projects SET updated_at=? WHERE id=?", (utc_now_iso(), model["id"]))
    return {"written": len(rows_to_insert), "generated_suggested": 0, "generated_target": 0}


def _import_dual_task_csv_samples(con, model, csv_text: str) -> dict[str, int]:
    """双任务模型CSV导入：使用 wwtp_ai_engine.DataImporter 进行字段映射和清洗"""
    try:
        df = wwtp_ai_engine.DataImporter.load_from_text(csv_text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(df) < 2:
        raise HTTPException(422, "CSV 中可导入的数据行不足")

    rows_to_insert: list[tuple[int, str, dict[str, Any], float | None, float | None, str]] = []
    for _, row in df.iterrows():
        sample_time = row["timestamp"].replace(microsecond=0).isoformat()
        values: dict[str, float | None] = {}
        for col in wwtp_ai_engine.RAW_COLS:
            if col == "timestamp":
                continue
            values[col] = model_sample_value(row.get(col))
        pac_value = values.get("pac_dosage")
        rows_to_insert.append((model["id"], sample_time, values, pac_value, None, "csv_import"))

    for row in rows_to_insert:
        insert_training_sample(con, *row)
    con.execute("UPDATE model_projects SET updated_at=? WHERE id=?", (utc_now_iso(), model["id"]))
    return {"written": len(rows_to_insert), "generated_suggested": 0, "generated_target": 0}


def train_model_project_artifact(con, model) -> dict[str, Any]:
    kind = model_kind(model)
    if kind == MODEL_KIND_AI_PAC_DUAL_TASK:
        return train_dual_task_artifact(con, model)
    if kind in SUPPORTED_MODEL_KINDS:
        return train_regression_artifact(con, model, kind)
    raise HTTPException(422, "模型类型不支持")


def train_regression_artifact(con, model, kind: str) -> dict[str, Any]:
    target_name, target_key, label = target_definition_for_kind(kind)
    trained = build_regression_booster(con, model, target_key)
    artifact = {
        "format": model_artifact_format(kind),
        "file_name": f"{kind}_model_{model['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.lgb.txt",
        "model_kind": kind,
        "feature_names": trained["feature_keys"],
        "feature_labels": trained["feature_labels"],
        "target": target_name,
        "target_label": label,
        "training_config": trained["training_config"],
        "lightgbm_params": trained["lightgbm_params"],
        "booster_model": trained["booster"].model_to_string(),
        "lightgbm_version": lgb.__version__,
        "trained_at": utc_now_iso(),
    }
    metrics = {
        "samples": trained["metrics"]["samples"],
        "R2": trained["metrics"]["R2"],
        "MAE": trained["metrics"]["MAE"],
        "feature_count": len(trained["feature_keys"]),
        "target": target_name,
        "target_label": label,
        "objective": trained["training_config"]["objective"],
        "num_boost_round": trained["training_config"]["num_boost_round"],
        "best_iteration": trained["booster"].best_iteration,
    }
    now = utc_now_iso()
    con.execute(
        """
        UPDATE model_projects
        SET status='ready',recording_enabled=0,artifact_json=?,metrics_json=?,trained_at=?,updated_at=?
        WHERE id=?
        """,
        (dumps_json(artifact), dumps_json(metrics), now, now, model["id"]),
    )
    return {"artifact": artifact, "metrics": metrics}


def build_regression_booster(con, model, target_key: str) -> dict[str, Any]:
    target_column = training_target_column(con)
    samples = [
        row_to_dict(row)
        for row in con.execute(
            f"SELECT * FROM model_training_samples WHERE model_project_id=? AND {target_column} IS NOT NULL ORDER BY sample_time",
            (model["id"],),
        ).fetchall()
    ]
    if len(samples) < 2:
        raise HTTPException(409, "至少需要 2 条包含目标值的训练样本")
    kind = model_kind(model)
    schema = sync_model_feature_schema(con, model)
    training_config = training_config_for_model(model, kind, schema)
    if training_config["target_column"] != target_key:
        raise HTTPException(422, "训练目标列与模型类型不匹配")
    selected_features = set(training_config["feature_columns"])
    training_schema = [item for item in schema if item["key"] in selected_features]
    usable_samples: list[tuple[dict[str, Any], float]] = []
    for sample in samples:
        values = sample.get("values", {})
        target_value = values.get(target_key)
        if target_value is None:
            target_value = sample.get("target_value")
        try:
            target_number = float(target_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(target_number):
            usable_samples.append((values, target_number))
    if len(usable_samples) < 2:
        raise HTTPException(409, "缺少可用训练标签")

    feature_keys, feature_labels = regression_feature_columns(training_schema, usable_samples)
    matrix = regression_matrix(feature_keys, usable_samples)
    target = np.array([target_value for _, target_value in usable_samples], dtype=float)
    booster, metrics, lightgbm_params = train_lgb_regression(matrix, target, feature_keys, training_config)
    metrics.update({"samples": len(usable_samples), "feature_count": len(feature_keys)})
    return {
        "booster": booster,
        "metrics": metrics,
        "feature_keys": feature_keys,
        "feature_labels": feature_labels,
        "training_config": training_config,
        "lightgbm_params": lightgbm_params,
    }


def regression_feature_columns(schema: list[dict[str, Any]], usable_samples: list[tuple[dict[str, Any], float]]) -> tuple[list[str], dict[str, str]]:
    feature_keys: list[str] = []
    feature_labels: dict[str, str] = {}
    for item in schema:
        values = [row_values.get(item["key"]) for row_values, _ in usable_samples]
        numeric = [float(value) for value in values if value is not None]
        if len(numeric) >= 2 and max(numeric) - min(numeric) > 1e-9:
            feature_keys.append(item["key"])
            feature_labels[item["key"]] = item["label"]
    if not feature_keys:
        raise HTTPException(409, "训练样本缺少可变化的数据来源，请继续采集覆盖不同工况的数据")
    return feature_keys, feature_labels


def regression_matrix(feature_keys: list[str], usable_samples: list[tuple[dict[str, Any], float]]) -> np.ndarray:
    return np.array(
        [[float(values.get(key)) if values.get(key) is not None else np.nan for key in feature_keys] for values, _ in usable_samples],
        dtype=float,
    )


def monotone_constraints_for_features(feature_keys: list[str]) -> list[int]:
    return [0 for _key in feature_keys]


def configured_monotone_constraints(feature_keys: list[str], training_config: dict[str, Any]) -> list[int]:
    constraints = training_config.get("monotone_constraints", {})
    if not isinstance(constraints, dict):
        return monotone_constraints_for_features(feature_keys)
    values: list[int] = []
    for key in feature_keys:
        try:
            constraint = int(constraints.get(key, 0))
        except (TypeError, ValueError):
            constraint = 0
        values.append(constraint if constraint in {-1, 0, 1} else 0)
    return values


def train_valid_split_indices(size: int, training_config: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    valid_size = max(1, int(round(size * float(training_config["valid_ratio"]))))
    valid_size = min(valid_size, size - 1)
    if training_config["split_method"] == "random":
        rng = np.random.default_rng(20260630)
        indices = rng.permutation(size)
        valid_indices = np.sort(indices[-valid_size:])
        train_indices = np.sort(indices[:-valid_size])
        return train_indices, valid_indices
    train_size = size - valid_size
    return np.arange(train_size), np.arange(train_size, size)


def train_lgb_regression(
    matrix: np.ndarray,
    target: np.ndarray,
    feature_keys: list[str],
    training_config: dict[str, Any],
) -> tuple[lgb.Booster, dict[str, Any], dict[str, Any]]:
    train_indices, valid_indices = train_valid_split_indices(len(target), training_config)
    train_matrix, train_target = matrix[train_indices], target[train_indices]
    valid_matrix, valid_target = matrix[valid_indices], target[valid_indices]
    feature_names = [f"f{i}" for i in range(matrix.shape[1])] if matrix.shape[1] else None
    train_dataset = lgb.Dataset(train_matrix, label=train_target, feature_name=feature_names, free_raw_data=False)
    valid_dataset = lgb.Dataset(valid_matrix, label=valid_target, reference=train_dataset, feature_name=feature_names, free_raw_data=False)
    # metric 转换为 LightGBM 支持的列表
    metric_raw = training_config.get("metric", "rmse")
    metric_list: list[str]
    if isinstance(metric_raw, list):
        metric_list = [str(m) for m in metric_raw]
    else:
        metric_list = [str(metric_raw)]

    params = {
        "objective": training_config["objective"],
        "metric": metric_list,
        "boosting": training_config["boosting_type"],
        "learning_rate": training_config["learning_rate"],
        "num_leaves": training_config["num_leaves"],
        "max_depth": training_config["max_depth"],
        "min_data_in_leaf": training_config["min_data_in_leaf"],
        "min_sum_hessian_in_leaf": training_config["min_sum_hessian_in_leaf"],
        "max_delta_step": training_config["max_delta_step"],
        "max_bin": training_config["max_bin"],
        "min_data_in_bin": training_config["min_data_in_bin"],
        "bin_construct_sample_cnt": training_config["bin_construct_sample_cnt"],
        "feature_pre_filter": False,
        "monotone_constraints": configured_monotone_constraints(feature_keys, training_config),
        "monotone_constraints_method": "advanced",
        "lambda_l1": training_config["lambda_l1"],
        "lambda_l2": training_config["lambda_l2"],
        "min_gain_to_split": training_config["min_gain_to_split"],
        "path_smooth": training_config["path_smooth"],
        "linear_lambda": training_config["linear_lambda"],
        "feature_fraction": training_config["feature_fraction"],
        "feature_fraction_bynode": training_config["feature_fraction_bynode"],
        "bagging_fraction": training_config["bagging_fraction"],
        "bagging_freq": training_config["bagging_freq"],
        "extra_trees": training_config["extra_trees"],
        "verbosity": -1,
        "seed": training_config["seed"],
        "feature_fraction_seed": training_config["feature_fraction_seed"],
        "bagging_seed": training_config["bagging_seed"],
        "data_random_seed": training_config["data_random_seed"],
        "extra_seed": training_config["extra_seed"],
        "deterministic": training_config["deterministic"],
    }
    callbacks = [lgb.log_evaluation(50)]
    if training_config["early_stopping_rounds"] > 0:
        callbacks.insert(0, lgb.early_stopping(training_config["early_stopping_rounds"]))
    booster = lgb.train(
        params,
        train_dataset,
        valid_sets=[train_dataset, valid_dataset],
        valid_names=["train", "valid"],
        num_boost_round=training_config["num_boost_round"],
        callbacks=callbacks,
    )
    num_iteration = booster.best_iteration if booster.best_iteration else None
    predictions = booster.predict(matrix, num_iteration=num_iteration)
    target_mean = float(np.mean(target))
    sse = float(np.sum((target - predictions) ** 2))
    sst = float(np.sum((target - target_mean) ** 2))
    r2 = 1.0 if sst < 1e-12 else 1 - sse / sst
    mae = float(np.mean(np.abs(target - predictions)))
    return booster, {"R2": round(r2, 4), "MAE": round(mae, 4)}, params


def train_dual_task_artifact(con, model) -> dict[str, Any]:
    """训练双任务模型artifact：同时训练PAC预测和TP变化量预测"""
    import tempfile
    import shutil

    raw = loads_json(model_row_value(model, "training_config_json", "{}"), {})
    training_config = wwtp_ai_engine.normalize_training_config(raw)

    sample_interval_minutes = float(
        model_row_value(model, "sample_interval_minutes", 0) or 0
    )

    hrt_minutes: float | None = None
    config_hrt = raw.get("tp_hrt_minutes") if isinstance(raw, dict) else None
    if config_hrt is not None and config_hrt > 0:
        hrt_minutes = float(config_hrt)

    samples = [
        row_to_dict(row)
        for row in con.execute(
            "SELECT * FROM model_training_samples WHERE model_project_id=? ORDER BY sample_time",
            (model["id"],),
        ).fetchall()
    ]
    if len(samples) < 40:
        raise HTTPException(409, "双任务模型至少需要 40 条训练样本")

    df = wwtp_ai_engine.samples_to_dataframe(samples)
    if len(df) < 40:
        raise HTTPException(409, "有效样本不足，请检查数据质量")

    datasets = wwtp_ai_engine.FeatureEngineer.build_features(
        df,
        for_training=True,
        hrt_minutes=hrt_minutes,
        sample_interval_minutes=sample_interval_minutes,
    )
    if len(datasets["task1"]) < 20 or len(datasets["task2"]) < 20:
        raise HTTPException(409, "特征工程后可用样本不足")

    temp_dir = tempfile.mkdtemp(prefix="wwtp_dual_task_")
    try:
        trainer = wwtp_ai_engine.ModelTrainer(config=training_config)
        result = trainer.train_both(datasets, output_dir=temp_dir)

        with open(result["model1_path"], "r", encoding="utf-8") as f:
            booster1_str = f.read()
        with open(result["model2_path"], "r", encoding="utf-8") as f:
            booster2_str = f.read()

        artifact = {
            "format": model_artifact_format(MODEL_KIND_AI_PAC_DUAL_TASK),
            "model_kind": MODEL_KIND_AI_PAC_DUAL_TASK,
            "booster_models": {
                "task1": booster1_str,
                "task2": booster2_str,
            },
            "feature_names": {
                "task1": result["model1_features"],
                "task2": result["model2_features"],
            },
            "training_config": training_config,
            "trained_at": utc_now_iso(),
            "lightgbm_version": lgb.__version__,
            "label_mode": datasets.get("label_mode", "legacy"),
            "used_lag_rows": datasets.get("used_lag_rows"),
            "hrt_minutes": datasets.get("hrt_minutes"),
            "sample_interval_minutes": datasets.get("sample_interval_minutes"),
        }

        metrics = {
            "task1": {
                "feature_count": len(result["model1_features"]),
                "samples": len(datasets["task1"]),
                "eval": result.get("task1_metrics", {}),
            },
            "task2": {
                "feature_count": len(result["model2_features"]),
                "samples": len(datasets["task2"]),
                "eval": result.get("task2_metrics", {}),
                "label_mode": datasets.get("label_mode", "legacy"),
                "used_lag_rows": datasets.get("used_lag_rows"),
                "hrt_minutes": datasets.get("hrt_minutes"),
            },
        }

        now = utc_now_iso()
        con.execute(
            """
            UPDATE model_projects
            SET status='ready',recording_enabled=0,artifact_json=?,metrics_json=?,trained_at=?,updated_at=?
            WHERE id=?
            """,
            (dumps_json(artifact), dumps_json(metrics), now, now, model["id"]),
        )
        return {"artifact": artifact, "metrics": metrics}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def export_dual_task_features(con, model) -> bytes:
    """导出双任务模型处理后的特征数据，返回 ZIP 字节（内含 task1_features.csv 和 task2_features.csv）"""
    import zipfile
    from io import BytesIO

    sample_interval_minutes = float(
        model_row_value(model, "sample_interval_minutes", 0) or 0
    )

    raw = loads_json(model_row_value(model, "training_config_json", "{}"), {})
    hrt_minutes: float | None = None
    config_hrt = raw.get("tp_hrt_minutes") if isinstance(raw, dict) else None
    if config_hrt is not None and config_hrt > 0:
        hrt_minutes = float(config_hrt)

    samples = [
        row_to_dict(row)
        for row in con.execute(
            "SELECT * FROM model_training_samples WHERE model_project_id=? ORDER BY sample_time",
            (model["id"],),
        ).fetchall()
    ]
    if len(samples) < 2:
        raise HTTPException(409, "样本不足，无法导出特征")

    df = wwtp_ai_engine.samples_to_dataframe(samples)
    datasets = wwtp_ai_engine.FeatureEngineer.build_features(
        df,
        for_training=True,
        hrt_minutes=hrt_minutes,
        sample_interval_minutes=sample_interval_minutes,
    )

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for task_name in ("task1", "task2"):
            task_df = datasets.get(task_name)
            if task_df is not None and len(task_df) > 0:
                csv_buf = io.StringIO()
                task_df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
                zf.writestr(f"{task_name}_features.csv", csv_buf.getvalue())
    buf.seek(0)
    return buf.getvalue()
