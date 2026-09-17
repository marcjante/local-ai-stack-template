"""HC Palau FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import create_db_and_tables
from .routers.attendance import router as attendance_router
from .routers.convocations import router as convocations_router
from .routers.exam_periods import router as exam_periods_router
from .routers.events import router as events_router
from .routers.exercise_progress import router as exercise_progress_router
from .routers.exercises import router as exercises_router
from .routers.goals import router as goals_router
from .routers.players import router as players_router
from .routers.routines import router as routines_router
from .routers.standings import router as standings_router


@asynccontextmanager
async def lifespan(_: FastAPI):
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
    application.include_router(goals_router)
    application.include_router(exercises_router)
    application.include_router(exercise_progress_router)
    application.include_router(convocations_router)
    application.include_router(routines_router)
    application.include_router(exam_periods_router)
    application.include_router(standings_router)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "hcpalau"}

    return application


app = create_app()
