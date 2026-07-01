from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.common import row_to_dict
from app.database import LEARNING_SOURCE_TAG_DEFS, db_session, infer_process_source_tags, loads_json, utc_now_iso
from app.schemas import DosingPointCreate, DosingPointUpdate
from app.services.audit import audit
from app.services.recommendation import calculate_for_point


router = APIRouter()


PROCESS_SOURCE_TAG_FIELDS = [
    "in_flow_tag_id",
    "in_tp_tag_id",
    "in_ph_tag_id",
    "out_flow_tag_id",
    "out_tp_tag_id",
    "reflux_flow_1_tag_id",
    "reflux_flow_2_tag_id",
    "pac_flow_tag_id",
    *[field for field, *_ in LEARNING_SOURCE_TAG_DEFS],
]


TAG_DEFS = [
    ("Q", "流量", "m3/h", 3, 15, 0, 4000),
    ("TP_BEFORE", "投加前 TP", "mg/L", 20, 120, 0, 20),
    ("TP_OUT", "出水 TP", "mg/L", 30, 180, 0, 5),
    ("PH", "pH", "", 10, 60, 3, 11),
    ("PAC_ACTUAL", "PAC 实际", "L/h", 10, 60, 0, 200),
    ("TURBIDITY", "浊度", "NTU", 30, 120, 0, 300),
    ("BIO_ORP1", "生化池ORP1", "mV", 10, 60, -1000, 1000),
    ("BIO_ORP2", "生化池ORP2", "mV", 10, 60, -1000, 1000),
    ("BIO_ORP3", "生化池ORP3", "mV", 10, 60, -1000, 1000),
    ("BIO_ORP4", "生化池ORP4", "mV", 10, 60, -1000, 1000),
    ("BIO_DO1", "生化池DO1", "mg/L", 10, 60, 0, 20),
    ("BIO_DO2", "生化池DO2", "mg/L", 10, 60, 0, 20),
    ("BIO_MLSS1", "生化池MLSS1", "mg/L", 30, 120, 0, 20000),
    ("BIO_MLSS2", "生化池MLSS2", "mg/L", 30, 120, 0, 20000),
]

VIRTUAL_TAG_DEFS = [
    ("PREDICT_TP", "预测出水TP", "mg/L", 60, 180, 0, 5),
    ("RECOMMEND_PAC", "推荐加药流量", "L/h", 10, 60, 0, 200),
]


def latest_recommendation(con, dosing_point_id: int) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT r.*, e.explanation_json
        FROM recommendations r
        LEFT JOIN recommendation_explanations e ON e.recommendation_id=r.id
        WHERE r.dosing_point_id=? AND r.source='online'
        ORDER BY r.recommend_time DESC
        LIMIT 1
        """,
        (dosing_point_id,),
    ).fetchone()
    if not row:
        return None
    data = row_to_dict(row)
    data["explanation"] = loads_json(row["explanation_json"], {})
    data.pop("explanation_json", None)
    return data


@router.get("/api/dosing-points")
def dosing_points() -> list[dict[str, Any]]:
    with db_session() as con:
        rows = con.execute(
            """
            SELECT dp.*, pl.name AS process_line_name, pl.line_code, pa.name AS area_name, p.name AS plant_name,
                   ppg.name AS process_parameter_group_name
            FROM dosing_points dp
            JOIN process_lines pl ON pl.id=dp.process_line_id
            JOIN process_areas pa ON pa.id=pl.area_id
            JOIN plants p ON p.id=pa.plant_id
            LEFT JOIN process_parameter_groups ppg ON ppg.id=dp.process_parameter_group_id
            ORDER BY dp.display_order
            """
        ).fetchall()
        result = []
        for row in rows:
            item = public_dosing_point(row_to_dict(row))
            item["control_config"] = point_control_config(con, row["process_parameter_group_id"])
            item["latest_recommendation"] = latest_recommendation(con, row["id"])
            item["source_tags"] = source_tag_options(con, row["id"])
            result.append(item)
        return result


@router.post("/api/dosing-points")
def create_dosing_point(payload: DosingPointCreate) -> dict[str, Any]:
    with db_session() as con:
        validate_dosing_point_payload(con, payload)
        validate_process_source_tags(con, payload)
        process_line_id = resolve_process_line_id(con, payload.process_line_id)
        display_order = payload.display_order
        if display_order is None or display_order == 0:
            display_order = int(con.execute("SELECT COALESCE(MAX(display_order), 0) + 1 FROM dosing_points").fetchone()[0])
        cur = con.execute(
            """
            INSERT INTO dosing_points(
                process_line_id,name,code,enabled,flow_source,
                in_flow_tag_id,in_tp_tag_id,in_ph_tag_id,out_flow_tag_id,out_tp_tag_id,
                in_flow_weight,reflux_flow_1_tag_id,reflux_flow_2_tag_id,pac_flow_tag_id,
                bio_orp1_tag_id,bio_orp2_tag_id,bio_orp3_tag_id,bio_orp4_tag_id,
                bio_do1_tag_id,bio_do2_tag_id,bio_mlss1_tag_id,bio_mlss2_tag_id,
                tp_model_id,pac_flow_model_id,process_parameter_group_id,source_configured,display_order,write_enabled
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            point_values(payload, process_line_id, display_order),
        )
        point_id = int(cur.lastrowid)
        create_default_point_tags(con, point_id, payload.code)
        backfill_point_source_tags(con, point_id)
        audit(con, "local", "create", "dosing_point", str(point_id), payload.model_dump())
        result = calculate_for_point(con, point_id) if payload.process_parameter_group_id is not None else None
    return {"ok": True, "id": point_id, "recommendation": result}


@router.put("/api/dosing-points/{point_id}")
def update_dosing_point(point_id: int, payload: DosingPointUpdate) -> dict[str, Any]:
    with db_session() as con:
        point = con.execute("SELECT * FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not point:
            raise HTTPException(404, "投加点不存在")
        validate_dosing_point_payload(con, payload, point_id=point_id)
        validate_process_source_tags(con, payload, point_id=point_id)
        process_line_id = payload.process_line_id if payload.process_line_id is not None else point["process_line_id"]
        display_order = payload.display_order if payload.display_order is not None else point["display_order"]
        old_code = point["code"]
        con.execute(
            """
            UPDATE dosing_points
            SET process_line_id=?, name=?, code=?, enabled=?, flow_source=?,
                in_flow_tag_id=?, in_tp_tag_id=?, in_ph_tag_id=?, out_flow_tag_id=?, out_tp_tag_id=?,
                in_flow_weight=?, reflux_flow_1_tag_id=?, reflux_flow_2_tag_id=?, pac_flow_tag_id=?,
                bio_orp1_tag_id=?, bio_orp2_tag_id=?, bio_orp3_tag_id=?, bio_orp4_tag_id=?,
                bio_do1_tag_id=?, bio_do2_tag_id=?, bio_mlss1_tag_id=?, bio_mlss2_tag_id=?,
                tp_model_id=?, pac_flow_model_id=?, process_parameter_group_id=?, source_configured=?,
                display_order=?, write_enabled=?
            WHERE id=?
            """,
            (*point_values(payload, process_line_id, display_order), point_id),
        )
        if old_code != payload.code:
            rename_point_tag_codes(con, point_id, payload.code)
        audit(con, "local", "update", "dosing_point", str(point_id), payload.model_dump())
        result = calculate_for_point(con, point_id) if payload.enabled and payload.process_parameter_group_id is not None else None
    return {"ok": True, "recommendation": result}


@router.delete("/api/dosing-points/{point_id}")
def delete_dosing_point(point_id: int) -> dict[str, Any]:
    with db_session() as con:
        point = con.execute("SELECT * FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not point:
            raise HTTPException(404, "投加点不存在")
        con.execute("UPDATE alarms SET dosing_point_id=NULL WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM recommendations WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM sensor_tags WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM dosing_points WHERE id=?", (point_id,))
        audit(con, "local", "delete", "dosing_point", str(point_id), {"name": point["name"], "code": point["code"]})
    return {"ok": True, "deleted_id": point_id}


@router.get("/api/dosing-points/{point_id}/config")
def point_config(point_id: int) -> dict[str, Any]:
    with db_session() as con:
        point = con.execute("SELECT * FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not point:
            raise HTTPException(404, "投加点不存在")
        return {
            "point": public_dosing_point(row_to_dict(point)),
            "control_config": point_control_config(con, point["process_parameter_group_id"]),
        }


def public_dosing_point(row: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "process_line_id",
        "name",
        "code",
        "enabled",
        "flow_source",
        "display_order",
        "write_enabled",
        "in_flow_tag_id",
        "in_tp_tag_id",
        "in_ph_tag_id",
        "out_flow_tag_id",
        "out_tp_tag_id",
        "reflux_flow_1_tag_id",
        "reflux_flow_2_tag_id",
        "pac_flow_tag_id",
        "source_configured",
        "in_flow_weight",
        "process_parameter_group_id",
        "bio_orp1_tag_id",
        "bio_orp2_tag_id",
        "bio_orp3_tag_id",
        "bio_orp4_tag_id",
        "bio_do1_tag_id",
        "bio_do2_tag_id",
        "bio_mlss1_tag_id",
        "bio_mlss2_tag_id",
        "tp_model_id",
        "pac_flow_model_id",
        "process_line_name",
        "line_code",
        "area_name",
        "plant_name",
        "process_parameter_group_name",
    }
    return {key: row.get(key) for key in allowed if key in row}


def public_control_config(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "tp_target_mg_l": row["tp_target_mg_l"],
        "tp_upper_mg_l": row.get("tp_upper_mg_l", row.get("tp_limit_mg_l")),
        "pac_min_l_h": row["pac_min_l_h"],
        "pac_max_l_h": row["pac_max_l_h"],
        "calculation_interval_seconds": row["calculation_interval_seconds"],
        "pac_density_kg_l": row.get("pac_density_kg_l", 1.2),
        "unit_dose_curve": row.get("unit_dose_curve", []),
        "updated_at": row["updated_at"],
    }


def point_control_config(con, group_id: int | None) -> dict[str, Any] | None:
    if group_id is None:
        return None
    row = con.execute("SELECT * FROM process_parameter_groups WHERE id=?", (group_id,)).fetchone()
    return public_control_config(row_to_dict(row)) if row else None


def point_values(payload: DosingPointCreate | DosingPointUpdate, process_line_id: int, display_order: int) -> tuple[Any, ...]:
    return (
        process_line_id,
        payload.name,
        payload.code,
        int(payload.enabled),
        payload.flow_source or "line",
        payload.in_flow_tag_id,
        payload.in_tp_tag_id,
        payload.in_ph_tag_id,
        payload.out_flow_tag_id,
        payload.out_tp_tag_id,
        payload.in_flow_weight,
        payload.reflux_flow_1_tag_id,
        payload.reflux_flow_2_tag_id,
        payload.pac_flow_tag_id,
        payload.bio_orp1_tag_id,
        payload.bio_orp2_tag_id,
        payload.bio_orp3_tag_id,
        payload.bio_orp4_tag_id,
        payload.bio_do1_tag_id,
        payload.bio_do2_tag_id,
        payload.bio_mlss1_tag_id,
        payload.bio_mlss2_tag_id,
        payload.tp_model_id,
        payload.pac_flow_model_id,
        payload.process_parameter_group_id,
        int(any(getattr(payload, field) is not None for field in PROCESS_SOURCE_TAG_FIELDS)),
        display_order,
        int(payload.write_enabled or False),
    )


def source_tag_options(con, point_id: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT id, dosing_point_id, tag_code, name, unit, last_quality, last_value_text, last_read_at
        FROM sensor_tags
        WHERE enabled=1 AND (dosing_point_id IS NULL OR dosing_point_id=?)
        ORDER BY CASE WHEN dosing_point_id IS NULL THEN 0 ELSE 1 END, id
        """,
        (point_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def validate_process_source_tags(con, payload: DosingPointCreate | DosingPointUpdate, point_id: int | None = None) -> None:
    for field_name in PROCESS_SOURCE_TAG_FIELDS:
        tag_id = getattr(payload, field_name, None)
        if tag_id is None:
            continue
        row = con.execute("SELECT id, dosing_point_id FROM sensor_tags WHERE id=? AND enabled=1", (tag_id,)).fetchone()
        if not row:
            raise HTTPException(422, f"{field_name} 对应采集点不存在或未启用")
        owner_id = row["dosing_point_id"]
        if owner_id is not None and (point_id is None or int(owner_id) != int(point_id)):
            raise HTTPException(422, f"{field_name} 只能选择公共数据或当前投加点的采集点")


def backfill_point_source_tags(con, point_id: int) -> None:
    tags = con.execute("SELECT id, tag_code, tag_type FROM sensor_tags WHERE dosing_point_id=? ORDER BY id", (point_id,)).fetchall()
    values = infer_process_source_tags(tags)
    learning_fields = [field for field, *_ in LEARNING_SOURCE_TAG_DEFS]
    con.execute(
        f"""
        UPDATE dosing_points
        SET in_flow_tag_id=COALESCE(in_flow_tag_id, ?),
            in_tp_tag_id=COALESCE(in_tp_tag_id, ?),
            in_ph_tag_id=COALESCE(in_ph_tag_id, ?),
            out_tp_tag_id=COALESCE(out_tp_tag_id, ?),
            pac_flow_tag_id=COALESCE(pac_flow_tag_id, ?),
            {", ".join(f"{field}=COALESCE({field}, ?)" for field in learning_fields)},
            source_configured=1
        WHERE id=?
        """,
        (
            values["in_flow_tag_id"],
            values["in_tp_tag_id"],
            values["in_ph_tag_id"],
            values["out_tp_tag_id"],
            values["pac_flow_tag_id"],
            *(values[field] for field in learning_fields),
            point_id,
        ),
    )


def validate_dosing_point_payload(con, payload: DosingPointCreate | DosingPointUpdate, point_id: int | None = None) -> None:
    if payload.process_line_id is not None:
        line = con.execute("SELECT id FROM process_lines WHERE id=?", (payload.process_line_id,)).fetchone()
        if not line:
            raise HTTPException(422, "工艺线不存在")
    elif isinstance(payload, DosingPointCreate) and resolve_process_line_id(con, None) is None:
        raise HTTPException(422, "工艺线不存在")
    if not all((char.isascii() and (char.isalnum() or char in "_-")) for char in payload.code):
        raise HTTPException(422, "投加点编码只能包含字母、数字、下划线和中划线")
    existing = con.execute("SELECT id FROM dosing_points WHERE code=?", (payload.code,)).fetchone()
    if existing and int(existing["id"]) != point_id:
        raise HTTPException(409, "投加点编码已存在")
    if payload.process_parameter_group_id is not None:
        params = con.execute("SELECT id FROM process_parameter_groups WHERE id=?", (payload.process_parameter_group_id,)).fetchone()
        if not params:
            raise HTTPException(422, "工艺参数组不存在")
    validate_point_model_selection(con, payload.tp_model_id, "tp_out_response", "出水TP预测模型")
    validate_point_model_selection(con, payload.pac_flow_model_id, "pac_flow_predict", "加药流量预测模型")


def validate_point_model_selection(con, model_id: int | None, model_kind: str, label: str) -> None:
    if model_id is None:
        return
    model = con.execute(
        "SELECT id,model_kind,trained_at FROM model_projects WHERE id=?",
        (model_id,),
    ).fetchone()
    if not model:
        raise HTTPException(422, f"{label}不存在")
    if model["model_kind"] != model_kind:
        raise HTTPException(422, f"{label}类型不匹配")
    if not model["trained_at"]:
        raise HTTPException(422, f"{label}尚未训练完成")


def resolve_process_line_id(con, process_line_id: int | None) -> int:
    if process_line_id is not None:
        return process_line_id
    row = con.execute("SELECT id FROM process_lines ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise HTTPException(422, "系统未配置默认工艺线")
    return int(row["id"])


def create_default_point_tags(con, point_id: int, point_code: str) -> None:
    now = utc_now_iso()
    con.executemany(
        """
        INSERT INTO sensor_tags(
            dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,min_value,max_value,source,enabled
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        [(point_id, f"{point_code}_{tag_type}", tag_type, name, unit, stale, max_stale, min_v, max_v, "s7comm", 1) for tag_type, name, unit, stale, max_stale, min_v, max_v in TAG_DEFS],
    )
    con.executemany(
        """
        INSERT INTO sensor_tags(
            dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,min_value,max_value,source,enabled,history_enabled
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [(point_id, f"{point_code}_{tag_type}", tag_type, name, unit, stale, max_stale, min_v, max_v, "computed", 1, 1) for tag_type, name, unit, stale, max_stale, min_v, max_v in VIRTUAL_TAG_DEFS],
    )
    defaults = {"Q": 0, "TP_BEFORE": 0, "TP_OUT": 0, "PH": 7.2, "PAC_ACTUAL": 0, "TURBIDITY": 0, "BIO_DO1": 2, "BIO_DO2": 2, "BIO_MLSS1": 3000, "BIO_MLSS2": 3000}
    for tag_type, default_value in defaults.items():
        tag = con.execute("SELECT id, unit FROM sensor_tags WHERE dosing_point_id=? AND tag_type=?", (point_id, tag_type)).fetchone()
        con.execute(
            "INSERT INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source) VALUES(?,?,?,?,?,?,?)",
            (tag["id"], default_value, tag["unit"], now, now, "good", "s7comm"),
        )


def rename_point_tag_codes(con, point_id: int, new_code: str) -> None:
    tags = con.execute("SELECT id, tag_type FROM sensor_tags WHERE dosing_point_id=?", (point_id,)).fetchall()
    for tag in tags:
        con.execute("UPDATE sensor_tags SET tag_code=? WHERE id=?", (f"{new_code}_{tag['tag_type']}", tag["id"]))


def ensure_virtual_point_tags(con, point_id: int, point_code: str) -> None:
    existing = {row["tag_type"] for row in con.execute("SELECT tag_type FROM sensor_tags WHERE dosing_point_id=?", (point_id,)).fetchall()}
    missing = [(tag_type, name, unit, stale, max_stale, min_v, max_v) for tag_type, name, unit, stale, max_stale, min_v, max_v in VIRTUAL_TAG_DEFS if tag_type not in existing]
    if missing:
        con.executemany(
            """
            INSERT INTO sensor_tags(
                dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,min_value,max_value,source,enabled,history_enabled
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [(point_id, f"{point_code}_{tag_type}", tag_type, name, unit, stale, max_stale, min_v, max_v, "computed", 1, 1) for tag_type, name, unit, stale, max_stale, min_v, max_v in missing],
        )
