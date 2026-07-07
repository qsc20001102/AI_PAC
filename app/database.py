from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backup"
DB_PATH = DATA_DIR / "ai_pac.sqlite"

LEARNING_SOURCE_TAG_DEFS = [
    ("bio_orp1_tag_id", "BIO_ORP1", "生化池ORP1", "mV", 10, 60, -1000, 1000, 0),
    ("bio_orp2_tag_id", "BIO_ORP2", "生化池ORP2", "mV", 10, 60, -1000, 1000, 0),
    ("bio_orp3_tag_id", "BIO_ORP3", "生化池ORP3", "mV", 10, 60, -1000, 1000, 0),
    ("bio_orp4_tag_id", "BIO_ORP4", "生化池ORP4", "mV", 10, 60, -1000, 1000, 0),
    ("bio_mlss1_tag_id", "BIO_MLSS1", "生化池MLSS1", "mg/L", 30, 120, 0, 20000, 3000),
    ("bio_mlss2_tag_id", "BIO_MLSS2", "生化池MLSS2", "mg/L", 30, 120, 0, 20000, 3000),
]

DEFAULT_UNIT_DOSE_CURVE = [
    {"tp_mg_l": 0.0, "dose_mg_l": 0.0},
    {"tp_mg_l": 0.3, "dose_mg_l": 30.0},
    {"tp_mg_l": 0.5, "dose_mg_l": 60.0},
    {"tp_mg_l": 1.0, "dose_mg_l": 100.0},
]


def utc_now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    return con


@contextmanager
def db_session() -> Iterable[sqlite3.Connection]:
    con = get_connection()
    try:
        yield con
        con.commit()
    finally:
        con.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS plants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS process_areas (
    id INTEGER PRIMARY KEY,
    plant_id INTEGER NOT NULL REFERENCES plants(id),
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS process_lines (
    id INTEGER PRIMARY KEY,
    area_id INTEGER NOT NULL REFERENCES process_areas(id),
    name TEXT NOT NULL,
    line_code TEXT NOT NULL UNIQUE,
    design_flow_m3_h REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dosing_points (
    id INTEGER PRIMARY KEY,
    process_line_id INTEGER NOT NULL REFERENCES process_lines(id),
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    flow_source TEXT NOT NULL DEFAULT 'line',
    phosphorus_source TEXT NOT NULL DEFAULT 'po4_priority',
    feedback_source TEXT NOT NULL DEFAULT 'line_out',
    in_flow_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    in_tp_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    in_ph_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    out_flow_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    out_tp_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    zone_flow_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    in_flow_weight REAL NOT NULL DEFAULT 1.0,
    reflux_flow_1_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    reflux_flow_2_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    po4_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    pac_flow_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_orp1_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_orp2_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_orp3_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_orp4_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_do1_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_do2_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_mlss1_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    bio_mlss2_tag_id INTEGER REFERENCES sensor_tags(id) ON DELETE SET NULL,
    tp_model_id INTEGER REFERENCES model_projects(id) ON DELETE SET NULL,
    pac_flow_model_id INTEGER REFERENCES model_projects(id) ON DELETE SET NULL,
    source_configured INTEGER NOT NULL DEFAULT 0,
    chemical_group_id INTEGER REFERENCES chemical_groups(id) ON DELETE SET NULL,
    process_parameter_group_id INTEGER REFERENCES process_parameter_groups(id) ON DELETE SET NULL,
    manual_contribution_factor REAL NOT NULL DEFAULT 1.0,
    display_order INTEGER NOT NULL DEFAULT 0,
    write_enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chemical_groups (
    id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE,
    pac_density_kg_l REAL NOT NULL,
    al2o3_fraction REAL NOT NULL,
    effective_factor REAL NOT NULL,
    al_p_ratio REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS process_parameter_groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tp_target_mg_l REAL NOT NULL,
    tp_limit_mg_l REAL NOT NULL,
    tp_upper_mg_l REAL NOT NULL DEFAULT 0.3,
    pac_density_kg_l REAL NOT NULL DEFAULT 1.2,
    unit_dose_curve_json TEXT NOT NULL DEFAULT '[{"tp_mg_l":0.0,"dose_mg_l":0.0},{"tp_mg_l":0.3,"dose_mg_l":30.0},{"tp_mg_l":0.5,"dose_mg_l":60.0},{"tp_mg_l":1.0,"dose_mg_l":100.0}]',
    forecast_horizon_minutes INTEGER NOT NULL DEFAULT 120,
    biochemical_phosphorus_removal_efficiency REAL NOT NULL DEFAULT 0.7,
    pac_min_l_h REAL NOT NULL,
    pac_max_l_h REAL NOT NULL,
    calculation_interval_seconds INTEGER NOT NULL DEFAULT 60,
    inflow_delay_minutes INTEGER NOT NULL DEFAULT 0,
    lag_minutes INTEGER NOT NULL,
    feedback_kp REAL NOT NULL,
    feedback_min REAL NOT NULL,
    feedback_max REAL NOT NULL,
    feedback_window_minutes INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sensor_tags (
    id INTEGER PRIMARY KEY,
    dosing_point_id INTEGER REFERENCES dosing_points(id) ON DELETE CASCADE,
    tag_code TEXT NOT NULL UNIQUE,
    tag_type TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    stale_minutes INTEGER NOT NULL,
    max_stale_minutes INTEGER NOT NULL,
    min_value REAL,
    max_value REAL,
    source TEXT NOT NULL DEFAULT 's7comm',
    enabled INTEGER NOT NULL DEFAULT 1,
    data_type TEXT NOT NULL DEFAULT 'REAL',
    plc_device_id INTEGER REFERENCES plc_devices(id) ON DELETE SET NULL,
    data_address TEXT NOT NULL DEFAULT '',
    poll_interval_seconds INTEGER NOT NULL DEFAULT 5,
    history_enabled INTEGER NOT NULL DEFAULT 1,
    history_interval_minutes INTEGER NOT NULL DEFAULT 5,
    last_quality TEXT NOT NULL DEFAULT 'unknown',
    last_value_text TEXT,
    last_read_at TEXT,
    last_error TEXT,
    last_history_at TEXT
);

CREATE TABLE IF NOT EXISTS sensor_samples (
    id INTEGER PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES sensor_tags(id) ON DELETE CASCADE,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    sample_time TEXT NOT NULL,
    receive_time TEXT NOT NULL,
    quality TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(tag_id, sample_time, source)
);

CREATE INDEX IF NOT EXISTS idx_sensor_samples_tag_time ON sensor_samples(tag_id, sample_time DESC);

CREATE TABLE IF NOT EXISTS manual_samples (
    id INTEGER PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES sensor_tags(id) ON DELETE CASCADE,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    sample_time TEXT NOT NULL,
    operator TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY,
    dosing_point_id INTEGER NOT NULL REFERENCES dosing_points(id) ON DELETE CASCADE,
    recommend_time TEXT NOT NULL,
    mode TEXT NOT NULL,
    base_l_h REAL NOT NULL,
    raw_l_h REAL NOT NULL,
    limited_l_h REAL NOT NULL,
    final_l_h REAL NOT NULL,
    quality TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'online',
    UNIQUE(dosing_point_id, recommend_time, source)
);

CREATE INDEX IF NOT EXISTS idx_recommendations_point_time ON recommendations(dosing_point_id, recommend_time DESC);

CREATE TABLE IF NOT EXISTS recommendation_explanations (
    id INTEGER PRIMARY KEY,
    recommendation_id INTEGER NOT NULL UNIQUE REFERENCES recommendations(id) ON DELETE CASCADE,
    explanation_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plc_devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    protocol TEXT NOT NULL DEFAULT 's7_1500',
    ip_address TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 102,
    timeout_ms INTEGER NOT NULL DEFAULT 5000,
    rack INTEGER NOT NULL DEFAULT 0,
    slot INTEGER NOT NULL DEFAULT 0,
    pdu_length INTEGER,
    status TEXT NOT NULL DEFAULT 'disconnected',
    last_connected_at TEXT,
    last_disconnected_at TEXT,
    last_error TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plc_device_events (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES plc_devices(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    pdu_length INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    dosing_point_id INTEGER REFERENCES dosing_points(id),
    status TEXT NOT NULL DEFAULT 'active',
    event_time TEXT NOT NULL,
    acknowledged_at TEXT,
    acknowledged_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_alarms_status_time ON alarms(status, event_time DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    protocol TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    poll_interval_seconds INTEGER NOT NULL DEFAULT 60,
    last_poll_at TEXT,
    last_error TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collector_runs (
    id INTEGER PRIMARY KEY,
    data_source_id INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    samples_written INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def init_schema() -> None:
    with db_session() as con:
        con.executescript(SCHEMA)
        ensure_runtime_schema(con)


def ensure_runtime_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS chemical_groups (
            id INTEGER PRIMARY KEY,
            batch_id TEXT NOT NULL UNIQUE,
            pac_density_kg_l REAL NOT NULL,
            al2o3_fraction REAL NOT NULL,
            effective_factor REAL NOT NULL,
            al_p_ratio REAL NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS process_parameter_groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            tp_target_mg_l REAL NOT NULL,
            tp_limit_mg_l REAL NOT NULL,
            tp_upper_mg_l REAL NOT NULL DEFAULT 0.3,
            pac_density_kg_l REAL NOT NULL DEFAULT 1.2,
            unit_dose_curve_json TEXT NOT NULL DEFAULT '[{"tp_mg_l":0.0,"dose_mg_l":0.0},{"tp_mg_l":0.3,"dose_mg_l":30.0},{"tp_mg_l":0.5,"dose_mg_l":60.0},{"tp_mg_l":1.0,"dose_mg_l":100.0}]',
            forecast_horizon_minutes INTEGER NOT NULL DEFAULT 120,
            biochemical_phosphorus_removal_efficiency REAL NOT NULL DEFAULT 0.7,
            pac_min_l_h REAL NOT NULL,
            pac_max_l_h REAL NOT NULL,
            calculation_interval_seconds INTEGER NOT NULL DEFAULT 60,
            inflow_delay_minutes INTEGER NOT NULL DEFAULT 0,
            lag_minutes INTEGER NOT NULL,
            feedback_kp REAL NOT NULL,
            feedback_min REAL NOT NULL,
            feedback_max REAL NOT NULL,
            feedback_window_minutes INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS model_projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            dosing_point_id INTEGER REFERENCES dosing_points(id) ON DELETE SET NULL,
            model_kind TEXT NOT NULL DEFAULT 'tp_out_response',
            status TEXT NOT NULL DEFAULT 'draft',
            sample_interval_minutes INTEGER NOT NULL DEFAULT 5,
            recording_enabled INTEGER NOT NULL DEFAULT 0,
            last_record_at TEXT,
            output_min REAL NOT NULL DEFAULT 0.70,
            output_max REAL NOT NULL DEFAULT 1.30,
            feature_schema_json TEXT NOT NULL DEFAULT '[]',
            training_config_json TEXT NOT NULL DEFAULT '{}',
            artifact_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            trained_at TEXT,
            published_by TEXT,
            published_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS model_training_samples (
            id INTEGER PRIMARY KEY,
            model_project_id INTEGER NOT NULL REFERENCES model_projects(id) ON DELETE CASCADE,
            sample_time TEXT NOT NULL,
            values_json TEXT NOT NULL DEFAULT '{}',
            suggested_l_h REAL,
            target_value REAL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_model_training_samples_project_time
        ON model_training_samples(model_project_id, sample_time DESC);
        """
    )
    ensure_model_projects_nullable_dosing_point(con)
    ensure_columns(
        con,
        "dosing_points",
        {
            "in_flow_tag_id": "INTEGER",
            "in_tp_tag_id": "INTEGER",
            "in_ph_tag_id": "INTEGER",
            "out_flow_tag_id": "INTEGER",
            "out_tp_tag_id": "INTEGER",
            "zone_flow_tag_id": "INTEGER",
            "in_flow_weight": "REAL NOT NULL DEFAULT 1.0",
            "reflux_flow_1_tag_id": "INTEGER",
            "reflux_flow_2_tag_id": "INTEGER",
            "po4_tag_id": "INTEGER",
            "pac_flow_tag_id": "INTEGER",
            **{field: "INTEGER" for field, *_ in LEARNING_SOURCE_TAG_DEFS},
            "bio_do1_tag_id": "INTEGER",
            "bio_do2_tag_id": "INTEGER",
            "tp_model_id": "INTEGER",
            "pac_flow_model_id": "INTEGER",
            "dual_model_id": "INTEGER",
            "source_configured": "INTEGER NOT NULL DEFAULT 0",
            "chemical_group_id": "INTEGER",
            "process_parameter_group_id": "INTEGER",
        },
    )
    ensure_columns(
        con,
        "chemical_groups",
        {"al2o3_fraction": "REAL NOT NULL DEFAULT 0.018"},
    )
    ensure_columns(
        con,
        "process_parameter_groups",
        {
            "tp_upper_mg_l": "REAL NOT NULL DEFAULT 0.3",
            "pac_density_kg_l": "REAL NOT NULL DEFAULT 1.2",
            "unit_dose_curve_json": f"TEXT NOT NULL DEFAULT '{dumps_json(DEFAULT_UNIT_DOSE_CURVE)}'",
            "forecast_horizon_minutes": "INTEGER NOT NULL DEFAULT 120",
            "biochemical_phosphorus_removal_efficiency": "REAL NOT NULL DEFAULT 0.7",
            "inflow_delay_minutes": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    con.execute("UPDATE dosing_points SET phosphorus_source='po4' WHERE phosphorus_source='po4_priority'")
    con.execute("UPDATE dosing_points SET phosphorus_source='in_tp' WHERE phosphorus_source='tp_before'")
    con.execute("UPDATE dosing_points SET zone_flow_tag_id=NULL WHERE zone_flow_tag_id IS NOT NULL")
    # `tag_code` is the only collection-point name. Keep the legacy display-name
    # column synchronized so historical databases cannot surface a second alias.
    con.execute("UPDATE sensor_tags SET name=tag_code WHERE name<>tag_code")
    ensure_columns(
        con,
        "sensor_tags",
        {
            "data_type": "TEXT NOT NULL DEFAULT 'REAL'",
            "plc_device_id": "INTEGER",
            "data_address": "TEXT NOT NULL DEFAULT ''",
            "poll_interval_seconds": "INTEGER NOT NULL DEFAULT 5",
            "history_enabled": "INTEGER NOT NULL DEFAULT 1",
            "history_interval_minutes": "INTEGER NOT NULL DEFAULT 5",
            "last_quality": "TEXT NOT NULL DEFAULT 'unknown'",
            "last_value_text": "TEXT",
            "last_read_at": "TEXT",
            "last_error": "TEXT",
            "last_history_at": "TEXT",
        },
    )
    ensure_columns(
        con,
        "model_projects",
        {
            "sample_interval_minutes": "INTEGER NOT NULL DEFAULT 5",
            "model_kind": "TEXT NOT NULL DEFAULT 'tp_out_response'",
            "training_config_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    backfill_parameter_groups(con)
    ensure_model_training_samples_target_value(con)
    sanitize_model_training_configs(con)
    # Recording is runtime activity, not a model lifecycle state. Restore models
    # that were previously published before recording was started.
    con.execute(
        "UPDATE model_projects SET status='published' WHERE status='recording' AND published_at IS NOT NULL"
    )
    con.execute(
        "UPDATE model_projects SET recording_enabled=0, status=CASE WHEN status='recording' THEN 'draft' ELSE status END"
    )
    con.execute(
        "UPDATE model_projects SET status='archived', recording_enabled=0 WHERE model_kind='dose_predict'"
    )
    ensure_columns(
        con,
        "plc_devices",
        {
            "reconnect_enabled": "INTEGER NOT NULL DEFAULT 0",
            "reconnect_interval_seconds": "INTEGER NOT NULL DEFAULT 10",
        },
    )
    backfill_process_source_tags(con)
    ensure_learning_source_tags(con)
    backfill_in_ph_source_tags(con)
    backfill_point_model_selections(con)


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def ensure_model_training_samples_target_value(con: sqlite3.Connection) -> None:
    columns = {row["name"] for row in con.execute("PRAGMA table_info(model_training_samples)").fetchall()}
    if "target_value" not in columns:
        con.execute("ALTER TABLE model_training_samples ADD COLUMN target_value REAL")
    if "k_ai" in columns:
        con.execute("UPDATE model_training_samples SET target_value=COALESCE(target_value, k_ai)")


def sanitize_model_training_configs(con: sqlite3.Connection) -> None:
    removed_keys = {"prediction_step", "sample_weight_rule"}
    rows = con.execute("SELECT id, training_config_json FROM model_projects").fetchall()
    for row in rows:
        try:
            config = loads_json(row["training_config_json"], {})
        except json.JSONDecodeError:
            continue
        if not isinstance(config, dict) or not any(key in config for key in removed_keys):
            continue
        cleaned = {key: value for key, value in config.items() if key not in removed_keys}
        con.execute(
            "UPDATE model_projects SET training_config_json=? WHERE id=?",
            (dumps_json(cleaned), row["id"]),
        )


def ensure_model_projects_nullable_dosing_point(con: sqlite3.Connection) -> None:
    columns = con.execute("PRAGMA table_info(model_projects)").fetchall()
    dosing_point_column = next((row for row in columns if row["name"] == "dosing_point_id"), None)
    if not dosing_point_column or not int(dosing_point_column["notnull"]):
        return
    con.commit()
    foreign_keys_enabled = int(con.execute("PRAGMA foreign_keys").fetchone()[0])
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS model_projects_new (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                dosing_point_id INTEGER REFERENCES dosing_points(id) ON DELETE SET NULL,
                model_kind TEXT NOT NULL DEFAULT 'tp_out_response',
                status TEXT NOT NULL DEFAULT 'draft',
                sample_interval_minutes INTEGER NOT NULL DEFAULT 5,
                recording_enabled INTEGER NOT NULL DEFAULT 0,
                last_record_at TEXT,
                output_min REAL NOT NULL DEFAULT 0.70,
                output_max REAL NOT NULL DEFAULT 1.30,
                feature_schema_json TEXT NOT NULL DEFAULT '[]',
                training_config_json TEXT NOT NULL DEFAULT '{}',
                artifact_json TEXT NOT NULL DEFAULT '{}',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                trained_at TEXT,
                published_by TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            INSERT INTO model_projects_new(
                id,name,dosing_point_id,model_kind,status,sample_interval_minutes,recording_enabled,last_record_at,
                output_min,output_max,feature_schema_json,training_config_json,artifact_json,metrics_json,
                trained_at,published_by,published_at,created_at,updated_at
            )
            SELECT id,name,dosing_point_id,model_kind,status,sample_interval_minutes,recording_enabled,last_record_at,
                output_min,output_max,feature_schema_json,training_config_json,artifact_json,metrics_json,
                trained_at,published_by,published_at,created_at,updated_at
            FROM model_projects;

            DROP TABLE model_projects;
            ALTER TABLE model_projects_new RENAME TO model_projects;
            """
        )
    finally:
        con.execute(f"PRAGMA foreign_keys={foreign_keys_enabled}")


def backfill_point_model_selections(con: sqlite3.Connection) -> None:
    for target_column, kind in (
        ("tp_model_id", "tp_out_response"),
        ("pac_flow_model_id", "pac_flow_predict"),
        ("dual_model_id", "ai_pac_dual_task"),
    ):
        con.execute(
            f"""
            UPDATE dosing_points
            SET {target_column}=(
                SELECT mp.id
                FROM model_projects mp
                WHERE mp.dosing_point_id=dosing_points.id
                  AND mp.model_kind=?
                  AND mp.status='published'
                  AND mp.trained_at IS NOT NULL
                ORDER BY mp.published_at DESC, mp.id DESC
                LIMIT 1
            )
            WHERE {target_column} IS NULL
              AND EXISTS (
                SELECT 1
                FROM model_projects mp
                WHERE mp.dosing_point_id=dosing_points.id
                  AND mp.model_kind=?
                  AND mp.status='published'
                  AND mp.trained_at IS NOT NULL
              )
            """,
            (kind, kind),
        )


def backfill_parameter_groups(con: sqlite3.Connection) -> None:
    now = utc_now_iso()
    pac_rows = []
    if table_exists(con, "pac_configs"):
        pac_rows = con.execute(
            """
            SELECT pc.*, dp.name AS point_name
            FROM pac_configs pc
            JOIN dosing_points dp ON dp.id=pc.dosing_point_id
            WHERE dp.chemical_group_id IS NULL
            ORDER BY pc.id
            """
        ).fetchall()
    for row in pac_rows:
        batch_id = row["batch_id"] or f"{row['point_name']}-药剂"
        existing = con.execute("SELECT id FROM chemical_groups WHERE batch_id=?", (batch_id,)).fetchone()
        if existing:
            group_id = int(existing["id"])
        else:
            cur = con.execute(
                """
                INSERT INTO chemical_groups(batch_id,pac_density_kg_l,al2o3_fraction,effective_factor,al_p_ratio,updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    batch_id,
                    row["pac_density_kg_l"],
                    row["al2o3_fraction"],
                    row["effective_factor"],
                    row["al_p_ratio"],
                    row["updated_at"] or now,
                ),
            )
            group_id = int(cur.lastrowid)
        con.execute("UPDATE dosing_points SET chemical_group_id=? WHERE id=?", (group_id, row["dosing_point_id"]))

    control_rows = []
    if table_exists(con, "control_configs"):
        control_rows = con.execute(
            """
            SELECT cc.*, dp.name AS point_name
            FROM control_configs cc
            JOIN dosing_points dp ON dp.id=cc.dosing_point_id
            WHERE dp.process_parameter_group_id IS NULL
            ORDER BY cc.id
            """
        ).fetchall()
    for row in control_rows:
        name = f"{row['point_name']}-工艺参数"
        existing = con.execute("SELECT id FROM process_parameter_groups WHERE name=?", (name,)).fetchone()
        if existing:
            group_id = int(existing["id"])
        else:
            cur = con.execute(
                """
                INSERT INTO process_parameter_groups(
                    name,tp_target_mg_l,tp_limit_mg_l,tp_upper_mg_l,pac_density_kg_l,unit_dose_curve_json,forecast_horizon_minutes,
                    biochemical_phosphorus_removal_efficiency,
                    pac_min_l_h,pac_max_l_h,calculation_interval_seconds,inflow_delay_minutes,
                    lag_minutes,feedback_kp,feedback_min,feedback_max,feedback_window_minutes,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    name,
                    row["tp_target_mg_l"],
                    row["tp_limit_mg_l"],
                    row["tp_limit_mg_l"],
                    1.2,
                    dumps_json(DEFAULT_UNIT_DOSE_CURVE),
                    120,
                    row["biochemical_phosphorus_removal_efficiency"],
                    row["pac_min_l_h"],
                    row["pac_max_l_h"],
                    60,
                    row["inflow_delay_minutes"],
                    row["lag_minutes"],
                    row["feedback_kp"],
                    row["feedback_min"],
                    row["feedback_max"],
                    row["feedback_window_minutes"],
                    row["updated_at"] or now,
                ),
            )
            group_id = int(cur.lastrowid)
        con.execute("UPDATE dosing_points SET process_parameter_group_id=? WHERE id=?", (group_id, row["dosing_point_id"]))


def backfill_process_source_tags(con: sqlite3.Connection) -> None:
    points = con.execute("SELECT * FROM dosing_points WHERE source_configured=0").fetchall()
    for point in points:
        tags = con.execute(
            "SELECT id, tag_code, tag_type FROM sensor_tags WHERE dosing_point_id=? ORDER BY id",
            (point["id"],),
        ).fetchall()
        updates = infer_process_source_tags(tags)
        con.execute(
            """
            UPDATE dosing_points
            SET in_flow_tag_id=?, in_tp_tag_id=?, in_ph_tag_id=?, out_tp_tag_id=?, pac_flow_tag_id=?, source_configured=1
            WHERE id=?
            """,
            (
                updates["in_flow_tag_id"],
                updates["in_tp_tag_id"],
                updates["in_ph_tag_id"],
                updates["out_tp_tag_id"],
                updates["pac_flow_tag_id"],
                point["id"],
            ),
        )


def ensure_learning_source_tags(con: sqlite3.Connection) -> None:
    points = con.execute("SELECT * FROM dosing_points ORDER BY id").fetchall()
    now = utc_now_iso()
    for point in points:
        assigned: dict[str, int] = {}
        for field, tag_type, _label, unit, stale, max_stale, min_value, max_value, default_value in LEARNING_SOURCE_TAG_DEFS:
            tag = con.execute(
                "SELECT id FROM sensor_tags WHERE dosing_point_id=? AND tag_type=? ORDER BY id LIMIT 1",
                (point["id"], tag_type),
            ).fetchone()
            if not tag:
                tag_code = f"{point['code']}_{tag_type}"
                cur = con.execute(
                    """
                    INSERT INTO sensor_tags(
                        dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,
                        min_value,max_value,source,enabled
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,1)
                    """,
                    (point["id"], tag_code, tag_type, tag_code, unit, stale, max_stale, min_value, max_value, "s7comm"),
                )
                tag_id = int(cur.lastrowid)
                con.execute(
                    """
                    INSERT OR IGNORE INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (tag_id, default_value, unit, now, now, "good", "s7comm"),
                )
            else:
                tag_id = int(tag["id"])
            if point[field] is None:
                assigned[field] = tag_id
        if assigned:
            set_clause = ", ".join(f"{field}=?" for field in assigned)
            con.execute(
                f"UPDATE dosing_points SET {set_clause}, source_configured=1 WHERE id=?",
                (*assigned.values(), point["id"]),
            )


def backfill_in_ph_source_tags(con: sqlite3.Connection) -> None:
    points = con.execute("SELECT id FROM dosing_points WHERE in_ph_tag_id IS NULL ORDER BY id").fetchall()
    for point in points:
        tags = con.execute(
            "SELECT id, tag_code, tag_type FROM sensor_tags WHERE dosing_point_id=? ORDER BY id",
            (point["id"],),
        ).fetchall()
        tag_id = infer_process_source_tags(tags)["in_ph_tag_id"]
        if tag_id is not None:
            con.execute("UPDATE dosing_points SET in_ph_tag_id=?, source_configured=1 WHERE id=?", (tag_id, point["id"]))


def infer_process_source_tags(tags: list[sqlite3.Row]) -> dict[str, int | None]:
    def find(field: str) -> int | None:
        for tag in tags:
            code = str(tag["tag_code"] or "").upper()
            tag_type = str(tag["tag_type"] or "").upper()
            if field == "in_flow_tag_id" and (tag_type == "Q" or code.endswith("_Q") or "IN_Q" in code):
                return int(tag["id"])
            if field == "in_tp_tag_id" and (tag_type == "TP_BEFORE" or "IN_TP" in code or "TP_BEFORE" in code):
                return int(tag["id"])
            if field == "in_ph_tag_id" and (tag_type == "PH" or "IN_PH" in code or code.endswith("_PH")):
                return int(tag["id"])
            if field == "out_tp_tag_id" and (tag_type == "TP_OUT" or "OUT_TP" in code):
                return int(tag["id"])
            if field == "pac_flow_tag_id" and (tag_type == "PAC_ACTUAL" or "QPAC" in code or "PAC_ACTUAL" in code or "PAC_FLOW" in code):
                return int(tag["id"])
            for learning_field, learning_type, *_ in LEARNING_SOURCE_TAG_DEFS:
                if field == learning_field and (tag_type == learning_type or learning_type in code):
                    return int(tag["id"])
        return None

    return {
        "in_flow_tag_id": find("in_flow_tag_id"),
        "in_tp_tag_id": find("in_tp_tag_id"),
        "in_ph_tag_id": find("in_ph_tag_id"),
        "out_tp_tag_id": find("out_tp_tag_id"),
        "pac_flow_tag_id": find("pac_flow_tag_id"),
        **{field: find(field) for field, *_ in LEARNING_SOURCE_TAG_DEFS},
    }


def ensure_columns(con: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, ddl in columns.items():
        if name not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def table_count(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def upsert_alarm(
    con: sqlite3.Connection,
    *,
    severity: str,
    title: str,
    category: str,
    message: str,
    dosing_point_id: int | None,
    event_time: str | None = None,
) -> None:
    active = con.execute(
        """
        SELECT id FROM alarms
        WHERE status='active' AND title=? AND category=? AND COALESCE(dosing_point_id, 0)=COALESCE(?, 0)
        """,
        (title, category, dosing_point_id),
    ).fetchone()
    if active:
        return
    con.execute(
        """
        INSERT INTO alarms(severity,title,category,message,dosing_point_id,event_time)
        VALUES(?,?,?,?,?,?)
        """,
        (severity, title, category, message, dosing_point_id, event_time or utc_now_iso()),
    )


def clear_alarm(con: sqlite3.Connection, *, title: str, category: str, dosing_point_id: int | None) -> None:
    con.execute(
        """
        UPDATE alarms
        SET status='cleared'
        WHERE status='active' AND title=? AND category=? AND COALESCE(dosing_point_id, 0)=COALESCE(?, 0)
        """,
        (title, category, dosing_point_id),
    )


def backup_database() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"ai_pac_{stamp}.sqlite"
    with get_connection() as source:
        with sqlite3.connect(target) as dest:
            source.backup(dest)
    return target


def create_time_range(hours: int = 6, step_minutes: int = 5) -> list[datetime]:
    now = datetime.now().replace(second=0, microsecond=0)
    start = now - timedelta(hours=hours)
    values: list[datetime] = []
    cur = start
    while cur <= now:
        values.append(cur)
        cur += timedelta(minutes=step_minutes)
    return values
