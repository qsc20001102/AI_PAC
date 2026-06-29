from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.alarms import router as alarms_router
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
from app.services.collection_runtime import collection_loop, model_recording_loop
from app.services.plc import disconnect_client
from app.services.plc_devices import plc_client_store
from app.services.recommendation import recalculate_all
from app.services.seed import ensure_seed_data


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="AI 智能 PAC 除磷加药平台",
    version="0.1.0",
    description="本地部署的 PAC 除磷建议加药系统，输出可解释、可限幅、可回退的建议 L/h。",
)

app.include_router(health_router)
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


@app.on_event("startup")
def startup() -> None:
    init_schema()
    plc_client_store().clear()
    app.state.collector_task = asyncio.create_task(collection_loop())
    app.state.model_recording_task = asyncio.create_task(model_recording_loop())
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
        recalculate_all(con)


@app.on_event("shutdown")
async def shutdown() -> None:
    for task_name in ("collector_task", "model_recording_task"):
        task = getattr(app.state, task_name, None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    for client in list(plc_client_store().values()):
        disconnect_client(client)
    plc_client_store().clear()


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )
