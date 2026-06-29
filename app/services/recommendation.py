from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import lightgbm as lgb
import numpy as np
from app.database import clear_alarm, dumps_json, loads_json, parse_dt, upsert_alarm, utc_now_iso


AL_FRACTION_IN_AL2O3 = 54 / 102
AL_P_MASS_RATIO = 27 / 31

PROCESS_SOURCE_MAP = [
    ("in_flow_tag_id", "IN_Q", "进水流量", "m3/h"),
    ("in_tp_tag_id", "TP_BEFORE", "进水TP", "mg/L"),
    ("out_flow_tag_id", "OUT_Q", "出水流量", "m3/h"),
    ("out_tp_tag_id", "TP_OUT", "出水TP", "mg/L"),
    ("zone_flow_tag_id", "ZONE_Q", "分区流量", "m3/h"),
    ("reflux_flow_1_tag_id", "REFLUX_Q1", "回流流量1", "m3/h"),
    ("reflux_flow_2_tag_id", "REFLUX_Q2", "回流流量2", "m3/h"),
    ("po4_tag_id", "PO4_P", "正磷酸盐", "mg/L"),
    ("pac_flow_tag_id", "PAC_ACTUAL", "加药流量", "L/h"),
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


def classify_sample(tag: sqlite3.Row, sample: sqlite3.Row | None, now: datetime | None = None) -> DataPoint:
    now = now or datetime.now().replace(microsecond=0)
    if sample is None:
        return DataPoint(
            tag_id=tag["id"],
            tag_code=tag["tag_code"],
            tag_type=tag["tag_type"],
            name=tag["tag_code"],
            unit=tag["unit"],
            value=None,
            sample_time=None,
            receive_time=None,
            quality="missing",
            source=tag["source"],
            status="stale",
            age_minutes=None,
            stale_minutes=tag["stale_minutes"],
            max_stale_minutes=tag["max_stale_minutes"],
        )

    value = float(sample["value"])
    sample_time = parse_dt(sample["sample_time"])
    age = (now - sample_time).total_seconds() / 60 if sample_time else None
    status = "fresh"
    quality = sample["quality"]

    if quality != "good":
        status = "bad"
    elif tag["min_value"] is not None and value < tag["min_value"]:
        status = "bad"
    elif tag["max_value"] is not None and value > tag["max_value"]:
        status = "bad"
    elif age is None:
        status = "stale"
    elif age <= tag["stale_minutes"]:
        status = "manual" if sample["source"] == "manual" else "fresh"
    elif age <= tag["max_stale_minutes"]:
        status = "manual" if sample["source"] == "manual" else "delayed"
    else:
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
        source=sample["source"],
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
    return DataPoint(
        tag_id=point.tag_id,
        tag_code=point.tag_code,
        tag_type=tag_type,
        name=name or point.name,
        unit=point.unit or unit,
        value=point.value,
        sample_time=point.sample_time,
        receive_time=point.receive_time,
        quality=point.quality,
        source=point.source,
        status=point.status,
        age_minutes=point.age_minutes,
        stale_minutes=point.stale_minutes,
        max_stale_minutes=point.max_stale_minutes,
    )


def latest_data_for_tag(
    con: sqlite3.Connection,
    tag_id: int,
    logical_type: str,
    logical_name: str,
    default_unit: str,
    now: datetime | None = None,
) -> DataPoint | None:
    tag = con.execute("SELECT * FROM sensor_tags WHERE id=? AND enabled=1", (tag_id,)).fetchone()
    if not tag:
        return None
    history_sample = con.execute(
        """
        SELECT * FROM sensor_samples
        WHERE tag_id=?
        ORDER BY sample_time DESC
        LIMIT 1
        """,
        (tag["id"],),
    ).fetchone()

    # PLC polling keeps the newest reading on the tag.  History is intentionally
    # written less frequently, so using only sensor_samples would make a healthy
    # point look stale between history writes.
    realtime_sample: dict[str, Any] | None = None
    if tag["last_value_text"] is not None and tag["last_read_at"] is not None:
        try:
            realtime_sample = {
                "value": float(tag["last_value_text"]),
                "sample_time": tag["last_read_at"],
                "receive_time": tag["last_read_at"],
                "quality": tag["last_quality"] or "unknown",
                "source": tag["source"],
            }
        except (TypeError, ValueError):
            # Non-numeric collection points do not participate in this numeric
            # recommendation path. Keep the historical fallback for them.
            realtime_sample = None

    sample: sqlite3.Row | dict[str, Any] | None = history_sample
    if realtime_sample:
        realtime_time = parse_dt(realtime_sample["sample_time"])
        history_time = parse_dt(history_sample["sample_time"]) if history_sample else None
        if history_time is None or (realtime_time is not None and realtime_time >= history_time):
            sample = realtime_sample
    return with_logical_type(classify_sample(tag, sample, now), logical_type, logical_name, default_unit)


def computed_flow_point(base: DataPoint, value: float, status: str, sample_time: str | None) -> DataPoint:
    return DataPoint(
        tag_id=base.tag_id,
        tag_code=base.tag_code,
        tag_type="Q",
        name="参与计算流量",
        unit=base.unit or "m3/h",
        value=value,
        sample_time=sample_time or base.sample_time,
        receive_time=base.receive_time,
        quality="good" if status in {"fresh", "manual"} else "bad",
        source="computed",
        status=status,
        age_minutes=base.age_minutes,
        stale_minutes=base.stale_minutes,
        max_stale_minutes=base.max_stale_minutes,
    )


def latest_sample_time(points: list[DataPoint]) -> str | None:
    values = [point.sample_time for point in points if point.sample_time]
    return max(values) if values else None


def apply_flow_policy(point: sqlite3.Row, data: dict[str, DataPoint]) -> None:
    configured_parts: list[DataPoint] = []
    zone = data.get("ZONE_Q")
    if point["zone_flow_tag_id"] is not None:
        if not valid_for_fast_calc(zone):
            if zone:
                data["Q"] = computed_flow_point(zone, 0, "bad", zone.sample_time)
            return
        base = zone
        effective = float(zone.value or 0)
        configured_parts.append(zone)
    else:
        inflow = data.get("IN_Q")
        if not valid_for_fast_calc(inflow):
            return
        base = inflow
        effective = float(inflow.value or 0) * float(point["in_flow_weight"] if point["in_flow_weight"] is not None else 1.0)
        configured_parts.append(inflow)

    status = "manual" if any(part.status == "manual" for part in configured_parts) else "fresh"
    data["Q"] = computed_flow_point(base, effective, status, latest_sample_time(configured_parts))


def latest_data_for_point(con: sqlite3.Connection, dosing_point_id: int, now: datetime | None = None) -> dict[str, DataPoint]:
    point = con.execute("SELECT * FROM dosing_points WHERE id=?", (dosing_point_id,)).fetchone()
    if point and (bool(point["source_configured"]) or any(point[field] is not None for field, *_ in PROCESS_SOURCE_MAP)):
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

    tags = con.execute(
        "SELECT * FROM sensor_tags WHERE dosing_point_id=? AND enabled=1",
        (dosing_point_id,),
    ).fetchall()
    result: dict[str, DataPoint] = {}
    for tag in tags:
        sample = con.execute(
            """
            SELECT * FROM sensor_samples
            WHERE tag_id=?
            ORDER BY sample_time DESC
            LIMIT 1
            """,
            (tag["id"],),
        ).fetchone()
        result[tag["tag_type"]] = classify_sample(tag, sample, now)
    return result


def valid_for_fast_calc(point: DataPoint | None) -> bool:
    return bool(point and point.value is not None and point.status in {"fresh", "manual"})


def valid_for_slow_calc(point: DataPoint | None) -> bool:
    return bool(point and point.value is not None and point.status in {"fresh", "manual", "delayed"})


def calculate_mechanism_base(q_m3_h: float, p_control_mg_l: float, pac: sqlite3.Row) -> float:
    al_kg_l = (
        pac["pac_density_kg_l"]
        * float(pac["al2o3_fraction"] if "al2o3_fraction" in pac.keys() else 1.0)
        * AL_FRACTION_IN_AL2O3
        * pac["effective_factor"]
    )
    if al_kg_l <= 0:
        raise ValueError("PAC 参数无效：有效铝含量必须大于 0")
    al_need_kg_h = q_m3_h * p_control_mg_l * AL_P_MASS_RATIO * pac["al_p_ratio"] / 1000
    return al_need_kg_h / al_kg_l


def feedback_factor(
    con: sqlite3.Connection,
    dosing_point_id: int,
    control: sqlite3.Row,
    data: dict[str, DataPoint],
    now: datetime,
) -> tuple[float, float | None, list[str]]:
    tp_out = data.get("TP_OUT")
    if not valid_for_slow_calc(tp_out):
        return 1.0, None, ["出水 TP 缺失或超时，反馈修正暂停"]

    lag_target = now - timedelta(minutes=int(control["lag_minutes"]))
    window_start = lag_target - timedelta(minutes=int(control["feedback_window_minutes"]))
    window_end = lag_target + timedelta(minutes=15)
    if tp_out.tag_id is None:
        return 1.0, None, ["未配置出水 TP 标签，反馈修正暂停"]

    rows = con.execute(
        """
        SELECT value FROM sensor_samples
        WHERE tag_id=? AND sample_time BETWEEN ? AND ? AND quality='good'
        ORDER BY sample_time DESC
        """,
        (tp_out.tag_id, window_start.isoformat(), window_end.isoformat()),
    ).fetchall()
    if not rows:
        return 1.0, None, ["滞后窗口内无出水 TP 样本，反馈修正暂停"]

    avg = sum(float(row["value"]) for row in rows) / len(rows)
    raw = 1 + float(control["feedback_kp"]) * (avg - float(control["tp_target_mg_l"]))
    k = clamp(raw, float(control["feedback_min"]), float(control["feedback_max"]))
    return k, avg, [f"滞后 {control['lag_minutes']} min 出水 TP 已对齐", f"反馈窗口样本 {len(rows)} 条"]


def ai_factor(
    con: sqlite3.Connection,
    dosing_point_id: int,
    data: dict[str, DataPoint],
    base_l_h: float,
) -> tuple[float, str, dict[str, Any] | None]:
    point_model = con.execute(
        """
        SELECT * FROM model_projects
        WHERE dosing_point_id=? AND status='published' AND trained_at IS NOT NULL
        ORDER BY published_at DESC,id DESC
        LIMIT 1
        """,
        (dosing_point_id,),
    ).fetchone()
    if point_model:
        artifact = loads_json(point_model["artifact_json"], {})
        if artifact.get("format") != "ai_pac_lightgbm_v1" or not artifact.get("booster_model"):
            return 1.0, "投用模型文件格式无效，K_ai 回退 1.0", None
        feature_names = artifact.get("feature_names", [])
        feature_values: dict[str, float | None] = {}
        row: list[float] = []
        for key in feature_names:
            point = data.get(key)
            value = float(point.value) if point and point.value is not None else None
            feature_values[key] = value
            row.append(value if value is not None else np.nan)
        try:
            booster = lgb.Booster(model_str=artifact["booster_model"])
            raw = float(booster.predict(np.array([row], dtype=float))[0])
        except Exception:
            return 1.0, "投用模型推理异常，K_ai 回退 1.0", None
        if not math.isfinite(raw):
            return 1.0, "投用模型计算异常，K_ai 回退 1.0", None
        k_ai = clamp(raw, float(point_model["output_min"]), float(point_model["output_max"]))
        detail = {"model_id": point_model["id"], "version": point_model["name"], "features": feature_values, "raw": raw}
        return k_ai, f"{point_model['name']} 已投用", detail

    model = con.execute(
        "SELECT * FROM model_versions WHERE status='published' ORDER BY published_at DESC LIMIT 1"
    ).fetchone()
    if not model:
        return 1.0, "无已发布模型，K_ai 回退 1.0", None

    coeff = loads_json(model["coefficients_json"], {})
    q = data.get("Q").value if data.get("Q") and data.get("Q").value is not None else 0
    po4 = data.get("PO4_P").value if data.get("PO4_P") and data.get("PO4_P").value is not None else 0
    tp_out = data.get("TP_OUT").value if data.get("TP_OUT") and data.get("TP_OUT").value is not None else 0
    ph = data.get("PH").value if data.get("PH") and data.get("PH").value is not None else 7.2
    turbidity = data.get("TURBIDITY").value if data.get("TURBIDITY") and data.get("TURBIDITY").value is not None else 15

    normalized = {
        "q_load": clamp((q - 900) / 1000, -1, 1),
        "po4": clamp((po4 - 0.35) / 0.5, -1, 1),
        "tp_out": clamp((tp_out - 0.20) / 0.35, -1, 1),
        "ph": clamp((ph - 7.2) / 1.2, -1, 1),
        "turbidity": clamp((turbidity - 15) / 50, -1, 1),
    }
    raw = float(coeff.get("intercept", 1.0))
    for key, value in normalized.items():
        raw += float(coeff.get(key, 0.0)) * value

    if not math.isfinite(raw):
        return 1.0, "模型计算异常，K_ai 回退 1.0", None

    k_ai = clamp(raw, float(coeff.get("min", 0.70)), float(coeff.get("max", 1.30)))
    detail = {"model_id": model["id"], "version": model["version"], "features": normalized, "raw": raw}
    return k_ai, f"{model['version']} 已发布", detail


def apply_limits(
    con: sqlite3.Connection,
    dosing_point_id: int,
    control: sqlite3.Row,
    raw: float,
    now: datetime,
) -> tuple[float, float, list[str]]:
    limited = clamp(raw, float(control["pac_min_l_h"]), float(control["pac_max_l_h"]))
    reasons: list[str] = []
    if abs(limited - raw) > 1e-9:
        reasons.append("推荐值已按泵量程上下限限幅")

    last = con.execute(
        """
        SELECT final_l_h,recommend_time FROM recommendations
        WHERE dosing_point_id=? AND source='online'
        ORDER BY recommend_time DESC
        LIMIT 1
        """,
        (dosing_point_id,),
    ).fetchone()
    if not last:
        return limited, limited, reasons

    prev = float(last["final_l_h"])
    last_time = parse_dt(last["recommend_time"]) or now
    elapsed = max((now - last_time).total_seconds() / 60, 1)
    step_limit = abs(prev) * float(control["single_step_change_ratio"])
    if limited >= prev:
        rate_limit = float(control["max_increase_l_h_per_min"]) * elapsed
    else:
        rate_limit = float(control["max_decrease_l_h_per_min"]) * elapsed
    allowed = max(min(step_limit, rate_limit), 0.1)
    final = clamp(limited, prev - allowed, prev + allowed)
    if abs(final - limited) > 1e-9:
        reasons.append("推荐值变化率已限幅")
    return limited, final, reasons


def calculate_for_point(
    con: sqlite3.Connection,
    dosing_point_id: int,
    *,
    now: datetime | None = None,
    save: bool = True,
    override_data: dict[str, float | None] | None = None,
    source: str = "online",
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
    pac = con.execute("SELECT * FROM pac_configs WHERE dosing_point_id=?", (dosing_point_id,)).fetchone()
    control = con.execute("SELECT * FROM control_configs WHERE dosing_point_id=?", (dosing_point_id,)).fetchone()
    if point["chemical_group_id"] is not None:
        pac = con.execute(
            """
            SELECT id, pac_density_kg_l, 1.0 AS al2o3_fraction, effective_factor, al_p_ratio, batch_id, updated_at
            FROM chemical_groups
            WHERE id=?
            """,
            (point["chemical_group_id"],),
        ).fetchone() or pac
    if point["process_parameter_group_id"] is not None:
        control = con.execute(
            """
            SELECT id, tp_target_mg_l, tp_target_mg_l AS tp_safe_target_mg_l, tp_limit_mg_l,
                   pac_min_l_h, pac_max_l_h, 0.15 AS single_step_change_ratio,
                   999.0 AS max_increase_l_h_per_min, 999.0 AS max_decrease_l_h_per_min,
                   lag_minutes, feedback_kp, feedback_min, feedback_max, feedback_window_minutes,
                   calculation_interval_seconds, updated_at
            FROM process_parameter_groups
            WHERE id=?
            """,
            (point["process_parameter_group_id"],),
        ).fetchone() or control
    if not pac or not control:
        raise ValueError("PAC 参数或控制参数未配置")

    data = latest_data_for_point(con, dosing_point_id, now)
    if override_data:
        for tag_type, value in override_data.items():
            if tag_type in data and value is not None:
                dp = data[tag_type]
                data[tag_type] = DataPoint(
                    tag_id=dp.tag_id,
                    tag_code=dp.tag_code,
                    tag_type=dp.tag_type,
                    name=dp.name,
                    unit=dp.unit,
                    value=float(value),
                    sample_time=now.isoformat(),
                    receive_time=now.isoformat(),
                    quality="good",
                    source="simulated",
                    status="manual" if source == "simulation" else "fresh",
                    age_minutes=0,
                    stale_minutes=dp.stale_minutes,
                    max_stale_minutes=dp.max_stale_minutes,
                )

    reasons: list[str] = []
    mode = "normal"
    quality = "good"
    ai_allowed = True
    q = data.get("Q")
    po4 = data.get("PO4_P")
    tp_before = data.get("TP_BEFORE")

    last_rec = con.execute(
        """
        SELECT final_l_h FROM recommendations
        WHERE dosing_point_id=? AND source='online'
        ORDER BY recommend_time DESC LIMIT 1
        """,
        (dosing_point_id,),
    ).fetchone()
    hold_value = float(last_rec["final_l_h"]) if last_rec else float(control["pac_min_l_h"])

    tp_out_limit = data.get("TP_OUT")
    if valid_for_fast_calc(tp_out_limit) and float(tp_out_limit.value or 0) > float(control["tp_limit_mg_l"]):
        final = float(control["pac_max_l_h"])
        reasons.append("出水 TP 超过限制，直接输出最大加药流量")
        upsert_alarm(
            con,
            severity="high",
            title=f"{point['name']} 出水 TP 超限",
            category="data",
            message=f"出水 TP {tp_out_limit.value:.3f} mg/L 超过限制 {control['tp_limit_mg_l']} mg/L。",
            dosing_point_id=dosing_point_id,
            event_time=now.isoformat(),
        )
        return _persist_and_pack(con, dosing_point_id, now, point, data, "conservative", "degraded", final, 1.0, 1.0, final, final, final, reasons, None, None, save, source)
    clear_alarm(con, title=f"{point['name']} 出水 TP 超限", category="data", dosing_point_id=dosing_point_id)

    if not valid_for_fast_calc(q):
        mode = "conservative"
        quality = "degraded"
        base = hold_value
        k_feedback = 1.0
        k_ai = 1.0
        raw = base
        limited = clamp(raw, float(control["pac_min_l_h"]), float(control["pac_max_l_h"]))
        final = limited
        reasons.append("流量缺失或超时，保持上次有效建议/最低保守值")
        upsert_alarm(
            con,
            severity="high",
            title=f"{point['name']} 流量不可用",
            category="data",
            message="流量为关键输入，当前进入保守模式。",
            dosing_point_id=dosing_point_id,
            event_time=now.isoformat(),
        )
        return _persist_and_pack(con, dosing_point_id, now, point, data, mode, quality, base, k_feedback, k_ai, raw, limited, final, reasons, None, None, save, source)

    clear_alarm(con, title=f"{point['name']} 流量不可用", category="data", dosing_point_id=dosing_point_id)
    q_value = float(q.value or 0)
    if q_value <= 0:
        mode = "manual" if q.source == "manual" else "conservative"
        reasons.append("流量为 0，判定停水/停线，建议 0 L/h")
        return _persist_and_pack(con, dosing_point_id, now, point, data, mode, "good", 0, 1.0, 1.0, 0, 0, 0, reasons, None, None, save, source)
    if point["zone_flow_tag_id"] is not None:
        reasons.append("参与计算流量优先采用分区流量")
    else:
        reasons.append(f"参与计算流量采用进水流量 × {float(point['in_flow_weight'] or 0):.3g}")

    if valid_for_fast_calc(po4):
        p_value = float(po4.value or 0)
        p_source = "PO4-P"
        reasons.append("PO4-P fresh")
    elif valid_for_fast_calc(tp_before):
        p_value = float(tp_before.value or 0)
        p_source = "TP"
        reasons.append("PO4-P 缺失，已回退投加前 TP")
        mode = "conservative"
        quality = "degraded"
    else:
        mode = "conservative"
        quality = "degraded"
        base = hold_value
        reasons.append("磷数据全部缺失或超时，保守模式，不使用 AI 猜测")
        upsert_alarm(
            con,
            severity="high",
            title=f"{point['name']} 磷数据不可用",
            category="data",
            message="PO4-P 与投加前 TP 均不可用于关键计算。",
            dosing_point_id=dosing_point_id,
            event_time=now.isoformat(),
        )
        return _persist_and_pack(con, dosing_point_id, now, point, data, mode, quality, base, 1.0, 1.0, base, base, base, reasons, None, None, save, source)

    clear_alarm(con, title=f"{point['name']} 磷数据不可用", category="data", dosing_point_id=dosing_point_id)
    p_control = max(p_value - float(control["tp_target_mg_l"]), 0)
    base = calculate_mechanism_base(q_value, p_control, pac)
    reasons.append(f"机理公式按 {p_source} 与目标 TP 计算")

    k_feedback, tp_lag_avg, feedback_reasons = feedback_factor(con, dosing_point_id, control, data, now)
    reasons.extend(feedback_reasons)
    if k_feedback == 1.0 and tp_lag_avg is None:
        quality = "degraded" if quality == "good" else quality

    chemical_alarm = con.execute(
        """
        SELECT id FROM alarms
        WHERE dosing_point_id=? AND status='active' AND category='chemical'
        LIMIT 1
        """,
        (dosing_point_id,),
    ).fetchone()
    if chemical_alarm:
        mode = "conservative"
        quality = "degraded"
        ai_allowed = False
        reasons.append("PAC 批次待确认，进入保守推荐")

    k_ai, ai_reason, ai_detail = ai_factor(con, dosing_point_id, data, base)
    if not ai_allowed:
        k_ai = 1.0
        ai_detail = None
        reasons.append("当前工况禁止 AI 修正，K_ai 回退 1.0")
    else:
        reasons.append(ai_reason)

    ph = data.get("PH")
    if ph and ph.value is not None and (ph.value < 5.5 or ph.value > 9.0):
        mode = "conservative"
        quality = "degraded"
        k_ai = 1.0
        reasons.append("pH 超出 PAC 合理范围，限制 AI 修正")
        upsert_alarm(
            con,
            severity="medium",
            title=f"{point['name']} pH 异常",
            category="data",
            message="pH 超出建议范围，现场需复核混凝条件。",
            dosing_point_id=dosing_point_id,
            event_time=now.isoformat(),
        )

    raw = base * k_feedback * k_ai
    limited, final, limit_reasons = apply_limits(con, dosing_point_id, control, raw, now)
    reasons.extend(limit_reasons)

    if any(dp.status == "manual" for dp in data.values()):
        mode = "manual" if source != "simulation" else "simulation"
    if source == "simulation":
        mode = "simulation"

    return _persist_and_pack(con, dosing_point_id, now, point, data, mode, quality, base, k_feedback, k_ai, raw, limited, final, reasons, tp_lag_avg, ai_detail, save, source)


def _persist_and_pack(
    con: sqlite3.Connection,
    dosing_point_id: int,
    now: datetime,
    point: sqlite3.Row,
    data: dict[str, DataPoint],
    mode: str,
    quality: str,
    base: float,
    k_feedback: float,
    k_ai: float,
    raw: float,
    limited: float,
    final: float,
    reasons: list[str],
    tp_lag_avg: float | None,
    ai_detail: dict[str, Any] | None,
    save: bool,
    source: str,
) -> dict[str, Any]:
    recommendation_id: int | None = None
    explanation = {
        "mode": mode,
        "base_l_h": round(base, 3),
        "k_feedback": round(k_feedback, 4),
        "k_ai": round(k_ai, 4),
        "raw_l_h": round(raw, 3),
        "limited_l_h": round(limited, 3),
        "final_l_h": round(final, 3),
        "tp_lag_avg": round(tp_lag_avg, 4) if tp_lag_avg is not None else None,
        "reason": reasons,
        "ai_detail": ai_detail,
        "created_at": utc_now_iso(),
    }
    if save:
        cur = con.execute(
            """
            INSERT OR REPLACE INTO recommendations(
                dosing_point_id,recommend_time,mode,base_l_h,k_feedback,k_ai,raw_l_h,limited_l_h,final_l_h,quality,source
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                dosing_point_id,
                now.isoformat(),
                mode,
                round(base, 6),
                round(k_feedback, 6),
                round(k_ai, 6),
                round(raw, 6),
                round(limited, 6),
                round(final, 6),
                quality,
                source,
            ),
        )
        recommendation_id = cur.lastrowid
        if recommendation_id == 0:
            row = con.execute(
                "SELECT id FROM recommendations WHERE dosing_point_id=? AND recommend_time=? AND source=?",
                (dosing_point_id, now.isoformat(), source),
            ).fetchone()
            recommendation_id = row["id"] if row else None
        if recommendation_id:
            con.execute(
                """
                INSERT OR REPLACE INTO recommendation_explanations(recommendation_id,explanation_json)
                VALUES(?,?)
                """,
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
        "k_feedback": round(k_feedback, 3),
        "k_ai": round(k_ai, 3),
        "raw_l_h": round(raw, 2),
        "limited_l_h": round(limited, 2),
        "final_l_h": round(final, 2),
        "reasons": reasons,
        "tp_lag_avg": round(tp_lag_avg, 4) if tp_lag_avg is not None else None,
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
