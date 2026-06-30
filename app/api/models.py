from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.common import row_to_dict
from app.database import db_session, dumps_json, loads_json, utc_now_iso
from app.schemas import (
    ModelDeployIn,
    ModelProjectCreate,
    ModelProjectUpdate,
    ModelPublishIn,
    ModelSampleBulkDeleteIn,
    ModelSampleImportIn,
)
from app.services.audit import audit
from app.services.model_training import (
    SUPPORTED_MODEL_KINDS,
    current_model_feature_schema,
    decode_model_sample_csv_payload,
    import_model_csv_samples,
    normalize_training_config,
    sync_model_feature_schema,
    target_definition_for_kind,
    train_model_project_artifact,
)
from app.services.recommendation import recalculate_all


router = APIRouter()


@router.get("/api/models")
def models() -> dict[str, Any]:
    with db_session() as con:
        rows = model_project_rows(con)
        points = [row_to_dict(row) for row in con.execute("SELECT id,name,code FROM dosing_points ORDER BY display_order").fetchall()]
    return {"models": rows, "points": points}


@router.post("/api/models")
def create_model_project(payload: ModelProjectCreate) -> dict[str, Any]:
    now = utc_now_iso()
    with db_session() as con:
        point = con.execute("SELECT id FROM dosing_points WHERE id=?", (payload.dosing_point_id,)).fetchone()
        if not point:
            raise HTTPException(422, "训练投加点不存在")
        schema = current_model_feature_schema(con, payload.dosing_point_id, payload.model_kind)
        training_config = normalize_training_config(payload.training_config, payload.model_kind, schema)
        try:
            cur = con.execute(
                """
                INSERT INTO model_projects(
                    name,dosing_point_id,model_kind,status,sample_interval_minutes,feature_schema_json,training_config_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload.name.strip(),
                    payload.dosing_point_id,
                    payload.model_kind,
                    "draft",
                    payload.sample_interval_minutes,
                    dumps_json(schema),
                    dumps_json(training_config),
                    now,
                    now,
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(409, "模型名称已存在") from exc
            raise
        model_id = int(cur.lastrowid)
        audit(con, "local", "create", "model_project", str(model_id), payload.model_dump())
        model = model_project_detail(con, model_id)["model"]
    return {"ok": True, "model": model}


@router.get("/api/models/{model_id}")
def model_project_detail_api(
    model_id: int,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> dict[str, Any]:
    sample_start, sample_end = validate_model_sample_range(start, end)
    with db_session() as con:
        return model_project_detail(con, model_id, sample_start, sample_end)


@router.put("/api/models/{model_id}")
def update_model_project(model_id: int, payload: ModelProjectUpdate) -> dict[str, Any]:
    with db_session() as con:
        model = model_project_or_404(con, model_id)
        schema = sync_model_feature_schema(con, model)
        training_config = normalize_training_config(payload.training_config, model["model_kind"], schema)
        try:
            con.execute(
                """
                UPDATE model_projects
                SET name=?, sample_interval_minutes=?, training_config_json=?, updated_at=?
                WHERE id=?
                """,
                (payload.name.strip(), payload.sample_interval_minutes, dumps_json(training_config), utc_now_iso(), model_id),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(409, "模型名称已存在") from exc
            raise
        audit(con, "local", "update", "model_project", str(model_id), payload.model_dump())
        return {"ok": True, "model": model_project_detail(con, model_id)}


@router.delete("/api/models/{model_id}")
def delete_model_project(model_id: int) -> dict[str, Any]:
    with db_session() as con:
        model = model_project_or_404(con, model_id)
        con.execute("DELETE FROM model_projects WHERE id=?", (model_id,))
        audit(con, "local", "delete", "model_project", str(model_id), {"name": model["name"]})
    return {"ok": True}


@router.post("/api/models/{model_id}/recording/start")
def start_model_recording(model_id: int) -> dict[str, Any]:
    raise HTTPException(410, "模型实时记录功能已停用，请通过 CSV 表格导入训练样本")


@router.post("/api/models/{model_id}/recording/stop")
def stop_model_recording(model_id: int) -> dict[str, Any]:
    raise HTTPException(410, "模型实时记录功能已停用，请通过 CSV 表格导入训练样本")


@router.post("/api/models/{model_id}/samples/record")
def record_model_sample(model_id: int) -> dict[str, Any]:
    raise HTTPException(410, "模型实时记录功能已停用，请通过 CSV 表格导入训练样本")


@router.delete("/api/models/{model_id}/samples/{sample_id}")
def delete_model_sample(model_id: int, sample_id: int) -> dict[str, Any]:
    with db_session() as con:
        row = con.execute(
            "SELECT id FROM model_training_samples WHERE id=? AND model_project_id=?",
            (sample_id, model_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "训练样本不存在")
        con.execute("DELETE FROM model_training_samples WHERE id=?", (sample_id,))
        audit(con, "local", "delete", "model_training_sample", str(sample_id), {"model_id": model_id})
    return {"ok": True}


@router.post("/api/models/{model_id}/samples/bulk-delete")
def delete_model_samples(model_id: int, payload: ModelSampleBulkDeleteIn) -> dict[str, Any]:
    sample_ids = sorted({int(sample_id) for sample_id in payload.sample_ids})
    placeholders = ",".join("?" for _ in sample_ids)
    with db_session() as con:
        model_project_or_404(con, model_id)
        cur = con.execute(
            f"DELETE FROM model_training_samples WHERE model_project_id=? AND id IN ({placeholders})",
            [model_id, *sample_ids],
        )
        audit(con, "local", "bulk_delete", "model_training_sample", str(model_id), {"count": cur.rowcount})
    return {"ok": True, "deleted": cur.rowcount}


@router.delete("/api/models/{model_id}/samples")
def clear_model_samples(model_id: int) -> dict[str, Any]:
    with db_session() as con:
        model_project_or_404(con, model_id)
        cur = con.execute("DELETE FROM model_training_samples WHERE model_project_id=?", (model_id,))
        con.execute(
            """
            UPDATE model_projects
            SET recording_enabled=0,status=CASE WHEN status='published' THEN 'published' WHEN trained_at IS NOT NULL THEN 'ready' ELSE 'draft' END,
                last_record_at=NULL,updated_at=?
            WHERE id=?
            """,
            (utc_now_iso(), model_id),
        )
        audit(con, "local", "clear", "model_training_sample", str(model_id), {"count": cur.rowcount})
    return {"ok": True, "deleted": cur.rowcount}


@router.post("/api/models/{model_id}/samples/import")
def import_model_samples(model_id: int, payload: ModelSampleImportIn) -> dict[str, Any]:
    csv_text = decode_model_sample_csv_payload(payload)
    with db_session() as con:
        model = model_project_or_404(con, model_id)
        result = import_model_csv_samples(con, model, csv_text)
        audit(con, "local", "import", "model_training_sample", str(model_id), result)
        return {"ok": True, **result}


@router.get("/api/models/{model_id}/samples.csv")
def export_model_samples(model_id: int) -> StreamingResponse:
    with db_session() as con:
        detail = model_project_detail(con, model_id)
    model = detail["model"]
    schema = model.get("feature_schema", [])
    _target_name, target_key, target_header = target_definition_for_kind(model["model_kind"])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["时间", *[(item.get("tag_code") or item["label"]) for item in schema], target_header])
    for row in detail["samples"]:
        values = row.get("values", {})
        writer.writerow([row["sample_time"], *[model_csv_number(values.get(item["key"])) for item in schema], model_csv_number(values.get(target_key))])
    return StreamingResponse(
        iter(["\ufeff" + buf.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename=model_{model_id}_samples.csv"},
    )


def model_csv_number(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    return value


@router.post("/api/models/{model_id}/train")
def train_model_project(model_id: int) -> dict[str, Any]:
    with db_session() as con:
        model = model_project_or_404(con, model_id)
        trained = train_model_project_artifact(con, model)
        audit(con, "local", "train", "model_project", str(model_id), {"samples": trained["metrics"]["samples"]})
        return {"ok": True, "model": model_project_detail(con, model_id)["model"]}


@router.post("/api/models/{model_id}/deploy")
def deploy_model_project(model_id: int, payload: ModelDeployIn) -> dict[str, Any]:
    with db_session() as con:
        model = model_project_or_404(con, model_id)
        if payload.enabled and not model["trained_at"]:
            raise HTTPException(409, "请先完成模型训练后再投用")
        now = utc_now_iso()
        if payload.enabled:
            con.execute(
                "UPDATE model_projects SET status='ready',recording_enabled=0,updated_at=? WHERE dosing_point_id=? AND model_kind=? AND status='published'",
                (now, model["dosing_point_id"], model["model_kind"]),
            )
            status = "published"
            published_at = now
            published_by = payload.actor
        else:
            status = "ready" if model["trained_at"] else "draft"
            published_at = None
            published_by = None
        con.execute(
            """
            UPDATE model_projects
            SET status=?, recording_enabled=0, published_by=?, published_at=?, updated_at=?
            WHERE id=?
            """,
            (status, published_by, published_at, now, model_id),
        )
        audit(con, payload.actor, "deploy" if payload.enabled else "undeploy", "model_project", str(model_id), payload.model_dump())
        recalculate_all(con)
        return {"ok": True, "model": model_project_detail(con, model_id)["model"]}


@router.get("/api/models/{model_id}/artifact")
def download_model_artifact(model_id: int) -> StreamingResponse:
    with db_session() as con:
        model = model_project_or_404(con, model_id)
        if not model["trained_at"]:
            raise HTTPException(409, "模型尚未训练完成")
        artifact = loads_json(model["artifact_json"], {})
    if artifact.get("format") == "ai_pac_tp_forecast_v1" and artifact.get("booster_model"):
        content = artifact["booster_model"]
        media_type = "text/plain; charset=utf-8"
        filename = artifact.get("file_name") or f"model_{model_id}.lgb.txt"
    elif artifact.get("format") == "ai_pac_tp_forecast_v2" and artifact.get("booster_models"):
        content = dumps_json(artifact)
        media_type = "application/json; charset=utf-8"
        filename = artifact.get("file_name") or f"model_{model_id}_artifact.json"
    elif artifact.get("format") in {"ai_pac_tp_forecast_v3", "ai_pac_flow_predict_v1"} and artifact.get("booster_model"):
        content = dumps_json(artifact)
        media_type = "application/json; charset=utf-8"
        filename = artifact.get("file_name") or f"model_{model_id}_artifact.json"
    else:
        content = dumps_json(artifact)
        media_type = "application/json; charset=utf-8"
        filename = f"model_{model_id}_artifact.json"
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/api/models/publish")
def publish_model(payload: ModelPublishIn) -> dict[str, Any]:
    raise HTTPException(410, "旧版 K_AI 模型发布接口已删除")


def model_feature_schema(con, dosing_point_id: int) -> list[dict[str, Any]]:
    return current_model_feature_schema(con, dosing_point_id)


def model_project_or_404(con, model_id: int):
    row = con.execute("SELECT * FROM model_projects WHERE id=?", (model_id,)).fetchone()
    if not row:
        raise HTTPException(404, "训练模型不存在")
    if row["model_kind"] not in SUPPORTED_MODEL_KINDS:
        raise HTTPException(422, "模型类型不支持")
    return row


def model_project_rows(con) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT mp.id,mp.name,mp.model_kind,mp.dosing_point_id,mp.status,mp.recording_enabled,mp.last_record_at,
            mp.trained_at,mp.published_by,mp.published_at,mp.created_at,mp.updated_at,mp.sample_interval_minutes,mp.metrics_json,
            dp.name AS dosing_point_name, dp.code AS dosing_point_code,
            (SELECT COUNT(*) FROM model_training_samples ms WHERE ms.model_project_id=mp.id) AS sample_count
        FROM model_projects mp
        JOIN dosing_points dp ON dp.id=mp.dosing_point_id
        WHERE mp.model_kind IN ('tp_out_response','pac_flow_predict')
        ORDER BY mp.updated_at DESC, mp.id DESC
        """
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def model_project_summary_rows(con) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT mp.id,mp.name,mp.model_kind,mp.dosing_point_id,mp.status,mp.recording_enabled,
            mp.trained_at,mp.published_at,mp.sample_interval_minutes,mp.metrics_json,
            dp.name AS dosing_point_name,
            (SELECT COUNT(*) FROM model_training_samples ms WHERE ms.model_project_id=mp.id) AS sample_count
        FROM model_projects mp
        JOIN dosing_points dp ON dp.id=mp.dosing_point_id
        WHERE mp.model_kind IN ('tp_out_response','pac_flow_predict')
        ORDER BY CASE mp.status WHEN 'published' THEN 0 WHEN 'recording' THEN 1 WHEN 'ready' THEN 2 ELSE 3 END,
                 mp.updated_at DESC,mp.id DESC
        """
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def validate_model_sample_range(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    def normalize(value: str | None, label: str) -> str | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).replace(microsecond=0).isoformat()
        except ValueError as exc:
            raise HTTPException(422, f"{label}时间格式无效") from exc

    sample_start = normalize(start, "开始")
    sample_end = normalize(end, "结束")
    if sample_start and sample_end and sample_start > sample_end:
        raise HTTPException(422, "开始时间不能晚于结束时间")
    return sample_start, sample_end


def model_project_detail(
    con,
    model_id: int,
    sample_start: str | None = None,
    sample_end: str | None = None,
) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT mp.*, dp.name AS dosing_point_name, dp.code AS dosing_point_code,
            (SELECT COUNT(*) FROM model_training_samples ms WHERE ms.model_project_id=mp.id) AS sample_count
        FROM model_projects mp
        JOIN dosing_points dp ON dp.id=mp.dosing_point_id
        WHERE mp.id=?
        """,
        (model_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "训练模型不存在")
    model = row_to_dict(row)
    model["feature_schema"] = sync_model_feature_schema(con, row)
    raw_training_config = model.get("training_config", {})
    model["training_config"] = normalize_training_config(raw_training_config, model["model_kind"], model["feature_schema"])
    if raw_training_config != model["training_config"]:
        con.execute(
            "UPDATE model_projects SET training_config_json=?,updated_at=? WHERE id=?",
            (dumps_json(model["training_config"]), utc_now_iso(), model_id),
        )
    where = "WHERE model_project_id=?"
    params: list[Any] = [model_id]
    if sample_start:
        where += " AND sample_time>=?"
        params.append(sample_start)
    if sample_end:
        where += " AND sample_time<=?"
        params.append(sample_end)
    samples = []
    for sample in con.execute(
        f"SELECT * FROM model_training_samples {where} ORDER BY sample_time DESC,id DESC",
        params,
    ).fetchall():
        item = row_to_dict(sample)
        item["target_value"] = item.get("target_value", item.pop("k_ai", None))
        samples.append(item)
    return {
        "model": model,
        "columns": model.get("feature_schema", []),
        "samples": samples,
        "query": {"start": sample_start, "end": sample_end},
    }
