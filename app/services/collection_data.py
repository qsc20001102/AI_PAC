from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.api.common import row_to_dict
from app.database import utc_now_iso
from app.schemas import IngestSampleIn


def data_quality_rows(con) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT st.*, dp.name AS dosing_point_name,
            ss.value, ss.sample_time, ss.receive_time, ss.quality, ss.source AS sample_source
        FROM sensor_tags st
        LEFT JOIN dosing_points dp ON dp.id=st.dosing_point_id
        LEFT JOIN sensor_samples ss ON ss.id = (
            SELECT id FROM sensor_samples WHERE tag_id=st.id ORDER BY sample_time DESC LIMIT 1
        )
        WHERE st.enabled=1
        ORDER BY CASE WHEN st.dosing_point_id IS NULL THEN 0 ELSE 1 END, dp.display_order, st.id
        """
    ).fetchall()
    now = datetime.now()
    result = []
    for row in rows:
        item = row_to_dict(row)
        use_realtime = row["last_value_text"] is not None and row["last_read_at"] is not None
        value = row["last_value_text"] if use_realtime else row["value"]
        timestamp = row["last_read_at"] if use_realtime else row["sample_time"]
        quality = row["last_quality"] if use_realtime else row["quality"]
        source = row["source"] if use_realtime else row["sample_source"]
        item["value"] = value
        item["sample_time"] = timestamp
        item["receive_time"] = timestamp if use_realtime else row["receive_time"]
        item["quality"] = quality
        item["sample_source"] = source
        sample_time = datetime.fromisoformat(timestamp) if timestamp else None
        age = (now - sample_time).total_seconds() / 60 if sample_time else None
        if quality != "good" or source == "manual":
            status = "bad"
        elif age is None:
            status = "stale"
        elif age <= row["stale_minutes"]:
            status = "fresh"
        elif age <= row["max_stale_minutes"]:
            status = "delayed"
        else:
            status = "stale"
        item["status"] = status
        item["age_minutes"] = round(age, 1) if age is not None else None
        result.append(item)
    return result


def write_ingested_samples(con, samples: list[IngestSampleIn]) -> tuple[int, set[int], list[str]]:
    written = 0
    affected: set[int] = set()
    errors: list[str] = []
    now_iso = utc_now_iso()
    for item in samples:
        tag = con.execute("SELECT * FROM sensor_tags WHERE tag_code=?", (item.tag_code,)).fetchone()
        if not tag:
            errors.append(f"{item.tag_code}: 标签不存在")
            continue
        sample_time = item.sample_time or now_iso
        receive_time = item.receive_time or now_iso
        unit = item.unit if item.unit is not None else tag["unit"]
        con.execute(
            """
            INSERT OR REPLACE INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source)
            VALUES(?,?,?,?,?,?,?)
            """,
            (tag["id"], item.value, unit, sample_time, receive_time, item.quality, item.source),
        )
        affected.add(int(tag["dosing_point_id"]))
        written += 1
    return written, affected, errors


def refresh_local_simulated_samples(con, force: bool = False) -> None:
    """Keep the bundled local demo live without masking the delayed deep-treatment case."""
    now = datetime.now().replace(second=0, microsecond=0)
    baselines = {
        1: {"Q": 1235.0, "PO4_P": 0.320, "TP_BEFORE": 0.460, "TP_OUT": 0.180, "PH": 7.32, "PAC_ACTUAL": 36.4, "TURBIDITY": 14.0},
        2: {"Q": 988.0, "PO4_P": 0.410, "TP_BEFORE": 0.530, "TP_OUT": 0.240, "PH": 7.28, "PAC_ACTUAL": 28.3, "TURBIDITY": 18.0},
    }
    tags = con.execute(
        """
        SELECT st.*, dp.display_order
        FROM sensor_tags st
        JOIN dosing_points dp ON dp.id=st.dosing_point_id
        WHERE st.dosing_point_id IN (1,2) AND st.enabled=1
        """
    ).fetchall()
    source_row = con.execute("SELECT id FROM data_sources WHERE source_type='simulated' ORDER BY id LIMIT 1").fetchone()
    minute_phase = now.hour * 60 + now.minute
    inserted = 0
    for tag in tags:
        if tag["plc_device_id"] is not None or (tag["data_address"] or "").strip():
            continue
        latest = con.execute(
            """
            SELECT * FROM sensor_samples
            WHERE tag_id=?
            ORDER BY sample_time DESC
            LIMIT 1
            """,
            (tag["id"],),
        ).fetchone()
        if latest and latest["sample_time"] == now.isoformat() and not force:
            continue
        point_id = int(tag["dosing_point_id"])
        base = baselines.get(point_id, {}).get(tag["tag_type"], float(latest["value"]) if latest else 0.0)
        wave = math.sin((minute_phase + tag["id"] * 7) / 18)
        if tag["tag_type"] == "Q":
            value = max(base + wave * 35, 0)
        elif tag["tag_type"] in {"PO4_P", "TP_BEFORE", "TP_OUT"}:
            value = max(base + wave * 0.018, 0.01)
        elif tag["tag_type"] == "PH":
            value = max(min(base + wave * 0.05, 8.5), 6.0)
        elif tag["tag_type"] == "PAC_ACTUAL":
            value = max(base + wave * 0.8, 0)
        elif tag["tag_type"] == "TURBIDITY":
            value = max(base + wave * 1.2, 0)
        else:
            continue
        con.execute(
            """
            INSERT OR IGNORE INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source)
            VALUES(?,?,?,?,?,?,?)
            """,
            (tag["id"], round(value, 4), tag["unit"], now.isoformat(), now.isoformat(), "good", "simulated"),
        )
        inserted += 1
    if source_row:
        con.execute(
            "UPDATE data_sources SET status='running', last_poll_at=?, last_error=NULL WHERE id=?",
            (now.isoformat(), source_row["id"]),
        )
