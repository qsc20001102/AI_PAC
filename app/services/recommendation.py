from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from app.database import DEFAULT_UNIT_DOSE_CURVE, clear_alarm, dumps_json, loads_json, parse_dt, upsert_alarm, utc_now_iso
from app.services import wwtp_ai_engine


PROCESS_SOURCE_MAP = [
    ("in_flow_tag_id", "IN_Q", "进水流量", "m3/h"),
    ("in_tp_tag_id", "TP_BEFORE", "进水TP", "mg/L"),
    ("in_ph_tag_id", "PH", "进水PH", ""),
    ("out_tp_tag_id", "TP_OUT", "出水TP", "mg/L"),
    ("reflux_flow_1_tag_id", "REFLUX_Q1", "回流流量1", "m3/h"),
    ("reflux_flow_2_tag_id", "REFLUX_Q2", "回流流量2", "m3/h"),
    ("pac_flow_tag_id", "PAC_ACTUAL", "加药流量", "L/h"),
    ("bio_orp1_tag_id", "BIO_ORP1", "生化池ORP1", "mV"),
    ("bio_orp2_tag_id", "BIO_ORP2", "生化池ORP2", "mV"),
    ("bio_orp3_tag_id", "BIO_ORP3", "生化池ORP3", "mV"),
    ("bio_orp4_tag_id", "BIO_ORP4", "生化池ORP4", "mV"),
    ("bio_mlss1_tag_id", "BIO_MLSS1", "生化池MLSS1", "mg/L"),
    ("bio_mlss2_tag_id", "BIO_MLSS2", "生化池MLSS2", "mg/L"),
]


@dataclass
class DataPoint:
    tag_id: int | None
    tag_code: str
    tag_type: str
    name: str
    unit: str
    value: float | None
    sample_time: str | None
    receive_time: str | None
    quality: str
    source: str
    status: str
    age_minutes: float | None
    stale_minutes: int
    max_stale_minutes: int


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def valid_for_calc(point: DataPoint | None) -> bool:
    return bool(point and point.value is not None and point.status == "fresh")


def classify_sample(tag: sqlite3.Row, sample: sqlite3.Row | dict[str, Any] | None, now: datetime | None = None) -> DataPoint:
    now = now or datetime.now().replace(microsecond=0)
    if sample is None:
        return DataPoint(tag["id"], tag["tag_code"], tag["tag_type"], tag["tag_code"], tag["unit"], None, None, None, "missing", tag["source"], "missing", None, tag["stale_minutes"], tag["max_stale_minutes"])

    try:
        value = float(sample["value"])
    except (TypeError, ValueError):
        value = None
    sample_time = parse_dt(sample["sample_time"])
    age = (now - sample_time).total_seconds() / 60 if sample_time else None
    source = str(sample["source"] or "")
    quality = str(sample["quality"] or "unknown")
    status = "fresh"
    if value is None or source == "manual" or quality != "good":
        status = "bad"
    elif tag["min_value"] is not None and value < tag["min_value"]:
        status = "bad"
    elif tag["max_value"] is not None and value > tag["max_value"]:
        status = "bad"
    elif age is None:
        status = "missing"
    elif age > tag["stale_minutes"]:
        status = "stale"

    return DataPoint(
        tag_id=tag["id"],
        tag_code=tag["tag_code"],
        tag_type=tag["tag_type"],
        name=tag["tag_code"],
        unit=tag["unit"],
        value=value,
        sample_time=sample["sample_time"],
        receive_time=sample["receive_time"],
        quality=quality,
        source=source,
        status=status,
        age_minutes=round(age, 1) if age is not None else None,
        stale_minutes=tag["stale_minutes"],
        max_stale_minutes=tag["max_stale_minutes"],
    )


def datapoint_to_dict(point: DataPoint) -> dict[str, Any]:
    return {
        "tag_id": point.tag_id,
        "tag_code": point.tag_code,
        "tag_type": point.tag_type,
        "name": point.name,
        "unit": point.unit,
        "value": point.value,
        "sample_time": point.sample_time,
        "receive_time": point.receive_time,
        "quality": point.quality,
        "source": point.source,
        "status": point.status,
        "age_minutes": point.age_minutes,
        "stale_minutes": point.stale_minutes,
        "max_stale_minutes": point.max_stale_minutes,
    }


def with_logical_type(point: DataPoint, tag_type: str, name: str, unit: str) -> DataPoint:
    return DataPoint(point.tag_id, point.tag_code, tag_type, name or point.name, point.unit or unit, point.value, point.sample_time, point.receive_time, point.quality, point.source, point.status, point.age_minutes, point.stale_minutes, point.max_stale_minutes)


def latest_data_for_tag(
    con: sqlite3.Connection,
    tag_id: int,
    logical_type: str,
    logical_name: str,
    default_unit: str,
    now: datetime | None = None,
    at_time: datetime | None = None,
) -> DataPoint | None:
    tag = con.execute("SELECT * FROM sensor_tags WHERE id=? AND enabled=1", (tag_id,)).fetchone()
    if not tag:
        return None
    target_time = at_time or now
    history_sample = con.execute(
        """
        SELECT * FROM sensor_samples
        WHERE tag_id=? AND (? IS NULL OR sample_time<=?)
        ORDER BY sample_time DESC
        LIMIT 1
        """,
        (tag_id, target_time.isoformat() if target_time else None, target_time.isoformat() if target_time else None),
    ).fetchone()
    realtime_sample: dict[str, Any] | None = None
    if at_time is None and tag["last_value_text"] is not None and tag["last_read_at"] is not None:
        try:
            realtime_sample = {
                "value": float(tag["last_value_text"]),
                "sample_time": tag["last_read_at"],
                "receive_time": tag["last_read_at"],
                "quality": tag["last_quality"] or "unknown",
                "source": tag["source"],
            }
        except (TypeError, ValueError):
            realtime_sample = None
    sample: sqlite3.Row | dict[str, Any] | None = realtime_sample or history_sample
    return with_logical_type(classify_sample(tag, sample, at_time or now), logical_type, logical_name, default_unit)


def computed_flow_point(base: DataPoint, value: float) -> DataPoint:
    return DataPoint(base.tag_id, base.tag_code, "Q", "参考流量", base.unit or "m3/h", value, base.sample_time, base.receive_time, "good", "computed", "fresh", base.age_minutes, base.stale_minutes, base.max_stale_minutes)


def apply_flow_policy(point: sqlite3.Row, data: dict[str, DataPoint]) -> None:
    inflow = data.get("IN_Q")
    if not valid_for_calc(inflow):
        return
    effective = float(inflow.value or 0) * float(point["in_flow_weight"] if point["in_flow_weight"] is not None else 1.0)
    data["Q"] = computed_flow_point(inflow, effective)


def latest_data_for_point(con: sqlite3.Connection, dosing_point_id: int, now: datetime | None = None) -> dict[str, DataPoint]:
    point = con.execute("SELECT * FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if not point:
        return {}
    result: dict[str, DataPoint] = {}
    for field, logical_type, logical_name, default_unit in PROCESS_SOURCE_MAP:
        tag_id = point[field]
        if tag_id is None:
            continue
        data = latest_data_for_tag(con, int(tag_id), logical_type, logical_name, default_unit, now)
        if data:
            result[logical_type] = data
    apply_flow_policy(point, result)
    return result


def unit_dose_curve(control: sqlite3.Row | dict[str, Any]) -> list[dict[str, float]]:
    raw = control["unit_dose_curve_json"] if "unit_dose_curve_json" in control.keys() else None
    curve = loads_json(raw, DEFAULT_UNIT_DOSE_CURVE)
    return validate_unit_dose_curve(curve)


def validate_unit_dose_curve(curve: Any) -> list[dict[str, float]]:
    if not isinstance(curve, list) or len(curve) < 2:
        raise ValueError("单耗曲线至少需要 2 个关键点")
    points: list[dict[str, float]] = []
    seen: set[float] = set()
    for item in curve:
        tp = float(item["tp_mg_l"])
        dose = float(item["dose_mg_l"])
        if tp < 0 or dose < 0 or not math.isfinite(tp) or not math.isfinite(dose):
            raise ValueError("单耗曲线关键点必须是非负有限数")
        if tp in seen:
            raise ValueError("单耗曲线出水TP关键点不能重复")
        seen.add(tp)
        points.append({"tp_mg_l": tp, "dose_mg_l": dose})
    return sorted(points, key=lambda item: item["tp_mg_l"])


def interpolate_unit_dose(tp_out: float, curve: list[dict[str, float]]) -> float:
    points = validate_unit_dose_curve(curve)
    if tp_out <= points[0]["tp_mg_l"]:
        return points[0]["dose_mg_l"]
    if tp_out >= points[-1]["tp_mg_l"]:
        return points[-1]["dose_mg_l"]
    for left, right in zip(points, points[1:]):
        if left["tp_mg_l"] <= tp_out <= right["tp_mg_l"]:
            span = right["tp_mg_l"] - left["tp_mg_l"]
            ratio = 0 if span <= 0 else (tp_out - left["tp_mg_l"]) / span
            return left["dose_mg_l"] + (right["dose_mg_l"] - left["dose_mg_l"]) * ratio
    return points[-1]["dose_mg_l"]


def conservative_formula_l_h(reference_flow_m3_h: float, unit_dose_mg_l: float, density_kg_l: float) -> float:
    if density_kg_l <= 0:
        raise ValueError("药剂密度必须大于 0")
    return reference_flow_m3_h * unit_dose_mg_l / density_kg_l / 1000.0


def active_model(con: sqlite3.Connection, dosing_point_id: int, model_kind: str) -> sqlite3.Row | None:
    field_name = "pac_flow_model_id" if model_kind == "pac_flow_predict" else "tp_model_id"
    point = con.execute(f"SELECT {field_name} FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if not point or point[field_name] is None:
        return None
    return con.execute(
        """
        SELECT * FROM model_projects
        WHERE id=? AND model_kind=? AND trained_at IS NOT NULL
        LIMIT 1
        """,
        (point[field_name], model_kind),
    ).fetchone()


def dual_task_model(con: sqlite3.Connection, dosing_point_id: int) -> sqlite3.Row | None:
    point = con.execute("SELECT dual_model_id FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if not point or point["dual_model_id"] is None:
        return None
    return con.execute(
        """
        SELECT * FROM model_projects
        WHERE id=? AND model_kind='ai_pac_dual_task' AND trained_at IS NOT NULL
        LIMIT 1
        """,
        (point["dual_model_id"],),
    ).fetchone()


def fetch_history_for_dual_model(con: sqlite3.Connection, dosing_point_id: int, now: datetime) -> pd.DataFrame | None:
    """为双任务模型获取历史数据（至少80条）"""
    point = con.execute("SELECT * FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if not point:
        return None

    tag_field_map = {
        "in_flow_tag_id": "inflow_flow",
        "in_tp_tag_id": "inflow_tp",
        "in_ph_tag_id": "inflow_ph",
        "out_tp_tag_id": "outflow_tp",
        "reflux_flow_1_tag_id": "high_density_a1_return",
        "reflux_flow_2_tag_id": "high_density_a2_return",
        "bio_orp1_tag_id": "orp_east_1",
        "bio_orp2_tag_id": "orp_east_2",
        "bio_orp3_tag_id": "orp_west_1",
        "bio_orp4_tag_id": "orp_west_2",
        "bio_mlss1_tag_id": "mlss_east",
        "bio_mlss2_tag_id": "mlss_west",
        "pac_flow_tag_id": "pac_dosage",
    }

    tag_ids = []
    id_to_col = {}
    for field, col in tag_field_map.items():
        tid = point[field]
        if tid is not None:
            tag_ids.append(tid)
            id_to_col[tid] = col

    if not tag_ids:
        return None

    since = (now - timedelta(hours=72)).isoformat()
    placeholders = ",".join("?" * len(tag_ids))
    rows = con.execute(
        f"""
        SELECT tag_id, sample_time, value
        FROM sensor_samples
        WHERE tag_id IN ({placeholders}) AND sample_time >= ? AND quality='good'
        ORDER BY sample_time DESC
        """,
        (*tag_ids, since),
    ).fetchall()

    if not rows:
        return None

    records = []
    for row in rows:
        records.append({
            "timestamp": row["sample_time"],
            "tag_col": id_to_col.get(row["tag_id"]),
            "value": row["value"],
        })

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    pivoted = df.pivot_table(index="timestamp", columns="tag_col", values="value", aggfunc="mean")
    pivoted = pivoted.reset_index()

    for col in tag_field_map.values():
        if col not in pivoted.columns:
            pivoted[col] = np.nan

    pivoted = pivoted.sort_values("timestamp").reset_index(drop=True)

    for col in tag_field_map.values():
        pivoted[col] = pivoted[col].ffill().bfill()

    pivoted = pivoted.dropna(subset=list(tag_field_map.values())).reset_index(drop=True)

    return pivoted if len(pivoted) >= 36 else None


def predict_dual_task_model(
    model: sqlite3.Row,
    history_df: pd.DataFrame,
) -> tuple[float | None, float | None, dict[str, Any] | None, str | None]:
    """使用双任务模型预测 PAC 加药量和下次出水TP"""
    artifact = loads_json(model["artifact_json"], {})
    fmt = artifact.get("format", "")
    if fmt not in ("ai_pac_dual_task_v1", "ai_pac_dual_task_v2"):
        return None, None, None, "模型文件格式不支持"
    if not artifact.get("booster_models") or not artifact.get("feature_names"):
        return None, None, None, "模型文件无效"

    try:
        import lightgbm as lgb
        from collections import deque

        booster1 = lgb.Booster(model_str=artifact["booster_models"]["task1"])
        booster2 = lgb.Booster(model_str=artifact["booster_models"]["task2"])
        features1 = artifact["feature_names"]["task1"]
        features2 = artifact["feature_names"]["task2"]

        sample_interval = float(artifact.get("sample_interval_minutes", 5.0))
        buffer_size = 120 if fmt == "ai_pac_dual_task_v2" else 80

        pipeline = wwtp_ai_engine.InferencePipeline.__new__(wwtp_ai_engine.InferencePipeline)
        pipeline.model1 = booster1
        pipeline.model2 = booster2
        pipeline.features1 = features1
        pipeline.features2 = features2
        pipeline.history = deque(maxlen=buffer_size)
        pipeline.sample_interval_minutes = sample_interval

        pipeline.init_history(history_df)
        result = pipeline.predict()

        if result.get("status") != "ok":
            return None, None, None, result.get("message", "推理失败")

        pac_pred = float(result["pac_dosage_prediction"])
        next_tp_pred = float(result["next_outflow_tp_prediction"])
        detail = {
            "model_id": model["id"],
            "version": model["name"],
            "format": fmt,
            "label_mode": artifact.get("label_mode"),
            "used_lag_rows": artifact.get("used_lag_rows"),
            "hrt_minutes": artifact.get("hrt_minutes"),
            "pac_dosage_prediction": pac_pred,
            "tp_delta_prediction": result["tp_delta_prediction"],
            "current_outflow_tp": result["current_outflow_tp"],
            "next_outflow_tp_prediction": next_tp_pred,
        }
        return pac_pred, next_tp_pred, detail, None
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return None, None, None, f"双任务模型推理异常: {exc}"


def _predict_tp_for_pac(
    history_df: pd.DataFrame,
    candidate_pac: float,
    pipeline: Any,
    booster2: Any,
    features2: list[str],
) -> float:
    """给定候选PAC加药量，预测出水TP"""
    modified = history_df.copy()
    modified.iloc[-1, modified.columns.get_loc("pac_dosage")] = candidate_pac
    pipeline.history.clear()
    for _, row in modified.iterrows():
        pipeline.history.append(row.to_dict())
    features_df = pipeline._compute_features()
    X2 = features_df[features2]
    tp_delta = float(booster2.predict(X2)[0])
    return float(history_df["outflow_tp"].iloc[-1]) + tp_delta


def optimize_pac_for_target_tp_dual(
    model: sqlite3.Row,
    history_df: pd.DataFrame,
    control: sqlite3.Row,
) -> tuple[float | None, float | None, dict[str, Any] | None, str | None]:
    """基于双任务模型的任务2，反向优化：二分搜索找到满足目标TP的最小PAC加药量"""
    target_tp = float(control["tp_target_mg_l"])
    min_l_h = float(control["pac_min_l_h"])
    max_l_h = float(control["pac_max_l_h"])
    if max_l_h < min_l_h:
        return None, None, None, "最大加药量小于最小加药量"

    artifact = loads_json(model["artifact_json"], {})
    fmt = artifact.get("format", "")
    if fmt not in ("ai_pac_dual_task_v1", "ai_pac_dual_task_v2"):
        return None, None, None, "模型文件格式不支持"
    if not artifact.get("booster_models") or not artifact.get("feature_names"):
        return None, None, None, "模型文件无效"

    try:
        import lightgbm as lgb
        from collections import deque

        booster2 = lgb.Booster(model_str=artifact["booster_models"]["task2"])
        features2 = artifact["feature_names"]["task2"]

        sample_interval = float(artifact.get("sample_interval_minutes", 5.0))
        buffer_size = 120 if fmt == "ai_pac_dual_task_v2" else 80

        pipeline = wwtp_ai_engine.InferencePipeline.__new__(wwtp_ai_engine.InferencePipeline)
        pipeline.model1 = None
        pipeline.model2 = booster2
        pipeline.features1 = []
        pipeline.features2 = features2
        pipeline.history = deque(maxlen=buffer_size)
        pipeline.sample_interval_minutes = sample_interval

        current_tp = float(history_df["outflow_tp"].iloc[-1])
        checked = 0

        tp_at_min = _predict_tp_for_pac(history_df, min_l_h, pipeline, booster2, features2)
        checked += 1
        if tp_at_min <= target_tp:
            # 最小加药量已满足目标
            detail = {
                "model_id": model["id"], "version": model["name"], "target_tp": target_tp,
                "current_tp": round(current_tp, 4), "checked_candidates": checked,
                "target_met": True, "optimized_pac_l_h": round(min_l_h, 2),
                "predicted_tp": round(tp_at_min, 4),
            }
            return min_l_h, tp_at_min, detail, None

        tp_at_max = _predict_tp_for_pac(history_df, max_l_h, pipeline, booster2, features2)
        checked += 1
        if tp_at_max > target_tp:
            # 即使最大加药量也无法达标
            detail = {
                "model_id": model["id"], "version": model["name"], "target_tp": target_tp,
                "current_tp": round(current_tp, 4), "checked_candidates": checked,
                "target_met": False, "fallback_reason": "即使最大加药量也无法达到目标TP",
            }
            return None, None, detail, detail["fallback_reason"]

        # 二分搜索：PAC 越多 TP 越低，单调递减
        lo = min_l_h
        hi = max_l_h
        best_pac = max_l_h
        best_tp = tp_at_max
        for _ in range(20):  # 最多20次迭代，精度约 0.001 L/h
            mid = round((lo + hi) / 2, 3)
            if mid <= lo or mid >= hi:
                break
            tp_mid = _predict_tp_for_pac(history_df, mid, pipeline, booster2, features2)
            checked += 1
            if tp_mid <= target_tp:
                # mid 满足条件，尝试更小的PAC
                best_pac = mid
                best_tp = tp_mid
                hi = mid
            else:
                # mid 不满足，需要更大的PAC
                lo = mid

        detail = {
            "model_id": model["id"],
            "version": model["name"],
            "target_tp": target_tp,
            "current_tp": round(current_tp, 4),
            "checked_candidates": checked,
            "target_met": True,
            "optimized_pac_l_h": round(best_pac, 2),
            "predicted_tp": round(best_tp, 4),
        }
        return best_pac, best_tp, detail, None

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return None, None, None, f"优化计算异常: {exc}"


def model_feature_row(artifact: dict[str, Any], data: dict[str, DataPoint], extra: dict[str, float] | None = None) -> tuple[list[float], dict[str, float | None]]:
    extra = extra or {}
    row: list[float] = []
    feature_values: dict[str, float | None] = {}
    for key in artifact.get("feature_names", []):
        if key in extra:
            value = extra[key]
        else:
            point = data.get(key)
            value = float(point.value) if point and point.value is not None else None
        feature_values[key] = value
        row.append(value if value is not None else np.nan)
    return row, feature_values


def predict_legacy_tp_forecast_model(model: sqlite3.Row, data: dict[str, DataPoint], extra: dict[str, float] | None = None) -> tuple[float | None, dict[str, Any] | None, str | None]:
    artifact = loads_json(model["artifact_json"], {})
    if artifact.get("format") != "ai_pac_tp_forecast_v1":
        return None, None, "模型文件格式已过期，请重新训练"
    if not artifact.get("booster_model") or not artifact.get("feature_names"):
        return None, None, "模型文件无效"
    try:
        row, feature_values = model_feature_row(artifact, data, extra)
        booster = lgb.Booster(model_str=artifact["booster_model"])
        prediction = float(booster.predict(np.array([row], dtype=float))[0])
    except Exception:
        return None, None, "模型推理异常"
    if not math.isfinite(prediction):
        return None, None, "模型输出异常"
    return prediction, {"model_id": model["id"], "version": model["name"], "features": feature_values, "raw": prediction, "format": artifact.get("format")}, None


def tp_forecast_for_point(con: sqlite3.Connection, dosing_point_id: int, data: dict[str, DataPoint], control: sqlite3.Row) -> dict[str, Any] | None:
    model = active_model(con, dosing_point_id, "tp_out_response")
    if not model:
        return None
    artifact = loads_json(model["artifact_json"], {})
    if artifact.get("format") == "ai_pac_tp_forecast_v3":
        current_pac = current_pac_l_h(data, float(control["pac_min_l_h"]), float(control["pac_max_l_h"]))
        prediction, detail, error = predict_tp_forecast_model(model, data, {"PAC_ACTUAL": current_pac})
        if prediction is None:
            return {"model_id": model["id"], "error": error}
        return {
            "model_id": model["id"],
            "model_name": model["name"],
            "predicted_tp_out": round(prediction, 4),
            "target_label": artifact.get("target_label") or "下一次出水TP检测数据",
            "detail": detail,
        }
    if artifact.get("format") == "ai_pac_tp_forecast_v2":
        return {"model_id": model["id"], "error": "模型文件仍使用旧预测格式，请重新训练"}
    prediction, detail, error = predict_legacy_tp_forecast_model(model, data)
    if prediction is None:
        return {"model_id": model["id"], "error": error}
    return {
        "model_id": model["id"],
        "model_name": model["name"],
        "predicted_tp_out": round(prediction, 4),
        "target_label": "下一次出水TP检测数据",
        "detail": detail,
    }


def predict_tp_forecast_model(model: sqlite3.Row, data: dict[str, DataPoint], extra: dict[str, float] | None = None) -> tuple[float | None, dict[str, Any] | None, str | None]:
    artifact = loads_json(model["artifact_json"], {})
    if artifact.get("format") != "ai_pac_tp_forecast_v3":
        return None, None, "模型文件格式已过期，请重新训练"
    if not artifact.get("booster_model") or not artifact.get("feature_names"):
        return None, None, "模型文件无效"
    try:
        row, feature_values = model_feature_row(artifact, data, extra)
        booster = lgb.Booster(model_str=artifact["booster_model"])
        prediction = float(booster.predict(np.array([row], dtype=float))[0])
        if not math.isfinite(prediction):
            return None, None, "模型输出异常"
    except Exception:
        return None, None, "模型推理异常"
    return prediction, {"model_id": model["id"], "version": model["name"], "features": feature_values, "format": artifact.get("format"), "target_label": artifact.get("target_label")}, None


def predict_pac_flow_model(model: sqlite3.Row, data: dict[str, DataPoint], extra: dict[str, float] | None = None) -> tuple[float | None, dict[str, Any] | None, str | None]:
    artifact = loads_json(model["artifact_json"], {})
    if artifact.get("format") != "ai_pac_flow_predict_v1":
        return None, None, "模型文件格式已过期，请重新训练"
    if not artifact.get("booster_model") or not artifact.get("feature_names"):
        return None, None, "模型文件无效"
    try:
        row, feature_values = model_feature_row(artifact, data, extra)
        booster = lgb.Booster(model_str=artifact["booster_model"])
        prediction = float(booster.predict(np.array([row], dtype=float))[0])
        if not math.isfinite(prediction):
            return None, None, "模型输出异常"
    except Exception:
        return None, None, "模型推理异常"
    return prediction, {"model_id": model["id"], "version": model["name"], "features": feature_values, "feature_overrides": extra or {}, "format": artifact.get("format"), "target_label": artifact.get("target_label")}, None


def point_control(con: sqlite3.Connection, point: sqlite3.Row) -> sqlite3.Row:
    control = None
    if point["process_parameter_group_id"] is not None:
        control = con.execute("SELECT * FROM process_parameter_groups WHERE id=?", (point["process_parameter_group_id"],)).fetchone()
    if not control:
        raise ValueError("工艺参数未配置")
    return control


def last_final_l_h(con: sqlite3.Connection, dosing_point_id: int, fallback: float) -> float:
    row = con.execute(
        """
        SELECT final_l_h FROM recommendations
        WHERE dosing_point_id=? AND source='online'
        ORDER BY recommend_time DESC LIMIT 1
        """,
        (dosing_point_id,),
    ).fetchone()
    return float(row["final_l_h"]) if row else fallback


def calculate_for_point(
    con: sqlite3.Connection,
    dosing_point_id: int,
    *,
    now: datetime | None = None,
    save: bool = True,
    override_data: dict[str, float | None] | None = None,
    source: str = "online",
    ai_enabled: bool = True,
) -> dict[str, Any]:
    now = now or datetime.now().replace(second=0, microsecond=0)
    point = con.execute(
        """
        SELECT dp.*, pl.name AS process_line_name
        FROM dosing_points dp
        JOIN process_lines pl ON pl.id=dp.process_line_id
        WHERE dp.id=?
        """,
        (dosing_point_id,),
    ).fetchone()
    if not point:
        raise ValueError(f"投加点不存在：{dosing_point_id}")
    control = point_control(con, point)
    data = latest_data_for_point(con, dosing_point_id, now)
    if override_data:
        for tag_type, value in override_data.items():
            if tag_type in data and value is not None:
                dp = data[tag_type]
                data[tag_type] = DataPoint(dp.tag_id, dp.tag_code, dp.tag_type, dp.name, dp.unit, float(value), now.isoformat(), now.isoformat(), "good", "override", "fresh", 0, dp.stale_minutes, dp.max_stale_minutes)
        apply_flow_policy(point, data)

    reasons: list[str] = []
    q = data.get("Q")
    tp_out = data.get("TP_OUT")
    hold_value = last_final_l_h(con, dosing_point_id, float(control["pac_min_l_h"]))
    tp_forecast = tp_forecast_for_point(con, dosing_point_id, data, control)

    if not valid_for_calc(q) or not valid_for_calc(tp_out):
        final = clamp(hold_value, float(control["pac_min_l_h"]), float(control["pac_max_l_h"]))
        reasons.append("出水TP或进水流量实时数据异常，保留上次计算结果")
        if save:
            upsert_alarm(con, severity="high", title=f"{point['name']} 关键实时数据异常", category="data", message="出水TP或进水流量不是实时正常数据。", dosing_point_id=dosing_point_id, event_time=now.isoformat())
        return _persist_and_pack(con, dosing_point_id, now, point, data, "abnormal", "bad", final, final, final, final, reasons, None, tp_forecast, save, source, control)

    if save:
        clear_alarm(con, title=f"{point['name']} 关键实时数据异常", category="data", dosing_point_id=dosing_point_id)
    q_value = float(q.value or 0)
    current_tp_value = float(tp_out.value or 0)

    curve = unit_dose_curve(control)
    unit_dose = interpolate_unit_dose(current_tp_value, curve)
    base = conservative_formula_l_h(q_value, unit_dose, float(control["pac_density_kg_l"]))
    reasons.append(f"保守公式单耗曲线按实时出水TP {current_tp_value:.4g} mg/L 得到 {unit_dose:.4g} mg/L")
    reasons.append(f"保守公式：参考流量 {q_value:.4g} × 单耗 {unit_dose:.4g} / 密度 {float(control['pac_density_kg_l']):.4g} / 1000")

    raw = base
    mode = "conservative"
    ai_detail: dict[str, Any] | None = None

    pac_flow_coeff = float(control.get("pac_flow_coefficient", 1.0))
    tp_forecast_coeff = float(control.get("tp_forecast_coefficient", 1.0))

    # 优先检查双任务模型
    dual_model_row = dual_task_model(con, dosing_point_id) if ai_enabled else None
    if dual_model_row:
        history_df = fetch_history_for_dual_model(con, dosing_point_id, now)
        if history_df is not None and len(history_df) >= 36:
            predicted_pac, predicted_next_tp, detail, error = predict_dual_task_model(dual_model_row, history_df)
            if predicted_pac is not None:
                raw = predicted_pac * pac_flow_coeff
                mode = "dual_task_ai"
                ai_detail = detail
                reasons.append(f"双任务AI模式：投用模型 {dual_model_row['name']}，PAC预测 {predicted_pac:.4g} L/h × 系数 {pac_flow_coeff:.4g} = {raw:.4g} L/h，下次出水TP预测 {predicted_next_tp:.4g} mg/L × 系数 {tp_forecast_coeff:.4g} = {predicted_next_tp * tp_forecast_coeff:.4g} mg/L")
                # 构造tp_forecast
                tp_forecast = {
                    "model_id": dual_model_row["id"],
                    "model_name": dual_model_row["name"],
                    "predicted_tp_out": round(predicted_next_tp * tp_forecast_coeff, 4) if predicted_next_tp is not None else None,
                    "target_label": "下次出水TP预测",
                    "detail": detail,
                }
            else:
                reasons.append(error or "双任务模型推理失败，回退保守模式")
        else:
            reasons.append("双任务模型历史数据不足，回退保守模式")
    else:
        reasons.append("无投用双任务模型，使用保守模式纯计算")

    if mode == "conservative" and current_tp_value > float(control["tp_upper_mg_l"]):
        final = float(control["pac_max_l_h"])
        reasons.append("实时出水TP高于上限，直接输出最大加药流量")
        if save:
            upsert_alarm(con, severity="high", title=f"{point['name']} 出水TP高于上限", category="data", message=f"实时出水TP {current_tp_value:.4g} mg/L 高于上限 {float(control['tp_upper_mg_l']):.4g} mg/L。", dosing_point_id=dosing_point_id, event_time=now.isoformat())
        return _persist_and_pack(con, dosing_point_id, now, point, data, "conservative", "good", final, final, final, final, reasons, None, tp_forecast, save, source, control)
    if save:
        clear_alarm(con, title=f"{point['name']} 出水TP高于上限", category="data", dosing_point_id=dosing_point_id)

    limited = clamp(raw, float(control["pac_min_l_h"]), float(control["pac_max_l_h"]))
    final = limited
    if abs(limited - raw) > 1e-9:
        reasons.append("建议值已按最小/最大 L/h 限幅")
    return _persist_and_pack(con, dosing_point_id, now, point, data, mode, "good", base, raw, limited, final, reasons, ai_detail, tp_forecast, save, source, control)


def optimize_pac_by_tp_forecast_model(
    model: sqlite3.Row,
    data: dict[str, DataPoint],
    control: sqlite3.Row,
) -> tuple[float | None, dict[str, Any] | None, str | None]:
    target_tp = float(control["tp_target_mg_l"])
    min_l_h = float(control["pac_min_l_h"])
    max_l_h = float(control["pac_max_l_h"])
    if max_l_h < min_l_h:
        return None, None, "最大加药量小于最小加药量"
    steps = int(round((max_l_h - min_l_h) / 0.1))
    best: tuple[float, float] | None = None
    lowest_prediction: tuple[float, float] | None = None
    last_prediction: tuple[float, float] | None = None
    checked = 0
    current_pac = current_pac_l_h(data, min_l_h, max_l_h)
    current_prediction, _current_detail, current_error = predict_tp_forecast_model(model, data, {"PAC_ACTUAL": current_pac})
    if current_prediction is None:
        return None, None, current_error
    for index in range(steps + 1):
        candidate = round(min_l_h + index * 0.1, 1)
        if candidate > max_l_h:
            candidate = max_l_h
        prediction, _detail, error = predict_tp_forecast_model(model, data, {"PAC_ACTUAL": candidate})
        if prediction is None:
            return None, None, error
        checked += 1
        last_prediction = (candidate, prediction)
        if lowest_prediction is None or prediction < lowest_prediction[1] - 1e-9:
            lowest_prediction = (candidate, prediction)
        if prediction <= target_tp:
            best = (candidate, prediction)
            break
    if best is None and (last_prediction is None or last_prediction[0] < max_l_h):
        prediction, _detail, error = predict_tp_forecast_model(model, data, {"PAC_ACTUAL": max_l_h})
        if prediction is None:
            return None, None, error
        checked += 1
        last_prediction = (max_l_h, prediction)
        if lowest_prediction is None or prediction < lowest_prediction[1] - 1e-9:
            lowest_prediction = (max_l_h, prediction)
    model_sensitive = bool(lowest_prediction and current_prediction - lowest_prediction[1] >= 0.005)
    selected = best
    if selected is None:
        detail = {
            "model_id": model["id"],
            "version": model["name"],
            "target_label": "下一次出水TP检测数据",
            "target_tp": target_tp,
            "current_l_h": current_pac,
            "current_predicted_tp_out": round(current_prediction, 4),
            "lowest_predicted_l_h": lowest_prediction[0] if lowest_prediction else None,
            "lowest_predicted_tp_out": round(lowest_prediction[1], 4) if lowest_prediction else None,
            "step_l_h": 0.1,
            "checked_candidates": checked,
            "target_met": False,
            "fallback_reason": "fallback_conservative_unmet_target",
            "model_sensitive": model_sensitive,
            "search_min_l_h": min_l_h,
            "search_max_l_h": max_l_h,
        }
        return None, detail, f"枚举范围内没有找到预测TP小于等于目标TP的加药量，回退保守模式；最低预测TP {detail['lowest_predicted_tp_out']} mg/L"
    selected_l_h, selected_tp = selected
    return (
        selected_l_h,
        {
            "model_id": model["id"],
            "version": model["name"],
            "target_label": "下一次出水TP检测数据",
            "target_tp": target_tp,
            "selected_l_h": selected_l_h,
            "predicted_tp_out": round(selected_tp, 4),
            "current_l_h": current_pac,
            "current_predicted_tp_out": round(current_prediction, 4),
            "lowest_predicted_l_h": lowest_prediction[0] if lowest_prediction else None,
            "lowest_predicted_tp_out": round(lowest_prediction[1], 4) if lowest_prediction else None,
            "step_l_h": 0.1,
            "checked_candidates": checked,
            "target_met": True,
            "fallback_reason": None,
            "search_min_l_h": min_l_h,
            "search_max_l_h": max_l_h,
        },
        None,
    )


def current_pac_l_h(data: dict[str, DataPoint], min_l_h: float, max_l_h: float) -> float:
    point = data.get("PAC_ACTUAL")
    if not point or point.value is None:
        return min_l_h
    return round(clamp(float(point.value), min_l_h, max_l_h), 1)


def _persist_and_pack(
    con: sqlite3.Connection,
    dosing_point_id: int,
    now: datetime,
    point: sqlite3.Row,
    data: dict[str, DataPoint],
    mode: str,
    quality: str,
    base: float,
    raw: float,
    limited: float,
    final: float,
    reasons: list[str],
    ai_detail: dict[str, Any] | None,
    tp_forecast: dict[str, Any] | None,
    save: bool,
    source: str,
    control: sqlite3.Row | None = None,
) -> dict[str, Any]:
    recommendation_id: int | None = None
    explanation = {
        "mode": mode,
        "base_l_h": round(base, 3),
        "raw_l_h": round(raw, 3),
        "limited_l_h": round(limited, 3),
        "final_l_h": round(final, 3),
        "reason": reasons,
        "ai_detail": ai_detail,
        "tp_forecast": tp_forecast,
        "created_at": utc_now_iso(),
    }
    if save:
        write_virtual_point_samples(con, dosing_point_id, now, mode, tp_forecast, final, control)
        recommendation_columns = {row["name"] for row in con.execute("PRAGMA table_info(recommendations)").fetchall()}
        if {"k_feedback", "k_ai"} <= recommendation_columns:
            cur = con.execute(
                """
                INSERT OR REPLACE INTO recommendations(
                    dosing_point_id,recommend_time,mode,base_l_h,k_feedback,k_ai,raw_l_h,limited_l_h,final_l_h,quality,source
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (dosing_point_id, now.isoformat(), mode, round(base, 6), 1.0, 1.0, round(raw, 6), round(limited, 6), round(final, 6), quality, source),
            )
        else:
            cur = con.execute(
                """
                INSERT OR REPLACE INTO recommendations(
                    dosing_point_id,recommend_time,mode,base_l_h,raw_l_h,limited_l_h,final_l_h,quality,source
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (dosing_point_id, now.isoformat(), mode, round(base, 6), round(raw, 6), round(limited, 6), round(final, 6), quality, source),
            )
        recommendation_id = cur.lastrowid
        if recommendation_id == 0:
            row = con.execute("SELECT id FROM recommendations WHERE dosing_point_id=? AND recommend_time=? AND source=?", (dosing_point_id, now.isoformat(), source)).fetchone()
            recommendation_id = row["id"] if row else None
        if recommendation_id:
            con.execute(
                "INSERT OR REPLACE INTO recommendation_explanations(recommendation_id,explanation_json) VALUES(?,?)",
                (recommendation_id, dumps_json(explanation)),
            )

    return {
        "id": recommendation_id,
        "dosing_point_id": dosing_point_id,
        "dosing_point_name": point["name"],
        "process_line_name": point["process_line_name"],
        "recommend_time": now.isoformat(),
        "mode": mode,
        "quality": quality,
        "base_l_h": round(base, 2),
        "raw_l_h": round(raw, 2),
        "limited_l_h": round(limited, 2),
        "final_l_h": round(final, 2),
        "reasons": reasons,
        "tp_lag_avg": None,
        "tp_forecast": tp_forecast,
        "data": {key: datapoint_to_dict(value) for key, value in data.items()},
    }


def write_virtual_point_samples(
    con: sqlite3.Connection,
    dosing_point_id: int,
    now: datetime,
    mode: str,
    tp_forecast: dict[str, Any] | None,
    final_l_h: float,
    control: sqlite3.Row | None,
) -> None:
    point = con.execute("SELECT code FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if not point:
        return
    from app.api.dosing_points import ensure_virtual_point_tags
    ensure_virtual_point_tags(con, dosing_point_id, point["code"])
    tags = {
        row["tag_type"]: row
        for row in con.execute(
            "SELECT id, tag_type, last_history_at FROM sensor_tags WHERE dosing_point_id=? AND tag_type IN ('PREDICT_TP','RECOMMEND_PAC')",
            (dosing_point_id,),
        ).fetchall()
    }
    interval = int(control["calculation_interval_seconds"]) if control and control["calculation_interval_seconds"] else 60
    now_iso = now.isoformat()
    if "PREDICT_TP" in tags and tp_forecast and tp_forecast.get("predicted_tp_out") is not None:
        last_history = parse_dt(tags["PREDICT_TP"]["last_history_at"])
        if last_history is None or (now - last_history).total_seconds() >= interval:
            con.execute(
                "INSERT INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source) VALUES(?,?,?,?,?,?,?)",
                (tags["PREDICT_TP"]["id"], tp_forecast["predicted_tp_out"], "mg/L", now_iso, now_iso, "good", "computed"),
            )
            con.execute(
                "UPDATE sensor_tags SET last_history_at=?, last_value_text=?, last_quality='good', last_read_at=? WHERE id=?",
                (now_iso, str(tp_forecast["predicted_tp_out"]), now_iso, tags["PREDICT_TP"]["id"]),
            )
    if "RECOMMEND_PAC" in tags and mode != "abnormal":
        last_history = parse_dt(tags["RECOMMEND_PAC"]["last_history_at"])
        if last_history is None or (now - last_history).total_seconds() >= interval:
            con.execute(
                "INSERT INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source) VALUES(?,?,?,?,?,?,?)",
                (tags["RECOMMEND_PAC"]["id"], final_l_h, "L/h", now_iso, now_iso, "good", "computed"),
            )
            con.execute(
                "UPDATE sensor_tags SET last_history_at=?, last_value_text=?, last_quality='good', last_read_at=? WHERE id=?",
                (now_iso, str(final_l_h), now_iso, tags["RECOMMEND_PAC"]["id"]),
            )


def _pack_cached_recommendation(con: sqlite3.Connection, point_id: int, now: datetime) -> dict[str, Any] | None:
    """直接从数据库读取上次推荐结果（不重新计算），用于 dashboard 缓存命中"""
    row = con.execute(
        """
        SELECT r.*, dp.name AS dosing_point_name, pl.name AS process_line_name,
               re.explanation_json
        FROM recommendations r
        JOIN dosing_points dp ON dp.id=r.dosing_point_id
        JOIN process_lines pl ON pl.id=dp.process_line_id
        LEFT JOIN recommendation_explanations re ON re.recommendation_id=r.id
        WHERE r.dosing_point_id=? AND r.source='online'
        ORDER BY r.recommend_time DESC
        LIMIT 1
        """,
        (point_id,),
    ).fetchone()
    if not row:
        return None
    explanation = loads_json(row["explanation_json"] or "{}", {})
    # 使用 latest_data_for_point 获取逻辑类型映射的数据（与 calculate_for_point 一致）
    data = latest_data_for_point(con, point_id, now)
    return {
        "id": row["id"],
        "dosing_point_id": point_id,
        "dosing_point_name": row["dosing_point_name"],
        "process_line_name": row["process_line_name"],
        "recommend_time": row["recommend_time"],
        "mode": row["mode"],
        "quality": row["quality"],
        "base_l_h": round(float(row["base_l_h"] or 0), 2),
        "raw_l_h": round(float(row["raw_l_h"] or 0), 2),
        "limited_l_h": round(float(row["limited_l_h"] or 0), 2),
        "final_l_h": round(float(row["final_l_h"] or 0), 2),
        "reasons": explanation.get("reason", []),
        "tp_lag_avg": None,
        "tp_forecast": explanation.get("tp_forecast"),
        "data": data,
    }


def recalculate_all(con: sqlite3.Connection) -> list[dict[str, Any]]:
    now = datetime.now().replace(second=0, microsecond=0)
    rows = con.execute(
        "SELECT id FROM dosing_points WHERE enabled=1 AND process_parameter_group_id IS NOT NULL ORDER BY display_order"
    ).fetchall()
    result = []
    for row in rows:
        point_id = int(row["id"])
        interval_row = con.execute(
            """
            SELECT ppg.calculation_interval_seconds
            FROM dosing_points dp
            LEFT JOIN process_parameter_groups ppg ON ppg.id=dp.process_parameter_group_id
            WHERE dp.id=?
            """,
            (point_id,),
        ).fetchone()
        interval = int(interval_row["calculation_interval_seconds"] or 60) if interval_row else 60
        latest = con.execute(
            """
            SELECT recommend_time FROM recommendations
            WHERE dosing_point_id=? AND source='online'
            ORDER BY recommend_time DESC
            LIMIT 1
            """,
            (point_id,),
        ).fetchone()
        latest_time = parse_dt(latest["recommend_time"]) if latest else None
        if latest_time and (now - latest_time).total_seconds() < interval:
            cached = _pack_cached_recommendation(con, point_id, now)
            if cached:
                result.append(cached)
                continue
        result.append(calculate_for_point(con, point_id, now=now, save=True))
    return result
