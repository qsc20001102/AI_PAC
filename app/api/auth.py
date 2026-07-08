from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.auth import authenticate, change_password, get_user_by_token, revoke_token

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    old_password: str
    new_password: str


def _token_from_request(request: Request) -> str | None:
    return request.headers.get("x-token") or request.headers.get("X-Token")


@router.post("/api/auth/login")
def login(body: LoginBody) -> dict[str, Any]:
    user = authenticate(body.username.strip(), body.password)
    if not user:
        # P0-5 修复：统一使用 raise HTTPException，与其他模块错误返回方式保持一致
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"ok": True, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}, "token": user["token"]}


@router.get("/api/auth/me")
def me(request: Request) -> dict[str, Any]:
    token = _token_from_request(request)
    user = get_user_by_token(token)
    if not user:
        return {"authenticated": False, "role": "guest"}
    return {"authenticated": True, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}


@router.post("/api/auth/logout")
def logout(request: Request) -> dict[str, Any]:
    token = _token_from_request(request)
    if token:
        revoke_token(token)
    return {"ok": True}


@router.put("/api/auth/password")
def password(body: PasswordBody, request: Request) -> dict[str, Any]:
    token = _token_from_request(request)
    user = get_user_by_token(token)
    if not user:
        # P0-5 修复：统一使用 raise HTTPException
        raise HTTPException(status_code=401, detail="未登录")
    if len(body.new_password) < 6:
        # P0-5 修复：统一使用 raise HTTPException
        raise HTTPException(status_code=400, detail="新密码至少6位")
    result = change_password(user["id"], body.old_password, body.new_password)
    if not result["ok"]:
        # P0-5 修复：统一使用 raise HTTPException
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}
