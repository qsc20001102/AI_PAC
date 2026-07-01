from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import lightgbm as lgb
import numpy as np

from app.database import DEFAULT_UNIT_DOSE_CURVE, clear_alarm, dumps_json, loads_json, parse_dt, upsert_alarm, utc_now_iso


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
        control = con.execute("SELECT * FROM process_parameter_groups ORDER BY id LIMIT 1").fetchone()
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
        upsert_alarm(con, severity="high", title=f"{point['name']} 关键实时数据异常", category="data", message="出水TP或进水流量不是实时正常数据。", dosing_point_id=dosing_point_id, event_time=now.isoformat())
        return _persist_and_pack(con, dosing_point_id, now, point, data, "abnormal", "bad", final, final, final, final, reasons, None, tp_forecast, save, source)

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
    pac_model = active_model(con, dosing_point_id, "pac_flow_predict") if ai_enabled else None
    if pac_model:
        target_tp_value = float(control["tp_target_mg_l"])
        predicted_pac, detail, error = predict_pac_flow_model(pac_model, data, {"TP_OUT": target_tp_value})
        if predicted_pac is not None:
            raw = predicted_pac
            mode = "normal"
            ai_detail = detail
            reasons.append(f"正常模式：投用加药流量预测模型 {pac_model['name']}，将模型输入中的出水TP由当前值 {current_tp_value:.4g} mg/L 替换为目标TP {target_tp_value:.4g} mg/L，预测目标TP对应加药流量 {predicted_pac:.4g} L/h")
        else:
            reasons.append(error or "加药流量预测模型不可用，回退保守模式")
    else:
        reasons.append("无投用加药流量预测模型，使用保守模式纯计算")
    if mode == "conservative" and current_tp_value > float(control["tp_upper_mg_l"]):
        final = float(control["pac_max_l_h"])
        reasons.append("实时出水TP高于上限，直接输出最大加药流量")
        upsert_alarm(con, severity="high", title=f"{point['name']} 出水TP高于上限", category="data", message=f"实时出水TP {current_tp_value:.4g} mg/L 高于上限 {float(control['tp_upper_mg_l']):.4g} mg/L。", dosing_point_id=dosing_point_id, event_time=now.isoformat())
        return _persist_and_pack(con, dosing_point_id, now, point, data, "conservative", "good", final, final, final, final, reasons, None, tp_forecast, save, source)
    clear_alarm(con, title=f"{point['name']} 出水TP高于上限", category="data", dosing_point_id=dosing_point_id)

    limited = clamp(raw, float(control["pac_min_l_h"]), float(control["pac_max_l_h"]))
    final = limited
    if abs(limited - raw) > 1e-9:
        reasons.append("建议值已按最小/最大 L/h 限幅")
    return _persist_and_pack(con, dosing_point_id, now, point, data, mode, "good", base, raw, limited, final, reasons, ai_detail, tp_forecast, save, source)


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


def recalculate_all(con: sqlite3.Connection) -> list[dict[str, Any]]:
    now = datetime.now().replace(second=0, microsecond=0)
    rows = con.execute("SELECT id FROM dosing_points WHERE enabled=1 ORDER BY display_order").fetchall()
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
            result.append(calculate_for_point(con, point_id, now=latest_time, save=False))
        else:
            result.append(calculate_for_point(con, point_id, now=now, save=True))
    return result
