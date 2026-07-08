from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

from app.api.alarms import router as alarms_router
from app.api.auth import router as auth_router
from app.api.collection import router as collection_router
from app.api.dashboard import router as dashboard_router
from app.api.dosing_points import router as dosing_points_router
from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.models import router as models_router
from app.api.plc import router as plc_router
from app.api.process_groups import router as process_groups_router
from app.api.settings import router as settings_router
from app.api.trends import router as trends_router
from app.database import (
    db_session,
    init_schema,
    utc_now_iso,
)
from app.services.collection_runtime import collection_loop
from app.services.plc import disconnect_client
from app.services.plc_devices import auto_connect_enabled_plc_devices, plc_client_store
from app.api.dosing_points import ensure_virtual_point_tags
from app.services.recommendation import recalculate_all
from app.services.auth import ensure_default_users
from app.services.seed import ensure_seed_data
from app.services.settings_config import get_plc_auto_connect_enabled


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


# P2-1 修复：将废弃的 @app.on_event("startup"/"shutdown") 迁移到 FastAPI lifespan 上下文管理器。
# P2-2 修复：移除未使用的 from starlette.responses import Response 和 from fastapi.staticfiles import StaticFiles。
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup ----
    init_schema()
    ensure_default_users()
    plc_client_store().clear()
    with db_session() as con:
        ensure_seed_data(con)
        con.execute(
            """
            UPDATE plc_devices
            SET status='disconnected', last_disconnected_at=?, last_error='服务启动后连接已释放'
            WHERE status='connected'
            """,
            (utc_now_iso(),),
        )
        if get_plc_auto_connect_enabled(con):
            auto_connect_enabled_plc_devices(con)
        for row in con.execute("SELECT id, code FROM dosing_points ORDER BY id").fetchall():
            ensure_virtual_point_tags(con, int(row["id"]), row["code"])
        recalculate_all(con)
    app.state.collector_task = asyncio.create_task(collection_loop())

    yield

    # ---- shutdown ----
    task = getattr(app.state, "collector_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    for client in list(plc_client_store().values()):
        disconnect_client(client)
    plc_client_store().clear()


app = FastAPI(
    title="智能污水除磷药系统",
    version="0.1.0",
    description="本地部署的智能污水除磷药系统，输出可解释、可限幅、可回退的建议 L/h。",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(alarms_router)
app.include_router(process_groups_router)
app.include_router(settings_router)
app.include_router(models_router)
app.include_router(dashboard_router)
app.include_router(dosing_points_router)
app.include_router(plc_router)
app.include_router(collection_router)
app.include_router(ingest_router)
app.include_router(trends_router)


class NoCacheStaticFiles(StarletteStaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

if STATIC_DIR.exists():
    app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )
