import unittest
import sqlite3
from datetime import datetime

from app.api.models import model_feature_schema, model_project_or_404
from app.database import SCHEMA, dumps_json, ensure_runtime_schema
from app.schemas import IngestSampleIn
from app.services.collection_data import data_quality_rows, write_ingested_samples
from app.services.model_training import import_model_csv_samples, record_model_project_sample, train_model_project_artifact
from app.services.seed import ensure_seed_data
from app.services.recommendation import calculate_mechanism_base, clamp, latest_data_for_tag


class RecommendationFormulaTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-1, 0, 10), 0)
        self.assertEqual(clamp(12, 0, 10), 10)

    def test_mechanism_formula_matches_manual_check(self):
        pac = {
            "pac_density_kg_l": 1.20,
            "al2o3_fraction": 0.018,
            "effective_factor": 0.90,
            "al_p_ratio": 3.40,
        }
        result = calculate_mechanism_base(1276.52, 0.0984, pac)
        self.assertAlmostEqual(result, 36.14, places=1)

    def test_ingested_sample_is_written_to_database(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        ensure_seed_data(con)
        written, affected, errors = write_ingested_samples(
            con,
            [
                IngestSampleIn(
                    tag_code="PAC1_PO4_P",
                    value=0.37,
                    sample_time="2026-06-25T10:00:00",
                    source="unit_test",
                )
            ],
        )
        self.assertEqual(errors, [])
        self.assertEqual(written, 1)
        self.assertIn(1, affected)
        row = con.execute(
            """
            SELECT ss.value, ss.source
            FROM sensor_samples ss
            JOIN sensor_tags st ON st.id=ss.tag_id
            WHERE st.tag_code='PAC1_PO4_P' AND ss.sample_time='2026-06-25T10:00:00'
            """
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["value"], 0.37)
        self.assertEqual(row["source"], "unit_test")

    def test_recommendation_uses_newer_realtime_reading_before_history_storage(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        ensure_seed_data(con)
        tag = con.execute("SELECT * FROM sensor_tags WHERE tag_code='PAC2_Q'").fetchone()
        self.assertIsNotNone(tag)
        con.execute("DELETE FROM sensor_samples WHERE tag_id=?", (tag["id"],))
        con.execute(
            """
            UPDATE sensor_tags
            SET last_quality='good', last_value_text='536.712', last_read_at='2026-06-26T14:31:22'
            WHERE id=?
            """,
            (tag["id"],),
        )
        con.execute(
            """
            INSERT INTO sensor_samples(tag_id,value,unit,sample_time,receive_time,quality,source)
            VALUES(?,?,?,?,?,?,?)
            """,
            (tag["id"], 527.56, "m3/h", "2026-06-26T14:21:35", "2026-06-26T14:21:35", "good", "s7comm"),
        )

        point = latest_data_for_tag(
            con,
            tag["id"],
            "ZONE_Q",
            "分区流量",
            "m3/h",
            now=datetime.fromisoformat("2026-06-26T14:32:00"),
        )

        self.assertIsNotNone(point)
        self.assertEqual(point.status, "fresh")
        self.assertAlmostEqual(point.value, 536.712)
        self.assertEqual(point.sample_time, "2026-06-26T14:31:22")

    def test_dashboard_data_quality_prefers_realtime_collection_fields(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        ensure_seed_data(con)
        tag = con.execute("SELECT * FROM sensor_tags WHERE tag_code='PAC2_Q'").fetchone()
        self.assertIsNotNone(tag)
        read_at = datetime.now().replace(microsecond=0).isoformat()
        con.execute(
            """
            UPDATE sensor_tags
            SET last_quality='good', last_value_text='531.141', last_read_at=?
            WHERE id=?
            """,
            (read_at, tag["id"]),
        )

        row = next(item for item in data_quality_rows(con) if item["id"] == tag["id"])

        self.assertEqual(row["value"], "531.141")
        self.assertEqual(row["sample_time"], read_at)
        self.assertEqual(row["quality"], "good")
        self.assertEqual(row["status"], "fresh")

    def test_model_training_samples_and_artifact_are_persisted(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        ensure_runtime_schema(con)
        ensure_seed_data(con)
        schema = model_feature_schema(con, 1)
        cur = con.execute(
            """
            INSERT INTO model_projects(
                name,dosing_point_id,status,sample_interval_minutes,feature_schema_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            ("unit-model", 1, "draft", 5, dumps_json(schema), "2026-06-26T10:00:00", "2026-06-26T10:00:00"),
        )
        model = model_project_or_404(con, cur.lastrowid)
        first = record_model_project_sample(con, model)
        second = record_model_project_sample(con, model)
        self.assertIsNotNone(first["k_ai"])
        self.assertIsNotNone(second["suggested_l_h"])

        rows = con.execute(
            "SELECT id FROM model_training_samples WHERE model_project_id=? ORDER BY id",
            (cur.lastrowid,),
        ).fetchall()
        con.execute(
            "UPDATE model_training_samples SET values_json=? WHERE id=?",
            (dumps_json({"IN_Q": 1000.0, "_training_target_k_ai": 0.9}), rows[0]["id"]),
        )
        con.execute(
            "UPDATE model_training_samples SET values_json=? WHERE id=?",
            (dumps_json({"IN_Q": 1300.0, "_training_target_k_ai": 1.15}), rows[1]["id"]),
        )

        trained = train_model_project_artifact(con, model_project_or_404(con, cur.lastrowid))
        saved = model_project_or_404(con, cur.lastrowid)
        self.assertEqual(trained["metrics"]["samples"], 2)
        self.assertEqual(trained["artifact"]["format"], "ai_pac_lightgbm_v1")
        self.assertEqual(saved["status"], "ready")
        self.assertIsNotNone(saved["trained_at"])

    def test_model_csv_import_fills_missing_suggestion_and_k_ai(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        ensure_runtime_schema(con)
        ensure_seed_data(con)
        schema = model_feature_schema(con, 1)
        cur = con.execute(
            """
            INSERT INTO model_projects(
                name,dosing_point_id,status,sample_interval_minutes,feature_schema_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            ("csv-model", 1, "draft", 5, dumps_json(schema), "2026-06-26T10:00:00", "2026-06-26T10:00:00"),
        )
        model = model_project_or_404(con, cur.lastrowid)
        headers = ["时间", *[(item.get("tag_code") or item["label"]) for item in schema]]
        values_by_key = {
            "IN_Q": 1000.0,
            "TP_BEFORE": 0.32,
            "OUT_Q": 980.0,
            "TP_OUT": 0.16,
            "ZONE_Q": 520.0,
            "REFLUX_Q1": 0.0,
            "REFLUX_Q2": 0.0,
            "PO4_P": 0.28,
            "PAC_ACTUAL": 12.0,
        }
        row = ["2026-06-26T10:00:00", *[values_by_key.get(item["key"], "") for item in schema]]
        csv_text = ",".join(headers) + "\n" + ",".join(str(item) for item in row) + "\n"

        result = import_model_csv_samples(con, model, csv_text)
        self.assertEqual(result["written"], 1)
        self.assertEqual(result["generated_suggested"], 1)
        self.assertEqual(result["generated_k_ai"], 1)
        sample = con.execute(
            "SELECT * FROM model_training_samples WHERE model_project_id=?",
            (cur.lastrowid,),
        ).fetchone()
        self.assertIsNotNone(sample["suggested_l_h"])
        self.assertIsNotNone(sample["k_ai"])
        self.assertIn("_training_target_k_ai", sample["values_json"])


if __name__ == "__main__":
    unittest.main()
