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
from app.database import dumps_json, loads_json, utc_now_iso
from app.schemas import ModelSampleImportIn


MODEL_SAMPLE_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
MODEL_KIND_TP_OUT_RESPONSE = "tp_out_response"
TP_FORECAST_TARGETS = [
    ("TP_OUT_30", "_training_target_tp_out_30", "未来30分钟出水TP", "30"),
    ("TP_OUT_60", "_training_target_tp_out_60", "未来60分钟出水TP", "60"),
    ("TP_OUT_120", "_training_target_tp_out_120", "未来120分钟出水TP", "120"),
]
TP_FORECAST_FEATURES = [
    ("Q", None, "参考流量", "m3/h"),
    ("TP_BEFORE", "in_tp_tag_id", "进水总磷", "mg/L"),
    ("PH", "in_ph_tag_id", "进水PH", ""),
    ("OUT_Q", "out_flow_tag_id", "出水流量", "m3/h"),
    ("TP_OUT", "out_tp_tag_id", "当前出水总磷", "mg/L"),
    ("REFLUX_Q1", "reflux_flow_1_tag_id", "高密A1回流流量", "m3/h"),
    ("REFLUX_Q2", "reflux_flow_2_tag_id", "高密A2回流流量", "m3/h"),
    ("BIO_ORP1", "bio_orp1_tag_id", "生化池A东ORP1", "mV"),
    ("BIO_ORP2", "bio_orp2_tag_id", "生化池A东ORP2", "mV"),
    ("BIO_ORP3", "bio_orp3_tag_id", "生化池A西ORP1", "mV"),
    ("BIO_ORP4", "bio_orp4_tag_id", "生化池A西ORP2", "mV"),
    ("BIO_DO1", "bio_do1_tag_id", "生化池A东DO", "mg/L"),
    ("BIO_DO2", "bio_do2_tag_id", "生化池A西DO", "mg/L"),
    ("BIO_MLSS1", "bio_mlss1_tag_id", "生化池A东MLSS", "mg/L"),
    ("BIO_MLSS2", "bio_mlss2_tag_id", "生化池A西MLSS", "mg/L"),
    ("PAC_ACTUAL", "pac_flow_tag_id", "实际加药流量", "L/h"),
]


def model_kind(model) -> str:
    return model["model_kind"] if "model_kind" in model.keys() and model["model_kind"] else MODEL_KIND_TP_OUT_RESPONSE


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


def current_model_feature_schema(con, dosing_point_id: int, kind: str | None = None) -> list[dict[str, Any]]:
    point = con.execute("SELECT * FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if not point:
        raise HTTPException(404, "投加点不存在")
    if kind != MODEL_KIND_TP_OUT_RESPONSE:
        raise HTTPException(410, "投加量预测模型已删除，请使用出水TP预测模型")
    return tp_forecast_feature_schema(con, point)


def tp_forecast_feature_schema(con, point) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    for key, field_name, label, default_unit in TP_FORECAST_FEATURES:
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
    schema = current_model_feature_schema(con, int(model["dosing_point_id"]), model_kind(model))
    if loads_json(model["feature_schema_json"], []) != schema:
        con.execute(
            "UPDATE model_projects SET feature_schema_json=?,updated_at=? WHERE id=?",
            (dumps_json(schema), utc_now_iso(), model["id"]),
        )
    return schema


def record_model_project_sample(con, model) -> dict[str, Any]:
    raise HTTPException(410, "模型实时记录功能已停用，请通过 CSV 表格导入训练样本")


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


def _tp_forecast_target_headers(headers: dict[str, str]) -> dict[str, str]:
    aliases = {
        "_training_target_tp_out_30": ("未来30分钟出水TP", "TP_OUT_30", "target_tp_out_30", "_training_target_tp_out_30"),
        "_training_target_tp_out_60": ("未来60分钟出水TP", "TP_OUT_60", "target_tp_out_60", "_training_target_tp_out_60", "未来出水TP", "目标出水TP"),
        "_training_target_tp_out_120": ("未来120分钟出水TP", "TP_OUT_120", "target_tp_out_120", "_training_target_tp_out_120"),
    }
    result: dict[str, str] = {}
    for key, names in aliases.items():
        for name in names:
            if name in headers:
                result[key] = name
                break
    return result


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
    if kind != MODEL_KIND_TP_OUT_RESPONSE:
        raise HTTPException(410, "投加量预测模型已删除，请使用出水TP预测模型")
    target_headers = _tp_forecast_target_headers(headers)
    missing = [label for _name, key, label, _horizon in TP_FORECAST_TARGETS if key not in target_headers]
    if missing:
        raise HTTPException(422, f"CSV 缺少标签列：{'、'.join(missing)}")
    rows_to_insert: list[tuple[int, str, dict[str, Any], float | None, float | None, str]] = []
    for index, row in enumerate(reader, start=2):
        sample_time = str(row.get(headers[time_header]) or "").strip()
        try:
            sample_time = datetime.fromisoformat(sample_time).replace(microsecond=0).isoformat()
        except ValueError as exc:
            raise HTTPException(422, f"CSV 第 {index} 行时间格式无效") from exc
        values: dict[str, float | None] = {}
        for item in schema:
            values[item["key"]] = model_sample_value(_model_csv_feature_value(row, headers, item, index))
        target_values = {
            key: model_sample_value(_model_csv_float(row.get(headers[target_headers[key]]), target_headers[key], index))
            for _name, key, _label, _horizon in TP_FORECAST_TARGETS
        }
        values.update(target_values)
        target = target_values["_training_target_tp_out_60"]
        rows_to_insert.append((model["id"], sample_time, values, values.get("PAC_ACTUAL"), target, "csv_import"))
    if not rows_to_insert:
        raise HTTPException(422, "CSV 中没有可导入的数据行")
    for row in rows_to_insert:
        insert_training_sample(con, *row)
    con.execute("UPDATE model_projects SET updated_at=? WHERE id=?", (utc_now_iso(), model["id"]))
    return {"written": len(rows_to_insert), "generated_suggested": 0, "generated_target": 0}


def train_model_project_artifact(con, model) -> dict[str, Any]:
    kind = model_kind(model)
    if kind == MODEL_KIND_TP_OUT_RESPONSE:
        return train_tp_forecast_artifact(con, model)
    raise HTTPException(410, "投加量预测模型已删除，请使用出水TP预测模型")


def train_tp_forecast_artifact(con, model) -> dict[str, Any]:
    trained_targets: dict[str, Any] = {}
    metrics_by_target: dict[str, Any] = {}
    feature_names: list[str] | None = None
    feature_labels: dict[str, str] | None = None
    for target_name, target_key, label, horizon in TP_FORECAST_TARGETS:
        trained = build_regression_booster(con, model, target_key)
        trained_targets[horizon] = {
            "target": target_name,
            "label": label,
            "booster_model": trained["booster"].model_to_string(),
        }
        metrics_by_target[horizon] = trained["metrics"]
        if feature_names is None:
            feature_names = trained["feature_keys"]
            feature_labels = trained["feature_labels"]
        elif feature_names != trained["feature_keys"]:
            raise HTTPException(409, "三个预测标签可用特征不一致，请检查 CSV 数据完整性")
    artifact = {
        "format": "ai_pac_tp_forecast_v2",
        "file_name": f"tp_forecast_model_{model['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.lgb.txt",
        "feature_names": feature_names or [],
        "feature_labels": feature_labels or {},
        "booster_models": trained_targets,
        "lightgbm_version": lgb.__version__,
        "trained_at": utc_now_iso(),
        "target": "TP_OUT_30_60_120",
    }
    mae_values = [item["MAE"] for item in metrics_by_target.values()]
    r2_values = [item["R2"] for item in metrics_by_target.values()]
    sample_values = [item["samples"] for item in metrics_by_target.values()]
    metrics = {
        "samples": min(sample_values),
        "R2": round(float(np.mean(r2_values)), 4),
        "MAE": round(float(np.mean(mae_values)), 4),
        "feature_count": len(feature_names or []),
        "target": "TP_OUT_30_60_120",
        "targets": metrics_by_target,
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
    schema = sync_model_feature_schema(con, model)
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

    feature_keys, feature_labels = regression_feature_columns(schema, usable_samples)
    matrix = regression_matrix(feature_keys, usable_samples)
    target = np.array([target_value for _, target_value in usable_samples], dtype=float)
    booster, metrics = train_lgb_regression(matrix, target)
    metrics.update({"samples": len(usable_samples), "feature_count": len(feature_keys)})
    return {"booster": booster, "metrics": metrics, "feature_keys": feature_keys, "feature_labels": feature_labels}


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


def train_lgb_regression(matrix: np.ndarray, target: np.ndarray) -> tuple[lgb.Booster, dict[str, Any]]:
    dataset = lgb.Dataset(matrix, label=target, feature_name=[f"f{i}" for i in range(matrix.shape[1])] if matrix.shape[1] else None, free_raw_data=False)
    booster = lgb.train(
        {
            "objective": "regression_l2",
            "metric": "l2",
            "learning_rate": 0.05,
            "num_leaves": 7,
            "min_data_in_leaf": 2,
            "min_data_in_bin": 1,
            "feature_pre_filter": False,
            "verbosity": -1,
            "seed": 20260630,
        },
        dataset,
        num_boost_round=80,
    )
    predictions = booster.predict(matrix)
    target_mean = float(np.mean(target))
    sse = float(np.sum((target - predictions) ** 2))
    sst = float(np.sum((target - target_mean) ** 2))
    r2 = 1.0 if sst < 1e-12 else 1 - sse / sst
    mae = float(np.mean(np.abs(target - predictions)))
    return booster, {"R2": round(r2, 4), "MAE": round(mae, 4)}
