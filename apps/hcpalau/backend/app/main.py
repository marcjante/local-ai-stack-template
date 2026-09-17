"""HC Palau FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlmodel import Session
from sqlalchemy import text

from .config import get_settings, validate_runtime_settings
from .database import create_db_and_tables
from .database import get_session
from .routers.attendance import router as attendance_router
from .routers.activity import router as activity_router
from .routers.convocations import router as convocations_router
from .routers.exam_periods import router as exam_periods_router
from .routers.events import router as events_router
from .routers.exercise_progress import router as exercise_progress_router
from .routers.exercises import router as exercises_router
from .routers.goals import router as goals_router
from .routers.mvp import router as mvp_router
from .routers.notifications import router as notifications_router
from .routers.players import router as players_router
from .routers.player_stats import router as player_stats_router
from .routers.reinforcements import router as reinforcements_router
from .routers.routines import router as routines_router
from .routers.seguiment import router as seguiment_router
from .routers.session import router as session_router
from .routers.standings import router as standings_router


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_settings(get_settings())
    create_db_and_tables()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="HC Palau Infantil D API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(players_router)
    application.include_router(events_router)
    application.include_router(attendance_router)
    application.include_router(activity_router)
    application.include_router(goals_router)
    application.include_router(exercises_router)
    application.include_router(exercise_progress_router)
    application.include_router(convocations_router)
    application.include_router(routines_router)
    application.include_router(exam_periods_router)
    application.include_router(standings_router)
    application.include_router(mvp_router)
    application.include_router(notifications_router)
    application.include_router(seguiment_router)
    application.include_router(reinforcements_router)
    application.include_router(player_stats_router)
    application.include_router(session_router)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "hcpalau"}

    @application.get("/ready", tags=["system"])
    def ready(session: Session = Depends(get_session)) -> JSONResponse:
        try:
            session.exec(text("SELECT 1"))
        except Exception:
            return JSONResponse(
                {"status": "not_ready", "service": "hcpalau"},
                status_code=503,
            )
        return JSONResponse({"status": "ready", "service": "hcpalau"})

    application.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return application


app = create_app()
