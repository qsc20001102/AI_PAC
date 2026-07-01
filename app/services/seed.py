from __future__ import annotations

import sqlite3
from datetime import datetime

from app.database import table_count
from app.services.settings_config import ensure_default_app_settings


def ensure_seed_data(con: sqlite3.Connection) -> None:
    """Create only the minimum project shell required for a blank deployment."""
    now_iso = datetime.now().replace(second=0, microsecond=0).isoformat()
    if table_count(con, "plants") == 0:
        con.execute(
            "INSERT INTO plants(id,name,location,created_at) VALUES(1,?,?,?)",
            ("PAC Plant", "Local deployment", now_iso),
        )
    if table_count(con, "process_areas") == 0:
        con.execute("INSERT INTO process_areas(id,plant_id,name) VALUES(1,1,?)", ("Process Area",))
    if table_count(con, "process_lines") == 0:
        con.execute(
            "INSERT INTO process_lines(id,area_id,name,line_code,design_flow_m3_h) VALUES(?,?,?,?,?)",
            (1, 1, "Process Line 1", "LINE_1", 0),
        )
    ensure_default_app_settings(con)
