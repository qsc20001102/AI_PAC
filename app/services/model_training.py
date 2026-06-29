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
from app.services.recommendation import calculate_for_point


MODEL_SAMPLE_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")


def record_model_project_sample(con, model) -> dict[str, Any]:
    now = datetime.now().replace(microsecond=0)
    result = calculate_for_point(con, int(model["dosing_point_id"]), now=now, save=False, source="model_recording")
    schema = loads_json(model["feature_schema_json"], [])
    values: dict[str, float | None] = {}
    for item in schema:
        point = result["data"].get(item["key"])
        values[item["key"]] = point.get("value") if point else None
    actual = result["data"].get("PAC_ACTUAL")
    denominator = float(result.get("base_l_h") or 0) * float(result.get("k_feedback") or 0)
    if actual and actual.get("value") is not None and denominator > 1e-6:
        values["_training_target_k_ai"] = round(float(actual["value"]) / denominator, 6)
    else:
        values["_training_target_k_ai"] = None
    cur = con.execute(
        """
        INSERT INTO model_training_samples(model_project_id,sample_time,values_json,suggested_l_h,k_ai,source,created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            model["id"],
            now.isoformat(),
            dumps_json(values),
            result.get("final_l_h"),
            result.get("k_ai"),
            "realtime",
            utc_now_iso(),
        ),
    )
    con.execute("UPDATE model_projects SET last_record_at=?,updated_at=? WHERE id=?", (now.isoformat(), utc_now_iso(), model["id"]))
    row = con.execute("SELECT * FROM model_training_samples WHERE id=?", (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


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


def _model_csv_suggestion_header(headers: dict[str, str]) -> str | None:
    for name in ("建议值(L/h)", "建议值 L/h", "建议值L/h", "建议值", "系统输出建议值", "suggested_l_h", "suggestion", "PAC建议"):
        if name in headers:
            return name
    return None


def _model_csv_k_ai_header(headers: dict[str, str]) -> str | None:
    for name in ("K_AI", "k_ai", "KAI", "kAI", "AI系数", "K_AI系数"):
        if name in headers:
            return name
    return None


def _model_csv_time_header(headers: dict[str, str]) -> str | None:
    for name in ("时间", "sample_time", "time", "Time", "采样时间", "数据时间"):
        if name in headers:
            return name
    return None


def _model_csv_feature_value(row: dict[str, Any], headers: dict[str, str], item: dict[str, Any], row_number: int) -> float | None:
    tag_code = item.get("tag_code")
    label = item.get("label")
    key = item.get("key")
    value = _model_csv_column(row, headers, *(str(name) for name in (tag_code, label, key) if name))
    return _model_csv_float(value, str(tag_code or label or key), row_number)


def _model_csv_enrich_label(
    con,
    model,
    sample_time: str,
    values: dict[str, float | None],
    suggested: float | None,
    k_ai: float | None,
) -> tuple[float | None, float | None, float | None]:
    sample_dt = datetime.fromisoformat(sample_time)
    result = calculate_for_point(
        con,
        int(model["dosing_point_id"]),
        now=sample_dt,
        save=False,
        override_data=values,
        source="model_csv_import",
    )
    generated_suggested = float(result.get("final_l_h")) if result.get("final_l_h") is not None else None
    generated_k_ai = float(result.get("k_ai")) if result.get("k_ai") is not None else None
    training_target = k_ai

    actual = values.get("PAC_ACTUAL")
    denominator = float(result.get("base_l_h") or 0) * float(result.get("k_feedback") or 0)
    if training_target is None and actual is not None and denominator > 1e-6:
        training_target = round(float(actual) / denominator, 6)
    if training_target is None:
        training_target = generated_k_ai

    display_k_ai = k_ai if k_ai is not None else training_target
    return suggested if suggested is not None else generated_suggested, display_k_ai, training_target


def import_model_csv_samples(con, model, csv_text: str) -> dict[str, int]:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV 缺少表头")
    schema = loads_json(model["feature_schema_json"], [])
    headers = _model_csv_header_map(reader.fieldnames)
    time_header = _model_csv_time_header(headers)
    if not time_header:
        raise HTTPException(422, "CSV 必须包含“时间”列")
    suggestion_header = _model_csv_suggestion_header(headers)
    k_ai_header = _model_csv_k_ai_header(headers)
    rows_to_insert: list[tuple[Any, ...]] = []
    generated_suggested = 0
    generated_k_ai = 0
    for index, row in enumerate(reader, start=2):
        sample_time = str(row.get(headers[time_header]) or "").strip()
        try:
            sample_time = datetime.fromisoformat(sample_time).replace(microsecond=0).isoformat()
        except ValueError as exc:
            raise HTTPException(422, f"CSV 第 {index} 行时间格式无效") from exc
        values: dict[str, float | None] = {}
        for item in schema:
            values[item["key"]] = _model_csv_feature_value(row, headers, item, index)
        k_ai = _model_csv_float(row.get(headers[k_ai_header]), "K_AI", index) if k_ai_header else None
        suggested = _model_csv_float(row.get(headers[suggestion_header]), "建议值", index) if suggestion_header else None
        original_suggested = suggested
        original_k_ai = k_ai
        suggested, k_ai, training_target = _model_csv_enrich_label(con, model, sample_time, values, suggested, k_ai)
        if original_suggested is None and suggested is not None:
            generated_suggested += 1
        if original_k_ai is None and training_target is not None:
            generated_k_ai += 1
        values["_training_target_k_ai"] = training_target
        rows_to_insert.append((model["id"], sample_time, dumps_json(values), suggested, k_ai, "csv_import", utc_now_iso()))
    if not rows_to_insert:
        raise HTTPException(422, "CSV 中没有可导入的数据行")
    con.executemany(
        """
        INSERT INTO model_training_samples(model_project_id,sample_time,values_json,suggested_l_h,k_ai,source,created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        rows_to_insert,
    )
    con.execute("UPDATE model_projects SET updated_at=? WHERE id=?", (utc_now_iso(), model["id"]))
    return {"written": len(rows_to_insert), "generated_suggested": generated_suggested, "generated_k_ai": generated_k_ai}


def train_model_project_artifact(con, model) -> dict[str, Any]:
    samples = [
        row_to_dict(row)
        for row in con.execute(
            "SELECT * FROM model_training_samples WHERE model_project_id=? AND k_ai IS NOT NULL ORDER BY sample_time",
            (model["id"],),
        ).fetchall()
    ]
    if len(samples) < 2:
        raise HTTPException(409, "至少需要 2 条包含 K_AI 的训练样本")
    schema = loads_json(model["feature_schema_json"], [])
    usable_samples: list[tuple[dict[str, Any], float]] = []
    for sample in samples:
        values = sample.get("values", {})
        target_value = values.get("_training_target_k_ai")
        # External CSV uses its supplied K_AI column as the training label. Real-time
        # recording instead prioritizes the observed correction derived from PAC flow.
        if target_value is None:
            target_value = sample.get("k_ai")
        try:
            target_number = float(target_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(target_number):
            usable_samples.append((values, target_number))
    if len(usable_samples) < 2:
        raise HTTPException(409, "缺少可用训练标签：请配置加药流量来源并记录样本，或在 CSV 中提供 K_AI")

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

    matrix = np.array(
        [[float(values.get(key)) if values.get(key) is not None else np.nan for key in feature_keys] for values, _ in usable_samples],
        dtype=float,
    )
    target = np.array([target_value for _, target_value in usable_samples], dtype=float)
    dataset = lgb.Dataset(matrix, label=target, feature_name=feature_keys, free_raw_data=False)
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
            "seed": 20260626,
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
    artifact = {
        "format": "ai_pac_lightgbm_v1",
        "file_name": f"model_{model['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.lgb.txt",
        "feature_names": feature_keys,
        "feature_labels": feature_labels,
        "booster_model": booster.model_to_string(),
        "lightgbm_version": lgb.__version__,
        "trained_at": utc_now_iso(),
    }
    metrics = {"samples": len(usable_samples), "R2": round(r2, 4), "MAE": round(mae, 4), "feature_count": len(feature_keys)}
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
