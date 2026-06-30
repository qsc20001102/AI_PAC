from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.common import row_to_dict
from app.database import db_session, utc_now_iso
from app.schemas import CsvImportIn, IngestBatchIn, IngestSampleIn
from app.services.audit import audit
from app.services.collection_data import refresh_local_simulated_samples, write_ingested_samples
from app.services.recommendation import calculate_for_point, recalculate_all


router = APIRouter()


@router.get("/api/data-sources")
def data_sources() -> list[dict[str, Any]]:
    with db_session() as con:
        rows = con.execute("SELECT * FROM data_sources ORDER BY id").fetchall()
    return [row_to_dict(row) for row in rows]


@router.post("/api/ingest/samples")
def ingest_samples(payload: IngestBatchIn) -> dict[str, Any]:
    if not payload.samples:
        raise HTTPException(422, "samples 不能为空")
    with db_session() as con:
        started_at = utc_now_iso()
        source = con.execute(
            "SELECT id FROM data_sources WHERE name=? LIMIT 1",
            (payload.source_name,),
        ).fetchone()
        source_id = source["id"] if source else None
        if source_id:
            con.execute(
                "UPDATE data_sources SET status='running', last_poll_at=?, last_error=NULL WHERE id=?",
                (started_at, source_id),
            )
        written, affected, errors = write_ingested_samples(con, payload.samples)
        if payload.recalculate:
            for point_id in sorted(affected):
                calculate_for_point(con, point_id)
        finished_at = utc_now_iso()
        con.execute(
            """
            INSERT INTO collector_runs(data_source_id,status,started_at,finished_at,samples_written,message)
            VALUES(?,?,?,?,?,?)
            """,
            (source_id, "success" if not errors else "partial", started_at, finished_at, written, "; ".join(errors[:5]) if errors else "API batch ingested"),
        )
        if source_id:
            con.execute(
                "UPDATE data_sources SET status=?, last_poll_at=?, last_error=? WHERE id=?",
                ("running" if not errors else "warning", finished_at, "; ".join(errors[:5]) if errors else None, source_id),
            )
        audit(con, "api", "ingest", "sensor_samples", payload.source_name, {"written": written, "errors": errors[:10]})
    return {"ok": True, "written": written, "affected_dosing_points": sorted(affected), "errors": errors}


@router.post("/api/import/csv")
def import_csv(payload: CsvImportIn) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(payload.csv_text.strip()))
    required = {"tag_code", "value"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(422, "CSV 至少需要 tag_code,value 列，可选 sample_time,quality,source,unit")
    samples: list[IngestSampleIn] = []
    for idx, row in enumerate(reader, start=2):
        try:
            samples.append(
                IngestSampleIn(
                    tag_code=(row.get("tag_code") or "").strip(),
                    value=float(row.get("value") or ""),
                    unit=(row.get("unit") or None),
                    sample_time=(row.get("sample_time") or None),
                    quality=(row.get("quality") or "good"),
                    source=(row.get("source") or payload.source),
                )
            )
        except Exception as exc:
            raise HTTPException(422, f"CSV 第 {idx} 行解析失败：{exc}") from exc
    return ingest_samples(IngestBatchIn(samples=samples, source_name="外部采集 API", recalculate=payload.recalculate))


@router.post("/api/collector/demo-poll")
def demo_collector_poll() -> dict[str, Any]:
    with db_session() as con:
        source = con.execute("SELECT id FROM data_sources WHERE source_type='simulated' ORDER BY id LIMIT 1").fetchone()
        started_at = utc_now_iso()
        refresh_local_simulated_samples(con, force=True)
        recs = recalculate_all(con)
        finished_at = utc_now_iso()
        con.execute(
            """
            INSERT INTO collector_runs(data_source_id,status,started_at,finished_at,samples_written,message)
            VALUES(?,?,?,?,?,?)
            """,
            (source["id"] if source else None, "success", started_at, finished_at, 14, "本地样例模拟采集轮询完成"),
        )
    return {"ok": True, "recommendations": recs}

