from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from app.database import db_session


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwdhash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return salt + pwdhash.hex()


def _verify_password(password: str, stored: str) -> bool:
    if len(stored) < 64:
        return False
    salt = stored[:32]
    expected_hash = stored[32:]
    pwdhash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return secrets.compare_digest(expected_hash, pwdhash.hex())


def ensure_default_users() -> None:
    with db_session() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        count = con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count == 0:
            now = datetime.now().isoformat()
            con.execute(
                "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("emen", _hash_password("emen@1234"), "admin", now, now),
            )
            con.execute(
                "INSERT INTO users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("uesr", _hash_password("123456"), "user", now, now),
            )


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    with db_session() as con:
        row = con.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not row:
            return None
        if not _verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now() + timedelta(days=7)).isoformat()
        now = datetime.now().isoformat()
        con.execute(
            "INSERT INTO user_sessions (user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (row["id"], token, expires_at, now),
        )
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "token": token,
        }


def get_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with db_session() as con:
        row = con.execute(
            """
            SELECT u.id, u.username, u.role, s.expires_at
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            con.execute("DELETE FROM user_sessions WHERE token=?", (token,))
            return None
        return {"id": row["id"], "username": row["username"], "role": row["role"]}


def revoke_token(token: str) -> None:
    with db_session() as con:
        con.execute("DELETE FROM user_sessions WHERE token=?", (token,))


def change_password(user_id: int, old_password: str, new_password: str) -> dict[str, Any]:
    with db_session() as con:
        row = con.execute(
            "SELECT password_hash FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "用户不存在"}
        if not _verify_password(old_password, row["password_hash"]):
            return {"ok": False, "error": "旧密码错误"}
        new_hash = _hash_password(new_password)
        now = datetime.now().isoformat()
        con.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (new_hash, now, user_id),
        )
        con.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        return {"ok": True}
