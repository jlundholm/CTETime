import logging
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import aiosqlite
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.admin.routes import router as admin_router
from app.auth.routes import router as auth_router
from app.config import get_settings
from app.database import run_migrations
from app.student.routes import router as student_router
from app.teacher.routes import router as teacher_router


logger = logging.getLogger(__name__)


def _ensure_required_directories(database_path: str, log_dir: str) -> None:
    required_dirs = {
        Path(database_path).expanduser().resolve().parent,
        Path("/opt/cte-time/data"),
        Path(log_dir).expanduser().resolve(),
    }
    for directory in required_dirs:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Could not create required directory: %s", directory)


def _configure_file_logging(log_dir: str) -> None:
    log_path = Path(log_dir).expanduser().resolve() / "cte-time.log"
    root_logger = logging.getLogger()

    for handler in root_logger.handlers:
        if isinstance(handler, TimedRotatingFileHandler) and Path(handler.baseFilename) == log_path:
            return

    try:
        file_handler = TimedRotatingFileHandler(
            filename=log_path,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Could not initialize file logging at: %s", log_path)
        return
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    _ensure_required_directories(settings.database_path, settings.log_dir)
    _configure_file_logging(settings.log_dir)
    await run_migrations(settings.database_path)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CTE Time", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

    static_dir = Path(__file__).resolve().parent / "shared" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(student_router)
    app.include_router(teacher_router)

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        database_status = "connected"
        try:
            async with aiosqlite.connect(settings.database_path) as connection:
                await connection.execute("SELECT 1")
        except Exception:
            database_status = "disconnected"

        return {
            "status": "ok",
            "version": settings.app_version,
            "database": database_status,
        }

    return app


app = create_app()
