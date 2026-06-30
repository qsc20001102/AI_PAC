from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta

from pydantic import ValidationError

from app.api.models import create_model_project
from app.database import SCHEMA, dumps_json, ensure_runtime_schema
from app.schemas import ModelProjectCreate
from app.services.model_training import import_model_csv_samples, train_model_project_artifact
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

    def test_tp_response_model_forecast_uses_configured_horizon(self):
        con = self.memory_db()
        con.execute("UPDATE process_parameter_groups SET forecast_horizon_minutes=30 WHERE id=1")
        schema = [
            {"key": "Q", "label": "参考流量", "tag_code": "Q"},
            {"key": "TP_OUT", "label": "当前出水总磷", "tag_code": None},
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
            "时间,参考流量,当前出水总磷,实际加药流量,未来30分钟出水TP,未来60分钟出水TP,未来120分钟出水TP\n"
            "2026-06-26T10:00:00,1000,0.2,20,0.30,0.28,0.26\n"
            "2026-06-26T10:05:00,1200,0.25,30,0.20,0.18,0.17\n"
            "2026-06-26T10:10:00,1400,0.28,40,0.12,0.11,0.10\n"
        )
        import_model_csv_samples(con, model, csv_text)
        trained = train_model_project_artifact(con, con.execute("SELECT * FROM model_projects WHERE id=?", (cur.lastrowid,)).fetchone())
        self.assertEqual(trained["artifact"]["format"], "ai_pac_tp_forecast_v2")
        self.assertEqual(sorted(trained["artifact"]["booster_models"].keys()), ["120", "30", "60"])
        con.execute("UPDATE model_projects SET status='published',published_at=? WHERE id=?", ("2026-06-26T11:00:00", cur.lastrowid))
        result = calculate_for_point(con, 1, save=False)
        self.assertEqual(result["mode"], "conservative")
        self.assertIsNotNone(result["tp_forecast"])
        self.assertEqual(sorted(result["tp_forecast"]["predictions"].keys()), ["120", "30", "60"])
        self.assertEqual(result["tp_forecast"]["horizon_minutes"], 30)
        self.assertEqual(result["tp_forecast"]["predicted_tp_out"], result["tp_forecast"]["predictions"]["30"])
        self.assertTrue(any("回退保守模式" in reason for reason in result["reasons"]))


if __name__ == "__main__":
    unittest.main()
