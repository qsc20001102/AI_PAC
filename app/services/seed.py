from __future__ import annotations

import math
import random
import sqlite3
from datetime import datetime, timedelta

from app.database import DEFAULT_UNIT_DOSE_CURVE, backfill_process_source_tags, create_time_range, dumps_json, ensure_learning_source_tags, table_count, utc_now_iso


def ensure_seed_data(con: sqlite3.Connection) -> None:
    if table_count(con, "plants") > 0:
        _ensure_runtime_defaults(con)
        return

    now = datetime.now().replace(second=0, microsecond=0)
    now_iso = now.isoformat()

    con.execute(
        "INSERT INTO plants(id,name,location,created_at) VALUES(1,?,?,?)",
        ("某污水厂", "本地部署", now_iso),
    )
    con.execute("INSERT INTO process_areas(id,plant_id,name) VALUES(1,1,?)", ("深度处理区",))

    lines = [
        (1, 1, "生化1线", "LINE_1", 1250),
        (2, 1, "生化2线", "LINE_2", 1000),
        (3, 1, "深度处理线", "LINE_DEEP", 520),
        (4, 1, "备用投加线", "LINE_STANDBY", 300),
    ]
    con.executemany(
        "INSERT INTO process_lines(id,area_id,name,line_code,design_flow_m3_h) VALUES(?,?,?,?,?)",
        lines,
    )

    points = [
        (1, 1, "1#高效池 PAC", "PAC_1", 1, "line", "po4", "shared_out", 1.00, 1, 1),
        (2, 2, "2#高效池 PAC", "PAC_2", 1, "line", "po4", "shared_out", 0.92, 2, 1),
        (3, 3, "深度处理 PAC", "PAC_DEEP", 1, "line", "po4", "line_out", 0.70, 3, 0),
        (4, 4, "备用投加点", "PAC_STANDBY", 1, "manual", "manual", "manual", 0.30, 4, 0),
    ]
    con.executemany(
        """
        INSERT INTO dosing_points(
            id,process_line_id,name,code,enabled,flow_source,phosphorus_source,feedback_source,
            manual_contribution_factor,display_order,write_enabled
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        points,
    )

    pac_configs = [
        (1, 1, 1.20, 0.018, 0.90, 2.90, "PAC-202606-A-稀释", now_iso),
        (2, 2, 1.19, 0.018, 0.90, 1.35, "PAC-202606-A-稀释", now_iso),
        (3, 3, 1.18, 0.040, 0.88, 1.80, "PAC-202606-B-稀释", now_iso),
        (4, 4, 1.20, 0.018, 0.90, 2.00, "备用批次", now_iso),
    ]
    con.executemany(
        """
        INSERT INTO pac_configs(
            id,dosing_point_id,pac_density_kg_l,al2o3_fraction,effective_factor,al_p_ratio,batch_id,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        pac_configs,
    )

    control_configs = [
        (1, 1, 0.18, 0.16, 0.30, 0.7, 6.0, 80.0, 0.15, 3.5, 2.0, 0, 55, 0.28, 0.80, 1.30, 120, now_iso),
        (2, 2, 0.18, 0.16, 0.30, 0.7, 5.0, 70.0, 0.15, 3.0, 2.0, 0, 60, 0.24, 0.82, 1.25, 120, now_iso),
        (3, 3, 0.16, 0.14, 0.30, 0.7, 4.0, 55.0, 0.12, 2.5, 1.5, 0, 45, 0.22, 0.85, 1.22, 90, now_iso),
        (4, 4, 0.18, 0.16, 0.30, 0.7, 0.0, 40.0, 0.20, 3.0, 1.5, 0, 60, 0.20, 0.85, 1.20, 60, now_iso),
    ]
    con.executemany(
        """
        INSERT INTO control_configs(
            id,dosing_point_id,tp_target_mg_l,tp_safe_target_mg_l,tp_limit_mg_l,biochemical_phosphorus_removal_efficiency,
            pac_min_l_h,pac_max_l_h,
            single_step_change_ratio,max_increase_l_h_per_min,max_decrease_l_h_per_min,inflow_delay_minutes,lag_minutes,
            feedback_kp,feedback_min,feedback_max,feedback_window_minutes,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        control_configs,
    )
    process_groups = [
        (1, "默认工艺参数", 0.18, 0.30, 0.30, 1.20, dumps_json(DEFAULT_UNIT_DOSE_CURVE), 120, 0.7, 0.0, 80.0, 60, 0, 60, 0.0, 1.0, 1.0, 60, now_iso),
        (2, "深度处理工艺参数", 0.16, 0.30, 0.30, 1.20, dumps_json(DEFAULT_UNIT_DOSE_CURVE), 120, 0.7, 0.0, 60.0, 60, 0, 60, 0.0, 1.0, 1.0, 60, now_iso),
    ]
    con.executemany(
        """
        INSERT INTO process_parameter_groups(
            id,name,tp_target_mg_l,tp_limit_mg_l,tp_upper_mg_l,pac_density_kg_l,unit_dose_curve_json,
            forecast_horizon_minutes,biochemical_phosphorus_removal_efficiency,pac_min_l_h,pac_max_l_h,calculation_interval_seconds,
            inflow_delay_minutes,lag_minutes,feedback_kp,feedback_min,feedback_max,feedback_window_minutes,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        process_groups,
    )
    con.execute("UPDATE dosing_points SET process_parameter_group_id=1 WHERE id IN (1,2,4)")
    con.execute("UPDATE dosing_points SET process_parameter_group_id=2 WHERE id=3")

    tag_rows: list[tuple] = []
    tag_id = 1
    for point_id, prefix in [(1, "PAC1"), (2, "PAC2"), (3, "DEEP"), (4, "STBY")]:
        for tag_type, name, unit, stale, max_stale, min_v, max_v in [
            ("Q", "流量", "m3/h", 3, 15, 0, 4000),
            ("PO4_P", "投加前 PO4-P", "mg/L", 10, 60, 0, 20),
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
        ]:
            source = "manual" if point_id == 4 else "s7comm"
            tag_rows.append((tag_id, point_id, f"{prefix}_{tag_type}", tag_type, name, unit, stale, max_stale, min_v, max_v, source, 1))
            tag_id += 1
    con.executemany(
        """
        INSERT INTO sensor_tags(
            id,dosing_point_id,tag_code,tag_type,name,unit,stale_minutes,max_stale_minutes,
            min_value,max_value,source,enabled
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        tag_rows,
    )
    backfill_process_source_tags(con)
    ensure_learning_source_tags(con)

    con.execute(
        """
        INSERT INTO plc_connections(id,name,protocol,endpoint,status,mode,last_seen_at,read_only,enabled)
        VALUES(1,?,?,?,?,?,?,?,?)
        """,
        ("S7-1500 / PUT-GET", "s7_1500", "192.168.1.10:102", "disconnected", "S7comm/PUT-GET", None, 1, 1),
    )
    mappings = [
        (1, 1, 1, "read_Q", "DB10.DBD0", "REAL", 1, "m3/h", 1, 1),
        (2, 1, 1, "read_PO4_P", "DB10.DBD4", "REAL", 1, "mg/L", 1, 1),
        (3, 1, 1, "read_TP_OUT", "DB10.DBD8", "REAL", 1, "mg/L", 1, 1),
        (4, 1, 1, "read_PH", "DB10.DBD12", "REAL", 1, "", 1, 1),
        (5, 1, 1, "write_PAC_Suggest_L_h", "DB100.DBD0", "REAL", 1, "L/h", 0, 1),
        (6, 2, 1, "write_PAC_Suggest_L_h", "DB100.DBD20", "REAL", 1, "L/h", 0, 1),
    ]
    con.executemany(
        """
        INSERT INTO plc_tag_mappings(
            id,dosing_point_id,connection_id,tag_kind,plc_address,data_type,scale,unit,read_only,enabled
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        mappings,
    )

    con.execute(
        """
        INSERT INTO plc_devices(
            id,name,protocol,ip_address,port,timeout_ms,rack,slot,pdu_length,status,
            last_connected_at,last_disconnected_at,last_error,enabled,created_at,updated_at
        ) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "S7-1500 主站",
            "s7_1500",
            "192.168.1.10",
            102,
            5000,
            0,
            0,
            None,
            "disconnected",
            None,
            None,
            "待连接",
            1,
            now_iso,
            now_iso,
        ),
    )

    con.execute(
        """
        INSERT INTO data_sources(
            id,name,source_type,protocol,endpoint,status,poll_interval_seconds,last_poll_at,last_error,enabled,config_json,created_at
        ) VALUES(1,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "本地样例模拟采集",
            "simulated",
            "internal",
            "local://demo-generator",
            "running",
            60,
            now_iso,
            None,
            1,
            dumps_json({"points": ["PAC_1", "PAC_2"], "purpose": "开发环境样例数据源"}),
            now_iso,
        ),
    )
    con.execute(
        """
        INSERT INTO data_sources(
            id,name,source_type,protocol,endpoint,status,poll_interval_seconds,last_error,enabled,config_json,created_at
        ) VALUES(2,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "外部采集 API",
            "api",
            "http",
            "/api/ingest/samples",
            "idle",
            0,
            None,
            1,
            dumps_json({"required_fields": ["tag_code", "value", "sample_time"]}),
            now_iso,
        ),
    )

    metrics = {"MAPE": 12.3, "R2": 0.86, "samples": 4832, "shadow_days": 7}
    coefficients = {
        "intercept": 0.985,
        "q_load": 0.022,
        "po4": -0.035,
        "tp_out": 0.040,
        "ph": -0.020,
        "turbidity": 0.012,
        "min": 0.70,
        "max": 1.30,
    }
    con.execute(
        """
        INSERT INTO model_versions(
            id,version,status,train_start,train_end,metrics_json,coefficients_json,published_by,published_at,created_at
        ) VALUES(1,?,?,?,?,?,?,?,?,?)
        """,
        (
            "除磷模型 v3.0.1",
            "published",
            (now - timedelta(days=45)).date().isoformat(),
            (now - timedelta(days=7)).date().isoformat(),
            dumps_json(metrics),
            dumps_json(coefficients),
            "工程师",
            (now - timedelta(days=5, hours=3)).isoformat(),
            (now - timedelta(days=7)).isoformat(),
        ),
    )

    con.execute(
        """
        INSERT INTO model_versions(
            id,version,status,train_start,train_end,metrics_json,coefficients_json,created_at
        ) VALUES(2,?,?,?,?,?,?,?)
        """,
        (
            "除磷模型 v3.1.0-candidate",
            "shadow",
            (now - timedelta(days=30)).date().isoformat(),
            (now - timedelta(days=1)).date().isoformat(),
            dumps_json({"MAPE": 11.8, "R2": 0.88, "samples": 5120, "shadow_days": 1}),
            dumps_json({**coefficients, "intercept": 0.992, "po4": -0.028}),
            now_iso,
        ),
    )

    _insert_samples(con, now)
    from app.services.recommendation import calculate_for_point

    calculate_for_point(con, 3, now=now - timedelta(minutes=42), save=True)
    _insert_initial_alarms(con, now)
    _insert_settings(con, now_iso)
    _ensure_runtime_defaults(con)


def _ensure_runtime_defaults(con: sqlite3.Connection) -> None:
    now_iso = datetime.now().replace(second=0, microsecond=0).isoformat()
    if table_count(con, "plc_devices") == 0:
        con.execute(
            """
            INSERT INTO plc_devices(
                name,protocol,ip_address,port,timeout_ms,rack,slot,pdu_length,status,
                last_connected_at,last_disconnected_at,last_error,enabled,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "S7-1500 主站",
                "s7_1500",
                "192.168.1.10",
                102,
                5000,
                0,
                0,
                None,
                "disconnected",
                None,
                None,
                "待连接",
                1,
                now_iso,
                now_iso,
            ),
        )
    if table_count(con, "data_sources") == 0:
        con.execute(
            """
            INSERT INTO data_sources(
                name,source_type,protocol,endpoint,status,poll_interval_seconds,last_poll_at,last_error,enabled,config_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "本地样例模拟采集",
                "simulated",
                "internal",
                "local://demo-generator",
                "running",
                60,
                now_iso,
                None,
                1,
                dumps_json({"points": ["PAC_1", "PAC_2"], "purpose": "开发环境样例数据源"}),
                now_iso,
            ),
        )
        con.execute(
            """
            INSERT INTO data_sources(
                name,source_type,protocol,endpoint,status,poll_interval_seconds,last_error,enabled,config_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "外部采集 API",
                "api",
                "http",
                "/api/ingest/samples",
                "idle",
                0,
                None,
                1,
                dumps_json({"required_fields": ["tag_code", "value", "sample_time"]}),
                now_iso,
            ),
        )
    setting = con.execute("SELECT key FROM app_settings WHERE key='demo_live_refresh'").fetchone()
    if not setting:
        con.execute(
            "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)",
            ("demo_live_refresh", "true", now_iso),
        )


def _insert_samples(con: sqlite3.Connection, now: datetime) -> None:
    rng = random.Random(20260625)
    tag_map = {
        row["tag_code"]: row
        for row in con.execute("SELECT id, tag_code, unit FROM sensor_tags").fetchall()
    }

    base = {
        1: {"prefix": "PAC1", "q": 1235, "po4": 0.32, "tp_before": 0.46, "tp_out": 0.18, "ph": 7.32, "pac": 35.9, "turb": 14, "orp": -55, "do": 2.1, "mlss": 3200},
        2: {"prefix": "PAC2", "q": 988, "po4": 0.41, "tp_before": 0.53, "tp_out": 0.24, "ph": 7.28, "pac": 28.4, "turb": 18, "orp": -72, "do": 1.8, "mlss": 3500},
        3: {"prefix": "DEEP", "q": 512, "po4": 0.58, "tp_before": 0.66, "tp_out": 0.31, "ph": 7.14, "pac": 15.0, "turb": 11, "orp": -40, "do": 2.5, "mlss": 3000},
        4: {"prefix": "STBY", "q": 0, "po4": 0.0, "tp_before": 0.0, "tp_out": 0.0, "ph": 0.0, "pac": 0.0, "turb": 0.0, "orp": 0, "do": 0, "mlss": 0},
    }
    samples: list[tuple] = []
    for idx, ts in enumerate(create_time_range(6, 5)):
        phase = idx / 8
        for point_id, item in base.items():
            prefix = item["prefix"]
            if point_id == 4:
                continue
            if point_id == 3 and ts > now - timedelta(minutes=42):
                continue
            q = item["q"] + math.sin(phase) * 65 + rng.uniform(-35, 35)
            po4 = max(item["po4"] + math.sin(phase / 2) * 0.035 + rng.uniform(-0.025, 0.025), 0.02)
            tp_before = max(item["tp_before"] + math.cos(phase / 2) * 0.03 + rng.uniform(-0.03, 0.03), 0.02)
            lagged = item["tp_out"] + math.sin((phase - 2) / 2) * 0.025 + rng.uniform(-0.012, 0.012)
            ph = item["ph"] + rng.uniform(-0.08, 0.08)
            actual = item["pac"] + math.sin(phase / 3) * 1.4 + rng.uniform(-0.9, 0.9)
            turb = item["turb"] + rng.uniform(-2.0, 2.0)
            orp = item["orp"] + math.sin(phase / 2) * 12 + rng.uniform(-8, 8)
            dissolved_oxygen = max(item["do"] + math.cos(phase / 3) * 0.25 + rng.uniform(-0.15, 0.15), 0)
            mlss = max(item["mlss"] + math.sin(phase / 4) * 180 + rng.uniform(-90, 90), 0)
            values = {
                "Q": max(q, 0),
                "PO4_P": po4,
                "TP_BEFORE": tp_before,
                "TP_OUT": max(lagged, 0.02),
                "PH": ph,
                "PAC_ACTUAL": max(actual, 0),
                "TURBIDITY": max(turb, 0),
                "BIO_ORP1": orp,
                "BIO_ORP2": orp + rng.uniform(-10, 10),
                "BIO_ORP3": orp + rng.uniform(-14, 14),
                "BIO_ORP4": orp + rng.uniform(-18, 18),
                "BIO_DO1": dissolved_oxygen,
                "BIO_DO2": max(dissolved_oxygen + rng.uniform(-0.25, 0.25), 0),
                "BIO_MLSS1": mlss,
                "BIO_MLSS2": max(mlss + rng.uniform(-160, 160), 0),
            }
            for tag_type, value in values.items():
                tag = tag_map[f"{prefix}_{tag_type}"]
                samples.append(
                    (
                        tag["id"],
                        round(value, 4),
                        tag["unit"],
                        ts.isoformat(),
                        (ts + timedelta(seconds=8)).isoformat(),
                        "good",
                        "s7comm",
                    )
                )

    # Latest edge cases visible on the overview.
    stale_ts = now - timedelta(minutes=42)
    for tag_type in ["Q", "PO4_P", "TP_BEFORE", "TP_OUT", "PH", "PAC_ACTUAL", "TURBIDITY", "BIO_ORP1", "BIO_ORP2", "BIO_ORP3", "BIO_ORP4", "BIO_DO1", "BIO_DO2", "BIO_MLSS1", "BIO_MLSS2"]:
        tag = tag_map[f"DEEP_{tag_type}"]
        value = {"Q": 512, "PO4_P": 0.58, "TP_BEFORE": 0.66, "TP_OUT": 0.31, "PH": 7.14, "PAC_ACTUAL": 15.2, "TURBIDITY": 12, "BIO_ORP1": -40, "BIO_ORP2": -45, "BIO_ORP3": -38, "BIO_ORP4": -50, "BIO_DO1": 2.5, "BIO_DO2": 2.3, "BIO_MLSS1": 3000, "BIO_MLSS2": 3120}.get(tag_type, 0)
        samples.append((tag["id"], value, tag["unit"], stale_ts.isoformat(), stale_ts.isoformat(), "good", "s7comm"))

    for tag_type in ["Q", "PO4_P", "TP_BEFORE", "TP_OUT", "PH", "PAC_ACTUAL", "TURBIDITY", "BIO_ORP1", "BIO_ORP2", "BIO_ORP3", "BIO_ORP4", "BIO_DO1", "BIO_DO2", "BIO_MLSS1", "BIO_MLSS2"]:
        tag = tag_map[f"STBY_{tag_type}"]
        value = 7.2 if tag_type == "PH" else (2 if tag_type.startswith("BIO_DO") else (3000 if tag_type.startswith("BIO_MLSS") else 0))
        samples.append((tag["id"], value, tag["unit"], now.isoformat(), now.isoformat(), "good", "manual"))

    con.executemany(
        """
        INSERT OR IGNORE INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source)
        VALUES(?,?,?,?,?,?,?)
        """,
        samples,
    )


def _insert_initial_alarms(con: sqlite3.Connection, now: datetime) -> None:
    rows = [
        ("high", "出水TP延迟 42min", "data", "深度处理 PAC 出水 TP 数据延迟，反馈修正暂停。", 3, now - timedelta(minutes=42)),
        ("medium", "PAC批次待确认", "chemical", "2#高效池 PAC 药剂批次未完成现场确认。", 2, now - timedelta(minutes=46)),
        ("low", "PLC写入测试通过", "plc", "测试 DB 写入已通过，当前仍处于读写分离。", None, now - timedelta(minutes=62)),
    ]
    con.executemany(
        """
        INSERT INTO alarms(severity,title,category,message,dosing_point_id,event_time)
        VALUES(?,?,?,?,?,?)
        """,
        [(severity, title, category, message, point_id, ts.isoformat()) for severity, title, category, message, point_id, ts in rows],
    )


def _insert_settings(con: sqlite3.Connection, now_iso: str) -> None:
    settings = [
        ("retention_raw_days", "1095", now_iso),
        ("retention_alarm_days", "1095", now_iso),
        ("backup_dir", "backup", now_iso),
        ("write_policy", "只写建议值，不写启停/频率", now_iso),
        ("deployment_mode", "local", now_iso),
        ("demo_live_refresh", "true", now_iso),
        ("seeded_at", utc_now_iso(), now_iso),
    ]
    con.executemany(
        "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)",
        settings,
    )
