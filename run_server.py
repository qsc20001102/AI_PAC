from __future__ import annotations

import uvicorn

from app.database import db_session, init_schema
from app.services.settings_config import ensure_default_app_settings, get_configured_listen_port


def configured_port() -> int:
    init_schema()
    with db_session() as con:
        ensure_default_app_settings(con)
        return get_configured_listen_port(con)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=configured_port())
