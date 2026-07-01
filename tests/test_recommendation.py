from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.models import create_model_project
from app.database import SCHEMA, dumps_json, ensure_runtime_schema, loads_json
from app.schemas import ModelProjectCreate
from app.services.model_training import (
    current_model_feature_schema,
    import_model_csv_samples,
    monotone_constraints_for_features,
    normalize_training_config,
    parse_model_csv_sample_time,
    record_model_project_sample,
    train_model_project_artifact,
)
from app.services import collection_runtime, plc_devices
from app.api.settings import validate_setting_value
from app.services.plc import PlcConnectResult, PlcReadResult
from app.services.settings_config import ensure_default_app_settings, normalize_listen_port
from app.services.recommendation import (
    calculate_for_point,
    conservative_formula_l_h,
    interpolate_unit_dose,
    latest_data_for_tag,
    validate_unit_dose_curve,
)
from app.services.seed import ensure_seed_data


class RecommendationFormulaTests(unittest.TestCase):
    def memory_db(self) -> sqlite3.Connection:
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        ensure_runtime_schema(con)
        ensure_seed_data(con)
        return con

    def test_unit_dose_curve_interpolation_and_formula(self):
        curve = validate_unit_dose_curve(
            [
                {"tp_mg_l": 0.0, "dose_mg_l": 0.0},
                {"tp_mg_l": 0.3, "dose_mg_l": 30.0},
                {"tp_mg_l": 0.5, "dose_mg_l": 60.0},
            ]
        )
        self.assertAlmostEqual(interpolate_unit_dose(0.4, curve), 45.0)
        self.assertAlmostEqual(interpolate_unit_dose(0.9, curve), 60.0)
        self.assertAlmostEqual(conservative_formula_l_h(1000, 30, 1.2), 25.0)

    def test_recommendation_uses_conservative_formula_without_model(self):
        con = self.memory_db()
        now = datetime.now().replace(second=0, microsecond=0)
        result = calculate_for_point(con, 1, now=now, save=False)
        self.assertEqual(result["mode"], "conservative")
        self.assertGreater(result["final_l_h"], 0)
        self.assertTrue(any("保守公式" in reason for reason in result["reasons"]))

    def test_high_tp_outputs_max_l_h(self):
        con = self.memory_db()
        tag = con.execute("SELECT id,unit FROM sensor_tags WHERE tag_code='PAC1_TP_OUT'").fetchone()
        now = datetime.now().replace(second=0, microsecond=0)
        con.execute(
            "INSERT OR REPLACE INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source) VALUES(?,?,?,?,?,?,?)",
            (tag["id"], 2.0, tag["unit"], now.isoformat(), now.isoformat(), "good", "s7comm"),
        )
        result = calculate_for_point(con, 1, now=now, save=False)
        control = con.execute("SELECT * FROM process_parameter_groups WHERE id=1").fetchone()
        self.assertEqual(result["mode"], "conservative")
        self.assertAlmostEqual(result["final_l_h"], control["pac_max_l_h"])

    def test_bad_realtime_data_enters_abnormal_and_holds_last_value(self):
        con = self.memory_db()
        now = datetime.now().replace(second=0, microsecond=0)
        first = calculate_for_point(con, 1, now=now, save=True)
        tag = con.execute("SELECT id,unit FROM sensor_tags WHERE tag_code='PAC1_Q'").fetchone()
        bad_time = now + timedelta(minutes=1)
        con.execute(
            "INSERT OR REPLACE INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source) VALUES(?,?,?,?,?,?,?)",
            (tag["id"], 1000.0, tag["unit"], bad_time.isoformat(), bad_time.isoformat(), "bad", "s7comm"),
        )
        second = calculate_for_point(con, 1, now=bad_time, save=False)
        self.assertEqual(second["mode"], "abnormal")
        self.assertAlmostEqual(second["final_l_h"], first["final_l_h"])

    def test_manual_source_is_not_valid_for_calculation(self):
        con = self.memory_db()
        tag = con.execute("SELECT id FROM sensor_tags WHERE tag_code='PAC1_Q'").fetchone()
        point = latest_data_for_tag(con, tag["id"], "IN_Q", "进水流量", "m3/h")
        self.assertEqual(point.status, "fresh")
        now = datetime.now().replace(second=0, microsecond=0)
        con.execute(
            "UPDATE sensor_tags SET last_value_text='1000', last_quality='good', last_read_at=?, source='manual' WHERE id=?",
            (now.isoformat(), tag["id"]),
        )
        point = latest_data_for_tag(con, tag["id"], "IN_Q", "进水流量", "m3/h", now=now)
        self.assertEqual(point.status, "bad")

    def test_k_ai_model_kind_is_rejected(self):
        with self.assertRaises(ValidationError):
            ModelProjectCreate(name="旧KAI", dosing_point_id=1, model_kind="k_ai")

    def test_dose_predict_model_kind_is_rejected(self):
        with self.assertRaises(ValidationError):
            ModelProjectCreate(name="投加量预测", dosing_point_id=1, model_kind="dose_predict")

    def test_pac_flow_predict_model_kind_is_accepted(self):
        model = ModelProjectCreate(name="加药流量预测", model_kind="pac_flow_predict")
        self.assertEqual(model.model_kind, "pac_flow_predict")
        self.assertIsNone(model.dosing_point_id)

    def test_listen_port_setting_validation(self):
        self.assertEqual(validate_setting_value("listen_port", "9000"), "9000")
        self.assertEqual(normalize_listen_port("9000"), 9000)
        with self.assertRaises(HTTPException):
            validate_setting_value("listen_port", "70000")
        with self.assertRaises(HTTPException):
            validate_setting_value("listen_port", "abc")
        with self.assertRaises(HTTPException):
            validate_setting_value("demo_live_refresh", "false")
        with self.assertRaises(HTTPException):
            validate_setting_value("backup_dir", "backup")

    def test_default_settings_cleanup_obsolete_keys(self):
        con = self.memory_db()
        con.execute(
            "INSERT OR REPLACE INTO app_settings(key,value,updated_at) VALUES(?,?,?)",
            ("backup_dir", "custom", datetime.now().isoformat()),
        )
        con.execute(
            "INSERT OR REPLACE INTO app_settings(key,value,updated_at) VALUES(?,?,?)",
            ("demo_live_refresh", "true", datetime.now().isoformat()),
        )
        ensure_default_app_settings(con)
        self.assertIsNone(con.execute("SELECT key FROM app_settings WHERE key='backup_dir'").fetchone())
        self.assertIsNotNone(con.execute("SELECT key FROM app_settings WHERE key='listen_port'").fetchone())
        self.assertIsNone(con.execute("SELECT key FROM app_settings WHERE key='demo_live_refresh'").fetchone())

    def test_model_inputs_have_no_monotone_constraints(self):
        feature_keys = [
            "Q",
            "TP_BEFORE",
            "PH",
            "TP_OUT",
            "REFLUX_Q1",
            "REFLUX_Q2",
            "BIO_ORP1",
            "BIO_ORP2",
            "BIO_ORP3",
            "BIO_ORP4",
            "BIO_MLSS1",
            "BIO_MLSS2",
        ]
        self.assertEqual(
            monotone_constraints_for_features(feature_keys),
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        )

    def test_model_csv_time_accepts_slash_date_with_extra_spaces(self):
        self.assertEqual(parse_model_csv_sample_time("2026/5/20  0:00:00", 2), "2026-05-20T00:00:00")

    def test_tp_forecast_schema_uses_reduced_feature_set(self):
        con = self.memory_db()
        schema = current_model_feature_schema(con, 1, "tp_out_response")
        self.assertEqual(
            [item["key"] for item in schema],
            [
                "Q",
                "TP_BEFORE",
                "PH",
                "TP_OUT",
                "REFLUX_Q1",
                "REFLUX_Q2",
                "BIO_ORP1",
                "BIO_ORP2",
                "BIO_ORP3",
                "BIO_ORP4",
                "BIO_MLSS1",
                "BIO_MLSS2",
            ],
        )
        pac_schema = current_model_feature_schema(con, 1, "pac_flow_predict")
        self.assertEqual([item["key"] for item in pac_schema], [item["key"] for item in schema])

    def test_tp_response_model_forecast_uses_next_sample_target(self):
        con = self.memory_db()
        schema = [
            {"key": "Q", "label": "参考流量", "tag_code": "Q"},
            {"key": "PAC_ACTUAL", "label": "实际加药流量", "tag_code": None},
        ]
        cur = con.execute(
            """
            INSERT INTO model_projects(name,dosing_point_id,model_kind,status,sample_interval_minutes,feature_schema_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            ("tp-forecast", 1, "tp_out_response", "draft", 5, dumps_json(schema), "2026-06-26T10:00:00", "2026-06-26T10:00:00"),
        )
        model = con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone()
        csv_text = (
            "时间,参考流量,实际加药流量,下一次出水TP检测数据\n"
            "2026/5/20  0:00:00,1000,20,0.28\n"
            "2026-06-26T10:05:00,1200,30,0.18\n"
            "2026-06-26T10:10:00,1400,40,0.11\n"
        )
        import_model_csv_samples(con, model, csv_text)
        stored_time = con.execute(
            "SELECT sample_time FROM model_training_samples WHERE model_project_id=? ORDER BY sample_time LIMIT 1",
            (cur.lastrowid,),
        ).fetchone()["sample_time"]
        self.assertEqual(stored_time, "2026-05-20T00:00:00")
        trained = train_model_project_artifact(con, con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone())
        self.assertEqual(trained["artifact"]["format"], "ai_pac_tp_forecast_v3")
        self.assertEqual(trained["artifact"]["target"], "TP_OUT_NEXT")
        self.assertIn("booster_model", trained["artifact"])
        con.execute("UPDATE model_projects SET status='published',published_at=? WHERE id=?", ("2026-06-26T11:00:00", cur.lastrowid))
        con.execute("UPDATE dosing_points SET tp_model_id=? WHERE id=1", (cur.lastrowid,))
        result = calculate_for_point(con, 1, save=False)
        self.assertEqual(result["mode"], "conservative")
        self.assertIsNotNone(result["tp_forecast"])
        self.assertIn("predicted_tp_out", result["tp_forecast"])
        self.assertEqual(result["tp_forecast"]["target_label"], "下一次出水TP检测数据")
        self.assertNotIn("horizon_minutes", result["tp_forecast"])
        self.assertTrue(result["reasons"])

    def test_pac_flow_model_trains_with_actual_pac_target(self):
        con = self.memory_db()
        schema = [
            {"key": "Q", "label": "参考流量", "tag_code": "Q"},
            {"key": "TP_OUT", "label": "出水TP", "tag_code": None},
        ]
        cur = con.execute(
            """
            INSERT INTO model_projects(name,dosing_point_id,model_kind,status,sample_interval_minutes,feature_schema_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            ("pac-flow", 1, "pac_flow_predict", "draft", 5, dumps_json(schema), "2026-06-26T10:00:00", "2026-06-26T10:00:00"),
        )
        model = con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone()
        csv_text = (
            "时间,参考流量,出水TP,实际加药流量\n"
            "2026-06-26T10:00:00,1000,0.28,20\n"
            "2026-06-26T10:05:00,1200,0.22,30\n"
            "2026-06-26T10:10:00,1400,0.16,40\n"
        )
        import_model_csv_samples(con, model, csv_text)
        trained = train_model_project_artifact(con, con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone())
        self.assertEqual(trained["artifact"]["format"], "ai_pac_flow_predict_v1")
        self.assertEqual(trained["artifact"]["target"], "PAC_ACTUAL")
        self.assertIn("booster_model", trained["artifact"])
        con.execute("UPDATE model_projects SET status='published',published_at=? WHERE id=?", ("2026-06-26T11:00:00", cur.lastrowid))
        con.execute("UPDATE dosing_points SET pac_flow_model_id=? WHERE id=1", (cur.lastrowid,))
        result = calculate_for_point(con, 1, save=True)
        control = con.execute("SELECT * FROM process_parameter_groups ORDER BY id LIMIT 1").fetchone()
        self.assertEqual(result["mode"], "normal")
        self.assertGreaterEqual(result["final_l_h"], float(control["pac_min_l_h"]))
        self.assertLessEqual(result["final_l_h"], float(control["pac_max_l_h"]))
        explanation = con.execute(
            "SELECT explanation_json FROM recommendation_explanations WHERE recommendation_id=?",
            (result["id"],),
        ).fetchone()
        detail = loads_json(explanation["explanation_json"], {})["ai_detail"]
        self.assertEqual(detail["feature_overrides"]["TP_OUT"], float(control["tp_target_mg_l"]))
        self.assertEqual(detail["features"]["TP_OUT"], float(control["tp_target_mg_l"]))

    def test_training_config_controls_features_and_lgb_params(self):
        con = self.memory_db()
        schema = [
            {"key": "Q", "label": "参考流量", "tag_code": "Q"},
            {"key": "TP_OUT", "label": "出水TP", "tag_code": None},
        ]
        training_config = normalize_training_config(
            {
                "feature_columns": ["Q"],
                "objective": "regression_l2",
                "num_boost_round": 30,
                "early_stopping_rounds": 5,
                "monotone_constraints": {"Q": -1},
                "sample_weight_rule": "high_target",
            },
            "pac_flow_predict",
            schema,
        )
        cur = con.execute(
            """
            INSERT INTO model_projects(name,dosing_point_id,model_kind,status,sample_interval_minutes,feature_schema_json,training_config_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "pac-flow-configured",
                1,
                "pac_flow_predict",
                "draft",
                5,
                dumps_json(schema),
                dumps_json(training_config),
                "2026-06-26T10:00:00",
                "2026-06-26T10:00:00",
            ),
        )
        model = con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone()
        csv_text = (
            "时间,参考流量,出水TP,实际加药流量\n"
            "2026-06-26T10:00:00,1000,0.28,20\n"
            "2026-06-26T10:05:00,1200,0.22,30\n"
            "2026-06-26T10:10:00,1400,0.16,40\n"
            "2026-06-26T10:15:00,1600,0.12,50\n"
        )
        import_model_csv_samples(con, model, csv_text)
        trained = train_model_project_artifact(con, con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone())
        self.assertEqual(trained["artifact"]["feature_names"], ["Q"])
        self.assertEqual(trained["artifact"]["training_config"]["objective"], "regression_l2")
        self.assertEqual(trained["artifact"]["training_config"]["num_boost_round"], 30)
        self.assertEqual(trained["artifact"]["lightgbm_params"]["monotone_constraints"], [-1])

    def test_training_config_allows_zero_prediction_step(self):
        schema = [{"key": "Q", "label": "参考流量", "tag_code": "Q"}]
        config = normalize_training_config(
            {"feature_columns": ["Q"], "prediction_step": 0},
            "tp_out_response",
            schema,
        )
        self.assertEqual(config["prediction_step"], 0)

    def test_realtime_record_writes_current_tp_target_when_step_zero(self):
        con = self.memory_db()
        schema = current_model_feature_schema(con, 1, "tp_out_response")
        training_config = normalize_training_config(
            {"feature_columns": [item["key"] for item in schema], "prediction_step": 0},
            "tp_out_response",
            schema,
        )
        cur = con.execute(
            """
            INSERT INTO model_projects(name,dosing_point_id,model_kind,status,sample_interval_minutes,feature_schema_json,training_config_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "tp-record-step-zero",
                1,
                "tp_out_response",
                "draft",
                5,
                dumps_json(schema),
                dumps_json(training_config),
                "2026-06-26T10:00:00",
                "2026-06-26T10:00:00",
            ),
        )
        model = con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone()
        result = record_model_project_sample(con, model)
        self.assertIsNotNone(result["sample_id"])
        sample = con.execute(
            "SELECT * FROM model_training_samples WHERE id=?",
            (result["sample_id"],),
        ).fetchone()
        values = loads_json(sample["values_json"], {})
        self.assertIn("_training_target_tp_out_next", values)
        columns = {row["name"] for row in con.execute("PRAGMA table_info(model_training_samples)").fetchall()}
        target_column = "target_value" if "target_value" in columns else "k_ai"
        self.assertIsNotNone(sample[target_column])

    def test_plc_device_rows_do_not_report_connected_without_runtime_client(self):
        con = self.memory_db()
        plc_devices.plc_client_store().clear()
        con.execute("UPDATE plc_devices SET status='connected' WHERE id=1")
        rows = plc_devices.plc_device_rows(con)
        device = next(row for row in rows if row["id"] == 1)
        self.assertFalse(device["runtime_connected"])
        self.assertEqual(device["status"], "disconnected")

    def test_collection_poll_reconnects_when_db_status_is_connected(self):
        con = self.memory_db()
        plc_devices.plc_client_store().clear()
        tag = con.execute("SELECT id FROM sensor_tags WHERE tag_code='PAC1_Q'").fetchone()
        con.execute(
            """
            UPDATE sensor_tags
            SET plc_device_id=1,data_address='DB1.0',data_type='REAL',last_read_at=NULL,last_error=NULL
            WHERE id=?
            """,
            (tag["id"],),
        )
        con.execute("UPDATE plc_devices SET status='connected',enabled=1 WHERE id=1")

        class FakeClient:
            def get_connected(self):
                return True

        original_connect = plc_devices.connect_s7_1500
        original_read = collection_runtime.read_s7_value
        try:
            plc_devices.connect_s7_1500 = lambda **_kwargs: PlcConnectResult(
                ok=True,
                status="connected",
                message="ok",
                pdu_length=480,
                client=FakeClient(),
            )
            collection_runtime.read_s7_value = lambda _client, address, data_type: PlcReadResult(
                value=12.5,
                value_text="12.5",
                numeric_value=12.5,
                address=address,
                data_type=data_type,
                byte_length=4,
            )
            rows = collection_runtime.collection_due_rows(con, dosing_point_id=1, force=False)
            result = collection_runtime.poll_collection_rows(con, rows, force_history=True)
        finally:
            plc_devices.connect_s7_1500 = original_connect
            collection_runtime.read_s7_value = original_read
            plc_devices.plc_client_store().clear()

        self.assertEqual(result["read_failed"], 0)
        self.assertGreaterEqual(result["read_ok"], 1)
        updated = con.execute("SELECT last_quality,last_value_text,last_error FROM sensor_tags WHERE id=?", (tag["id"],)).fetchone()
        self.assertEqual(updated["last_quality"], "good")
        self.assertEqual(updated["last_value_text"], "12.5")
        self.assertIsNone(updated["last_error"])


if __name__ == "__main__":
    unittest.main()
