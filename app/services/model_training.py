from __future__ import annotations

import base64
import csv
import io
import math
import asyncio
from datetime import datetime
from typing import Any

import lightgbm as lgb
import numpy as np
from fastapi import HTTPException

from app.api.common import row_to_dict
from app.database import db_session, dumps_json, loads_json, utc_now_iso
from app.schemas import ModelSampleImportIn
from app.services.recommendation import latest_data_for_point


MODEL_SAMPLE_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
MODEL_SAMPLE_TIME_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)
MODEL_KIND_TP_OUT_RESPONSE = "tp_out_response"
MODEL_KIND_PAC_FLOW_PREDICT = "pac_flow_predict"
SUPPORTED_MODEL_KINDS = {MODEL_KIND_TP_OUT_RESPONSE, MODEL_KIND_PAC_FLOW_PREDICT}
TP_FORECAST_TARGET = ("TP_OUT_NEXT", "_training_target_tp_out_next", "下一次出水TP检测数据")
PAC_FLOW_TARGET = ("PAC_ACTUAL", "_training_target_pac_actual", "实际加药流量")
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
SAMPLE_WEIGHT_RULES = {"none", "high_target"}


def model_row_value(model, key: str, default: Any = None) -> Any:
    if isinstance(model, dict):
        return model.get(key, default)
    return model[key] if key in model.keys() else default


def model_kind(model) -> str:
    return model_row_value(model, "model_kind", MODEL_KIND_TP_OUT_RESPONSE) or MODEL_KIND_TP_OUT_RESPONSE


def default_training_config(kind: str, schema: list[dict[str, Any]]) -> dict[str, Any]:
    _target_name, target_key, _target_label = target_definition_for_kind(kind)
    feature_columns = [str(item["key"]) for item in schema]
    return {
        "target_column": target_key,
        "feature_columns": feature_columns,
        "prediction_step": 1,
        "valid_ratio": 0.2,
        "split_method": "time",
        "objective": "huber",
        "learning_rate": 0.03,
        "num_boost_round": 500,
        "early_stopping_rounds": 50,
        "num_leaves": 7,
        "max_depth": 3,
        "min_data_in_leaf": 20,
        "lambda_l2": 3.0,
        "feature_fraction": 1.0,
        "bagging_fraction": 0.85,
        "bagging_freq": 1,
        "monotone_constraints": {key: 0 for key in feature_columns},
        "sample_weight_rule": "none",
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
    sample_weight_rule = str(raw.get("sample_weight_rule", base["sample_weight_rule"]))
    return {
        "target_column": target_definition_for_kind(kind)[1],
        "feature_columns": feature_columns,
        "prediction_step": _config_int(raw.get("prediction_step"), base["prediction_step"], 0, 24),
        "valid_ratio": _config_float(raw.get("valid_ratio"), base["valid_ratio"], 0.05, 0.5),
        "split_method": split_method if split_method in SPLIT_METHODS else base["split_method"],
        "objective": objective if objective in OBJECTIVES else base["objective"],
        "learning_rate": _config_float(raw.get("learning_rate"), base["learning_rate"], 0.001, 1.0),
        "num_boost_round": _config_int(raw.get("num_boost_round"), base["num_boost_round"], 10, 2000),
        "early_stopping_rounds": _config_int(raw.get("early_stopping_rounds"), base["early_stopping_rounds"], 0, 300),
        "num_leaves": _config_int(raw.get("num_leaves"), base["num_leaves"], 2, 255),
        "max_depth": _config_int(raw.get("max_depth"), base["max_depth"], -1, 32),
        "min_data_in_leaf": _config_int(raw.get("min_data_in_leaf"), base["min_data_in_leaf"], 1, 10000),
        "lambda_l2": _config_float(raw.get("lambda_l2"), base["lambda_l2"], 0.0, 1000.0),
        "feature_fraction": _config_float(raw.get("feature_fraction"), base["feature_fraction"], 0.1, 1.0),
        "bagging_fraction": _config_float(raw.get("bagging_fraction"), base["bagging_fraction"], 0.1, 1.0),
        "bagging_freq": _config_int(raw.get("bagging_freq"), base["bagging_freq"], 0, 100),
        "monotone_constraints": constraints,
        "sample_weight_rule": sample_weight_rule if sample_weight_rule in SAMPLE_WEIGHT_RULES else base["sample_weight_rule"],
    }


def training_config_for_model(model, kind: str, schema: list[dict[str, Any]]) -> dict[str, Any]:
    raw = loads_json(model_row_value(model, "training_config_json", "{}"), {})
    return normalize_training_config(raw, kind, schema)


def training_target_column(con) -> str:
    columns = {row["name"] for row in con.execute("PRAGMA table_info(model_training_samples)").fetchall()}
    return "target_value" if "target_value" in columns else "k_ai"


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


def default_model_feature_schema(kind: str | None = None) -> list[dict[str, Any]]:
    kind = kind or MODEL_KIND_TP_OUT_RESPONSE
    if kind not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")
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


def sync_model_feature_schema(con, model) -> list[dict[str, Any]]:
    dosing_point_id = model_row_value(model, "dosing_point_id")
    schema = current_model_feature_schema(con, int(dosing_point_id) if dosing_point_id is not None else None, model_kind(model))
    if loads_json(model["feature_schema_json"], []) != schema:
        con.execute(
            "UPDATE model_projects SET feature_schema_json=?,updated_at=? WHERE id=?",
            (dumps_json(schema), utc_now_iso(), model["id"]),
        )
    return schema


def record_model_project_sample(con, model) -> dict[str, Any]:
    kind = model_kind(model)
    if kind not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")
    dosing_point_id = model_row_value(model, "dosing_point_id")
    if dosing_point_id is None:
        raise HTTPException(422, "模型未绑定投加点，不能实时记录；请导入 CSV 样本")
    now = datetime.now().replace(microsecond=0)
    schema = sync_model_feature_schema(con, model)
    live_data = latest_data_for_point(con, int(dosing_point_id), now)
    values: dict[str, float | None] = {}
    for item in schema:
        point = live_data.get(item["key"])
        values[item["key"]] = model_sample_value(point.value if point else None)
    current_target = model_realtime_target_value(kind, live_data)
    target_key = target_definition_for_kind(kind)[1]
    target_value = current_target
    if kind == MODEL_KIND_TP_OUT_RESPONSE:
        training_config = training_config_for_model(model, kind, schema)
        prediction_step = int(training_config["prediction_step"])
        if prediction_step == 0:
            values[target_key] = current_target
        else:
            target_value = None
    else:
        values[target_key] = current_target
    suggested_l_h = values.get("PAC_ACTUAL") if kind == MODEL_KIND_TP_OUT_RESPONSE else target_value
    sample_id = insert_training_sample(con, int(model["id"]), now.isoformat(), values, suggested_l_h, target_value, "realtime_record")
    backfilled = 0
    if kind == MODEL_KIND_TP_OUT_RESPONSE and current_target is not None:
        backfilled = backfill_tp_response_target(con, model, current_target, now)
    con.execute(
        """
        UPDATE model_projects
        SET last_record_at=?,updated_at=?
        WHERE id=?
        """,
        (now.isoformat(), now.isoformat(), model["id"]),
    )
    return {"sample_id": sample_id, "sample_time": now.isoformat(), "target_value": target_value, "backfilled": backfilled}


def model_realtime_target_value(kind: str, live_data: dict[str, Any]) -> float | None:
    target_source = "PAC_ACTUAL" if kind == MODEL_KIND_PAC_FLOW_PREDICT else "TP_OUT"
    point = live_data.get(target_source)
    return model_sample_value(point.value if point else None)


def backfill_tp_response_target(con, model, target_value: float, now: datetime) -> int:
    schema = sync_model_feature_schema(con, model)
    training_config = training_config_for_model(model, MODEL_KIND_TP_OUT_RESPONSE, schema)
    prediction_step = int(training_config["prediction_step"])
    if prediction_step <= 0:
        return 0
    target_column = training_target_column(con)
    target_key = target_definition_for_kind(MODEL_KIND_TP_OUT_RESPONSE)[1]
    rows = con.execute(
        f"""
        SELECT id,values_json
        FROM model_training_samples
        WHERE model_project_id=? AND source='realtime_record' AND sample_time<?
        ORDER BY sample_time DESC,id DESC
        LIMIT ?
        """,
        (model["id"], now.isoformat(), prediction_step),
    ).fetchall()
    if len(rows) < prediction_step:
        return 0
    row = rows[-1]
    values = loads_json(row["values_json"], {})
    values[target_key] = target_value
    cur = con.execute(
        f"""
        UPDATE model_training_samples
        SET values_json=?,{target_column}=?
        WHERE id=? AND {target_column} IS NULL
        """,
        (dumps_json(values), target_value, row["id"]),
    )
    return int(cur.rowcount or 0)


def parse_model_record_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def due_recording_models(con) -> list[Any]:
    rows = con.execute(
        """
        SELECT *
        FROM model_projects
        WHERE recording_enabled=1
          AND model_kind IN ('tp_out_response','pac_flow_predict')
        ORDER BY id
        """
    ).fetchall()
    now = datetime.now()
    due = []
    for row in rows:
        last_record = parse_model_record_time(row["last_record_at"])
        interval_seconds = int(row["sample_interval_minutes"]) * 60
        if last_record is None or (now - last_record).total_seconds() >= interval_seconds:
            due.append(row)
    return due


def record_due_model_samples(con) -> dict[str, Any]:
    recorded = 0
    errors: list[dict[str, Any]] = []
    for model in due_recording_models(con):
        try:
            record_model_project_sample(con, model)
            recorded += 1
        except Exception as exc:
            errors.append({"model_id": model["id"], "message": str(exc)})
    return {"recorded": recorded, "errors": errors}


async def model_recording_loop() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            with db_session() as con:
                record_due_model_samples(con)
        except asyncio.CancelledError:
            raise
        except Exception:
            continue


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
    if kind == MODEL_KIND_PAC_FLOW_PREDICT:
        return PAC_FLOW_TARGET
    return TP_FORECAST_TARGET


def target_aliases_for_kind(kind: str) -> tuple[str, ...]:
    if kind == MODEL_KIND_PAC_FLOW_PREDICT:
        return PAC_FLOW_TARGET_ALIASES
    return TP_FORECAST_LEGACY_TARGET_ALIASES


def model_artifact_format(kind: str) -> str:
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
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff\r\n\t ")))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV 缺少表头")
    kind = model_kind(model)
    schema = sync_model_feature_schema(con, model)
    headers = _model_csv_header_map(reader.fieldnames)
    time_header = _model_csv_time_header(headers)
    if not time_header:
        raise HTTPException(422, "CSV 必须包含“时间”列")
    if kind not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")
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


def train_model_project_artifact(con, model) -> dict[str, Any]:
    kind = model_kind(model)
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
            target_value = sample.get("target_value", sample.get("k_ai"))
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
    sample_weight = regression_sample_weight(target, training_config["sample_weight_rule"])
    booster, metrics, lightgbm_params = train_lgb_regression(matrix, target, feature_keys, training_config, sample_weight)
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


def regression_sample_weight(target: np.ndarray, rule: str) -> np.ndarray | None:
    if rule != "high_target" or len(target) < 4:
        return None
    threshold = float(np.quantile(target, 0.75))
    weights = np.ones(len(target), dtype=float)
    weights[target >= threshold] = 2.0
    return weights


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
    sample_weight: np.ndarray | None,
) -> tuple[lgb.Booster, dict[str, Any], dict[str, Any]]:
    train_indices, valid_indices = train_valid_split_indices(len(target), training_config)
    train_matrix, train_target = matrix[train_indices], target[train_indices]
    valid_matrix, valid_target = matrix[valid_indices], target[valid_indices]
    train_weight = sample_weight[train_indices] if sample_weight is not None else None
    valid_weight = sample_weight[valid_indices] if sample_weight is not None else None
    feature_names = [f"f{i}" for i in range(matrix.shape[1])] if matrix.shape[1] else None
    train_dataset = lgb.Dataset(train_matrix, label=train_target, weight=train_weight, feature_name=feature_names, free_raw_data=False)
    valid_dataset = lgb.Dataset(valid_matrix, label=valid_target, weight=valid_weight, reference=train_dataset, feature_name=feature_names, free_raw_data=False)
    params = {
        "objective": training_config["objective"],
        "metric": ["l1", "l2"],
        "learning_rate": training_config["learning_rate"],
        "num_leaves": training_config["num_leaves"],
        "max_depth": training_config["max_depth"],
        "min_data_in_leaf": training_config["min_data_in_leaf"],
        "min_data_in_bin": 3,
        "feature_pre_filter": False,
        "monotone_constraints": configured_monotone_constraints(feature_keys, training_config),
        "monotone_constraints_method": "advanced",
        "lambda_l1": 0.01,
        "lambda_l2": training_config["lambda_l2"],
        "min_gain_to_split": 0.0005,
        "feature_fraction": training_config["feature_fraction"],
        "bagging_fraction": training_config["bagging_fraction"],
        "bagging_freq": training_config["bagging_freq"],
        "verbosity": -1,
        "seed": 20260630,
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
