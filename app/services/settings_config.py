from __future__ import annotations

import sqlite3

from app.database import utc_now_iso


DEFAULT_LISTEN_PORT = 8000
LISTEN_PORT_KEY = "listen_port"
PLC_AUTO_CONNECT_KEY = "plc_auto_connect"

SETTING_DEFINITIONS: dict[str, dict[str, str]] = {
    LISTEN_PORT_KEY: {
        "label": "Web端口",
        "description": "项目 Web 服务监听端口，修改后需要重启服务生效。",
        "value_type": "number",
    },
    PLC_AUTO_CONNECT_KEY: {
        "label": "PLC自动连接",
        "description": "开启后项目启动完成会自动连接已启用的 PLC 设备；关闭后启动时不自动连接。",
        "value_type": "boolean",
    }
}

OBSOLETE_SETTING_KEYS = {
    "backup_dir",
    "deployment_mode",
    "demo_live_refresh",
    "retention_alarm_days",
    "retention_raw_days",
    "seeded_at",
    "write_policy",
}


def normalize_listen_port(value: str | int | None, default: int = DEFAULT_LISTEN_PORT) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if port < 1 or port > 65535:
        return default
    return port


def get_setting_value(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else None


def get_configured_listen_port(con: sqlite3.Connection) -> int:
    return normalize_listen_port(get_setting_value(con, LISTEN_PORT_KEY))


def get_bool_setting(con: sqlite3.Connection, key: str, default: bool = False) -> bool:
    value = get_setting_value(con, key)
    if value is None:
        return default
    return str(value).strip().lower() == "true"


def get_plc_auto_connect_enabled(con: sqlite3.Connection) -> bool:
    return get_bool_setting(con, PLC_AUTO_CONNECT_KEY, default=True)


def enrich_setting_row(row: sqlite3.Row) -> dict[str, str]:
    data = dict(row)
    definition = SETTING_DEFINITIONS.get(str(row["key"]), {})
    data["label"] = definition.get("label", str(row["key"]))
    data["description"] = definition.get("description", "")
    data["value_type"] = definition.get("value_type", "text")
    return data


def ensure_default_app_settings(con: sqlite3.Connection) -> None:
    now = utc_now_iso()
    defaults = {
        LISTEN_PORT_KEY: str(DEFAULT_LISTEN_PORT),
        PLC_AUTO_CONNECT_KEY: "true",
    }
    if OBSOLETE_SETTING_KEYS:
        placeholders = ",".join("?" for _ in OBSOLETE_SETTING_KEYS)
        con.execute(f"DELETE FROM app_settings WHERE key IN ({placeholders})", tuple(sorted(OBSOLETE_SETTING_KEYS)))
    for key, value in defaults.items():
        con.execute(
            """
            INSERT INTO app_settings(key,value,updated_at)
            VALUES(?,?,?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, value, now),
        )
