from __future__ import annotations

from typing import Any

from app.database import dumps_json, utc_now_iso


def audit(con, actor: str, action: str, entity_type: str, entity_id: str, detail: dict[str, Any]) -> None:
    con.execute(
        """
        INSERT INTO audit_logs(actor,action,entity_type,entity_id,detail_json,created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (actor, action, entity_type, entity_id, dumps_json(detail), utc_now_iso()),
    )
