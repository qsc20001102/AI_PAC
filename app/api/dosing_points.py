from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.common import row_to_dict
from app.database import db_session, infer_process_source_tags, loads_json, utc_now_iso
from app.schemas import ControlConfigUpdate, DosingPointCreate, DosingPointUpdate, PacConfigUpdate
from app.services.audit import audit
from app.services.recommendation import calculate_for_point


router = APIRouter()


PROCESS_SOURCE_TAG_FIELDS = [
    "in_flow_tag_id",
    "in_tp_tag_id",
    "out_flow_tag_id",
    "out_tp_tag_id",
    "zone_flow_tag_id",
    "reflux_flow_1_tag_id",
    "reflux_flow_2_tag_id",
    "po4_tag_id",
    "pac_flow_tag_id",
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
            SELECT dp.*, pl.name AS process_line_name, pl.line_code, pa.name AS area_name, p.name AS plant_name
            FROM dosing_points dp
            JOIN process_lines pl ON pl.id=dp.process_line_id
            JOIN process_areas pa ON pa.id=pl.area_id
            JOIN plants p ON p.id=pa.plant_id
            ORDER BY dp.display_order
            """
        ).fetchall()
        result = []
        for row in rows:
            item = row_to_dict(row)
            item["pac_config"] = row_to_dict(con.execute("SELECT * FROM pac_configs WHERE dosing_point_id=?", (row["id"],)).fetchone())
            item["control_config"] = row_to_dict(con.execute("SELECT * FROM control_configs WHERE dosing_point_id=?", (row["id"],)).fetchone())
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
                process_line_id,name,code,enabled,flow_source,phosphorus_source,feedback_source,
                in_flow_tag_id,in_tp_tag_id,out_flow_tag_id,out_tp_tag_id,zone_flow_tag_id,
                in_flow_weight,reflux_flow_1_tag_id,reflux_flow_2_tag_id,po4_tag_id,pac_flow_tag_id,
                chemical_group_id,process_parameter_group_id,source_configured,manual_contribution_factor,
                display_order,write_enabled
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                process_line_id,
                payload.name,
                payload.code,
                int(payload.enabled),
                payload.flow_source or "line",
                payload.phosphorus_source or "po4_priority",
                payload.feedback_source or "line_out",
                payload.in_flow_tag_id,
                payload.in_tp_tag_id,
                payload.out_flow_tag_id,
                payload.out_tp_tag_id,
                payload.zone_flow_tag_id,
                payload.in_flow_weight,
                payload.reflux_flow_1_tag_id,
                payload.reflux_flow_2_tag_id,
                payload.po4_tag_id,
                payload.pac_flow_tag_id,
                payload.chemical_group_id,
                payload.process_parameter_group_id,
                int(any(getattr(payload, field) is not None for field in PROCESS_SOURCE_TAG_FIELDS)),
                payload.manual_contribution_factor if payload.manual_contribution_factor is not None else 1.0,
                display_order,
                int(payload.write_enabled),
            ),
        )
        point_id = int(cur.lastrowid)
        create_default_point_config(con, point_id, payload.code)
        if not any(getattr(payload, field) is not None for field in PROCESS_SOURCE_TAG_FIELDS):
            backfill_point_source_tags(con, point_id)
        assign_default_groups(con, point_id)
        audit(con, "local", "create", "dosing_point", str(point_id), payload.model_dump())
        result = calculate_for_point(con, point_id)
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
        old_code = point["code"]
        con.execute(
            """
            UPDATE dosing_points
            SET process_line_id=?, name=?, code=?, enabled=?, flow_source=?, phosphorus_source=?, feedback_source=?,
                in_flow_tag_id=?, in_tp_tag_id=?, out_flow_tag_id=?, out_tp_tag_id=?, zone_flow_tag_id=?,
                in_flow_weight=?, reflux_flow_1_tag_id=?, reflux_flow_2_tag_id=?, po4_tag_id=?, pac_flow_tag_id=?,
                chemical_group_id=?, process_parameter_group_id=?, source_configured=1,
                manual_contribution_factor=?, display_order=?, write_enabled=?
            WHERE id=?
            """,
            (
                process_line_id,
                payload.name,
                payload.code,
                int(payload.enabled),
                payload.flow_source or point["flow_source"],
                payload.phosphorus_source or point["phosphorus_source"],
                payload.feedback_source or point["feedback_source"],
                payload.in_flow_tag_id,
                payload.in_tp_tag_id,
                payload.out_flow_tag_id,
                payload.out_tp_tag_id,
                payload.zone_flow_tag_id,
                payload.in_flow_weight,
                payload.reflux_flow_1_tag_id,
                payload.reflux_flow_2_tag_id,
                payload.po4_tag_id,
                payload.pac_flow_tag_id,
                payload.chemical_group_id if payload.chemical_group_id is not None else point["chemical_group_id"],
                payload.process_parameter_group_id if payload.process_parameter_group_id is not None else point["process_parameter_group_id"],
                payload.manual_contribution_factor if payload.manual_contribution_factor is not None else point["manual_contribution_factor"],
                payload.display_order if payload.display_order is not None else point["display_order"],
                int(payload.write_enabled if payload.write_enabled is not None else point["write_enabled"]),
                point_id,
            ),
        )
        if old_code != payload.code:
            rename_point_tag_codes(con, point_id, payload.code)
        audit(con, "local", "update", "dosing_point", str(point_id), payload.model_dump())
        result = calculate_for_point(con, point_id) if payload.enabled else None
    return {"ok": True, "recommendation": result}


@router.delete("/api/dosing-points/{point_id}")
def delete_dosing_point(point_id: int) -> dict[str, Any]:
    with db_session() as con:
        point = con.execute("SELECT * FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not point:
            raise HTTPException(404, "投加点不存在")
        remaining = con.execute("SELECT COUNT(*) FROM dosing_points WHERE id<>?", (point_id,)).fetchone()[0]
        if remaining == 0:
            raise HTTPException(409, "至少保留一个投加点")
        con.execute("UPDATE alarms SET dosing_point_id=NULL WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM simulation_runs WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM plc_write_tests WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM plc_tag_mappings WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM model_shadow_results WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM recommendations WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM sensor_tags WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM pac_configs WHERE dosing_point_id=?", (point_id,))
        con.execute("DELETE FROM control_configs WHERE dosing_point_id=?", (point_id,))
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
            "point": row_to_dict(point),
            "pac_config": row_to_dict(con.execute("SELECT * FROM pac_configs WHERE dosing_point_id=?", (point_id,)).fetchone()),
            "control_config": row_to_dict(con.execute("SELECT * FROM control_configs WHERE dosing_point_id=?", (point_id,)).fetchone()),
        }


@router.put("/api/dosing-points/{point_id}/pac-config")
def update_pac_config(point_id: int, payload: PacConfigUpdate) -> dict[str, Any]:
    with db_session() as con:
        exists = con.execute("SELECT id FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "投加点不存在")
        con.execute(
            """
            UPDATE pac_configs
            SET pac_density_kg_l=?, al2o3_fraction=?, effective_factor=?, al_p_ratio=?, batch_id=?, updated_at=?
            WHERE dosing_point_id=?
            """,
            (
                payload.pac_density_kg_l,
                payload.al2o3_fraction,
                payload.effective_factor,
                payload.al_p_ratio,
                payload.batch_id,
                utc_now_iso(),
                point_id,
            ),
        )
        audit(con, "local", "update", "pac_config", str(point_id), payload.model_dump())
        result = calculate_for_point(con, point_id)
    return {"ok": True, "recommendation": result}


@router.put("/api/dosing-points/{point_id}/control-config")
def update_control_config(point_id: int, payload: ControlConfigUpdate) -> dict[str, Any]:
    if payload.pac_max_l_h < payload.pac_min_l_h:
        raise HTTPException(422, "最大加药量必须大于等于最小加药量")
    if payload.feedback_max < payload.feedback_min:
        raise HTTPException(422, "反馈上限必须大于等于反馈下限")
    with db_session() as con:
        exists = con.execute("SELECT id FROM dosing_points WHERE id=?", (point_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "投加点不存在")
        con.execute(
            """
            UPDATE control_configs
            SET tp_target_mg_l=?, tp_safe_target_mg_l=?, tp_limit_mg_l=?, pac_min_l_h=?, pac_max_l_h=?,
                single_step_change_ratio=?, max_increase_l_h_per_min=?, max_decrease_l_h_per_min=?,
                lag_minutes=?, feedback_kp=?, feedback_min=?, feedback_max=?, feedback_window_minutes=?, updated_at=?
            WHERE dosing_point_id=?
            """,
            (
                payload.tp_target_mg_l,
                payload.tp_safe_target_mg_l,
                payload.tp_limit_mg_l,
                payload.pac_min_l_h,
                payload.pac_max_l_h,
                payload.single_step_change_ratio,
                payload.max_increase_l_h_per_min,
                payload.max_decrease_l_h_per_min,
                payload.lag_minutes,
                payload.feedback_kp,
                payload.feedback_min,
                payload.feedback_max,
                payload.feedback_window_minutes,
                utc_now_iso(),
                point_id,
            ),
        )
        audit(con, "local", "update", "control_config", str(point_id), payload.model_dump())
        result = calculate_for_point(con, point_id)
    return {"ok": True, "recommendation": result}


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


def validate_process_source_tags(
    con,
    payload: DosingPointCreate | DosingPointUpdate,
    point_id: int | None = None,
) -> None:
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
    tags = con.execute(
        "SELECT id, tag_code, tag_type FROM sensor_tags WHERE dosing_point_id=? ORDER BY id",
        (point_id,),
    ).fetchall()
    values = infer_process_source_tags(tags)
    con.execute(
        """
        UPDATE dosing_points
        SET in_flow_tag_id=?, in_tp_tag_id=?, out_tp_tag_id=?, po4_tag_id=?, pac_flow_tag_id=?, source_configured=1
        WHERE id=?
        """,
        (
            values["in_flow_tag_id"],
            values["in_tp_tag_id"],
            values["out_tp_tag_id"],
            values["po4_tag_id"],
            values["pac_flow_tag_id"],
            point_id,
        ),
    )


def assign_default_groups(con, point_id: int) -> None:
    chemical = con.execute("SELECT id FROM chemical_groups ORDER BY id LIMIT 1").fetchone()
    params = con.execute("SELECT id FROM process_parameter_groups ORDER BY id LIMIT 1").fetchone()
    if chemical:
        con.execute("UPDATE dosing_points SET chemical_group_id=COALESCE(chemical_group_id, ?) WHERE id=?", (chemical["id"], point_id))
    if params:
        con.execute(
            "UPDATE dosing_points SET process_parameter_group_id=COALESCE(process_parameter_group_id, ?) WHERE id=?",
            (params["id"], point_id),
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
    if payload.chemical_group_id is not None:
        chemical = con.execute("SELECT id FROM chemical_groups WHERE id=?", (payload.chemical_group_id,)).fetchone()
        if not chemical:
            raise HTTPException(422, "药剂组不存在")
    if payload.process_parameter_group_id is not None:
        params = con.execute(
            "SELECT id FROM process_parameter_groups WHERE id=?",
            (payload.process_parameter_group_id,),
        ).fetchone()
        if not params:
            raise HTTPException(422, "工艺参数组不存在")


def resolve_process_line_id(con, process_line_id: int | None) -> int:
    if process_line_id is not None:
        return process_line_id
    row = con.execute("SELECT id FROM process_lines ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise HTTPException(422, "系统未配置默认工艺线")
    return int(row["id"])


def create_default_point_config(con, point_id: int, point_code: str) -> None:
    now = utc_now_iso()
    con.execute(
        """
        INSERT INTO pac_configs(
            dosing_point_id,pac_density_kg_l,al2o3_fraction,effective_factor,al_p_ratio,batch_id,updated_at
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (point_id, 1.20, 0.018, 0.90, 2.50, "新建批次", now),
    )
    con.execute(
        """
        INSERT INTO control_configs(
            dosing_point_id,tp_target_mg_l,tp_safe_target_mg_l,tp_limit_mg_l,pac_min_l_h,pac_max_l_h,
            single_step_change_ratio,max_increase_l_h_per_min,max_decrease_l_h_per_min,lag_minutes,
            feedback_kp,feedback_min,feedback_max,feedback_window_minutes,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (point_id, 0.18, 0.16, 0.30, 0.0, 60.0, 0.15, 3.0, 2.0, 60, 0.25, 0.80, 1.30, 120, now),
    )
    tag_defs = [
        ("Q", "流量", "m3/h", 3, 15, 0, 4000),
        ("PO4_P", "投加前 PO4-P", "mg/L", 10, 60, 0, 20),
        ("TP_BEFORE", "投加前 TP", "mg/L", 20, 120, 0, 20),
        ("TP_OUT", "出水 TP", "mg/L", 30, 180, 0, 5),
        ("PH", "pH", "", 10, 60, 3, 11),
        ("PAC_ACTUAL", "PAC 实际", "L/h", 10, 60, 0, 200),
        ("TURBIDITY", "浊度", "NTU", 30, 120, 0, 300),
    ]
    con.executemany(
        """
        INSERT INTO sensor_tags(
            dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,min_value,max_value,source,enabled
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (point_id, f"{point_code}_{tag_type}", tag_type, name, unit, stale, max_stale, min_v, max_v, "manual", 1)
            for tag_type, name, unit, stale, max_stale, min_v, max_v in tag_defs
        ],
    )
    for tag_type, default_value in {
        "Q": 0,
        "PO4_P": 0,
        "TP_BEFORE": 0,
        "TP_OUT": 0,
        "PH": 7.2,
        "PAC_ACTUAL": 0,
        "TURBIDITY": 0,
    }.items():
        tag = con.execute(
            "SELECT id, unit FROM sensor_tags WHERE dosing_point_id=? AND tag_type=?",
            (point_id, tag_type),
        ).fetchone()
        con.execute(
            """
            INSERT INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source)
            VALUES(?,?,?,?,?,?,?)
            """,
            (tag["id"], default_value, tag["unit"], now, now, "good", "manual"),
        )

def rename_point_tag_codes(con, point_id: int, new_code: str) -> None:
    tags = con.execute("SELECT id, tag_type FROM sensor_tags WHERE dosing_point_id=?", (point_id,)).fetchall()
    for tag in tags:
        con.execute(
            "UPDATE sensor_tags SET tag_code=? WHERE id=?",
            (f"{new_code}_{tag['tag_type']}", tag["id"]),
        )
