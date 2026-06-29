from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.common import row_to_dict
from app.database import db_session, utc_now_iso
from app.schemas import ChemicalGroupIn, ProcessParameterGroupIn
from app.services.audit import audit
from app.services.recommendation import recalculate_all


router = APIRouter()


@router.get("/api/process-lines")
def process_lines() -> list[dict[str, Any]]:
    with db_session() as con:
        rows = con.execute(
            """
            SELECT pl.*, pa.name AS area_name, p.name AS plant_name
            FROM process_lines pl
            JOIN process_areas pa ON pa.id=pl.area_id
            JOIN plants p ON p.id=pa.plant_id
            ORDER BY pa.id, pl.id
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@router.get("/api/chemical-groups")
def chemical_groups() -> list[dict[str, Any]]:
    with db_session() as con:
        rows = con.execute("SELECT * FROM chemical_groups ORDER BY id").fetchall()
    return [row_to_dict(row) for row in rows]


@router.post("/api/chemical-groups")
def create_chemical_group(payload: ChemicalGroupIn) -> dict[str, Any]:
    with db_session() as con:
        cur = con.execute(
            """
            INSERT INTO chemical_groups(batch_id,pac_density_kg_l,effective_factor,al_p_ratio,updated_at)
            VALUES(?,?,?,?,?)
            """,
            (payload.batch_id.strip(), payload.pac_density_kg_l, payload.effective_factor, payload.al_p_ratio, utc_now_iso()),
        )
        group_id = int(cur.lastrowid)
        audit(con, "local", "create", "chemical_group", str(group_id), payload.model_dump())
    return {"ok": True, "id": group_id}


@router.put("/api/chemical-groups/{group_id}")
def update_chemical_group(group_id: int, payload: ChemicalGroupIn) -> dict[str, Any]:
    with db_session() as con:
        exists = con.execute("SELECT id FROM chemical_groups WHERE id=?", (group_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "药剂组不存在")
        con.execute(
            """
            UPDATE chemical_groups
            SET batch_id=?, pac_density_kg_l=?, effective_factor=?, al_p_ratio=?, updated_at=?
            WHERE id=?
            """,
            (payload.batch_id.strip(), payload.pac_density_kg_l, payload.effective_factor, payload.al_p_ratio, utc_now_iso(), group_id),
        )
        audit(con, "local", "update", "chemical_group", str(group_id), payload.model_dump())
        recalculate_all(con)
    return {"ok": True}


@router.delete("/api/chemical-groups/{group_id}")
def delete_chemical_group(group_id: int) -> dict[str, Any]:
    with db_session() as con:
        exists = con.execute("SELECT id FROM chemical_groups WHERE id=?", (group_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "药剂组不存在")
        remaining = con.execute("SELECT id FROM chemical_groups WHERE id<>? ORDER BY id LIMIT 1", (group_id,)).fetchone()
        if not remaining:
            raise HTTPException(409, "至少保留一个药剂组")
        con.execute("UPDATE dosing_points SET chemical_group_id=? WHERE chemical_group_id=?", (remaining["id"], group_id))
        con.execute("DELETE FROM chemical_groups WHERE id=?", (group_id,))
        audit(con, "local", "delete", "chemical_group", str(group_id), {"reassigned_to": remaining["id"]})
        recalculate_all(con)
    return {"ok": True, "deleted_id": group_id}


@router.get("/api/process-parameter-groups")
def process_parameter_groups() -> list[dict[str, Any]]:
    with db_session() as con:
        rows = con.execute("SELECT * FROM process_parameter_groups ORDER BY id").fetchall()
    return [row_to_dict(row) for row in rows]


def validate_process_parameter_group_payload(payload: ProcessParameterGroupIn) -> None:
    if payload.tp_target_mg_l > payload.tp_limit_mg_l:
        raise HTTPException(422, "目标 TP 不能高于出水限制")
    if payload.pac_max_l_h < payload.pac_min_l_h:
        raise HTTPException(422, "最大 L/h 必须大于等于最小 L/h")
    if payload.feedback_max < payload.feedback_min:
        raise HTTPException(422, "反馈上限必须大于等于反馈下限")


def process_parameter_group_values(payload: ProcessParameterGroupIn) -> tuple[Any, ...]:
    return (
        payload.name.strip(),
        payload.tp_target_mg_l,
        payload.tp_limit_mg_l,
        payload.pac_min_l_h,
        payload.pac_max_l_h,
        payload.calculation_interval_seconds,
        payload.lag_minutes,
        payload.feedback_kp,
        payload.feedback_min,
        payload.feedback_max,
        payload.feedback_window_minutes,
        utc_now_iso(),
    )


@router.post("/api/process-parameter-groups")
def create_process_parameter_group(payload: ProcessParameterGroupIn) -> dict[str, Any]:
    validate_process_parameter_group_payload(payload)
    with db_session() as con:
        cur = con.execute(
            """
            INSERT INTO process_parameter_groups(
                name,tp_target_mg_l,tp_limit_mg_l,pac_min_l_h,pac_max_l_h,calculation_interval_seconds,
                lag_minutes,feedback_kp,feedback_min,feedback_max,feedback_window_minutes,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            process_parameter_group_values(payload),
        )
        group_id = int(cur.lastrowid)
        audit(con, "local", "create", "process_parameter_group", str(group_id), payload.model_dump())
    return {"ok": True, "id": group_id}


@router.put("/api/process-parameter-groups/{group_id}")
def update_process_parameter_group(group_id: int, payload: ProcessParameterGroupIn) -> dict[str, Any]:
    validate_process_parameter_group_payload(payload)
    with db_session() as con:
        exists = con.execute("SELECT id FROM process_parameter_groups WHERE id=?", (group_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "参数组不存在")
        con.execute(
            """
            UPDATE process_parameter_groups
            SET name=?, tp_target_mg_l=?, tp_limit_mg_l=?, pac_min_l_h=?, pac_max_l_h=?,
                calculation_interval_seconds=?, lag_minutes=?, feedback_kp=?, feedback_min=?,
                feedback_max=?, feedback_window_minutes=?, updated_at=?
            WHERE id=?
            """,
            (*process_parameter_group_values(payload), group_id),
        )
        audit(con, "local", "update", "process_parameter_group", str(group_id), payload.model_dump())
        recalculate_all(con)
    return {"ok": True}


@router.delete("/api/process-parameter-groups/{group_id}")
def delete_process_parameter_group(group_id: int) -> dict[str, Any]:
    with db_session() as con:
        exists = con.execute("SELECT id FROM process_parameter_groups WHERE id=?", (group_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "参数组不存在")
        remaining = con.execute("SELECT id FROM process_parameter_groups WHERE id<>? ORDER BY id LIMIT 1", (group_id,)).fetchone()
        if not remaining:
            raise HTTPException(409, "至少保留一个参数组")
        con.execute("UPDATE dosing_points SET process_parameter_group_id=? WHERE process_parameter_group_id=?", (remaining["id"], group_id))
        con.execute("DELETE FROM process_parameter_groups WHERE id=?", (group_id,))
        audit(con, "local", "delete", "process_parameter_group", str(group_id), {"reassigned_to": remaining["id"]})
        recalculate_all(con)
    return {"ok": True, "deleted_id": group_id}
