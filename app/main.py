import logging
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import aiosqlite
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.admin.routes import router as admin_router
from app.auth.routes import router as auth_router
from app.auth.staff import hash_password
from app.config import get_settings
from app.database import run_migrations
from app.shared.rate_limit import InMemoryRateLimiter
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


async def _seed_admin(database_path: str, email: str, password: str) -> None:
    email = email.strip()
    password = password.strip()

    if not email and not password:
        logger.info("ADMIN_EMAIL and ADMIN_PASSWORD not set; skipping admin bootstrap")
        return

    if not email or not password:
        logger.warning("ADMIN_EMAIL and ADMIN_PASSWORD must both be set; skipping bootstrap")
        return

    async with aiosqlite.connect(database_path) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM admins")
        row = await cursor.fetchone()
        if row[0] > 0:
            logger.info("Admin already exists; skipping bootstrap")
            return

        try:
            password_hash = hash_password(password)
        except Exception:
            logger.error("Failed to hash admin password; skipping bootstrap")
            return

        await conn.execute(
            "INSERT INTO admins (email, first_name, last_name, password_hash) VALUES (?, ?, ?, ?)",
            (email, "System", "Admin", password_hash),
        )
        await conn.commit()
        logger.info("Admin bootstrap complete: %s", email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    _ensure_required_directories(settings.database_path, settings.log_dir)
    _configure_file_logging(settings.log_dir)
    await run_migrations(settings.database_path)
    await _seed_admin(settings.database_path, settings.admin_email, settings.admin_password)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CTE Time", lifespan=lifespan)
    rate_limiter = InMemoryRateLimiter(
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    export_rate_limiter = InMemoryRateLimiter(
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    app.state.rate_limiter = rate_limiter
    app.state.export_rate_limiter = export_rate_limiter

    @app.middleware("http")
    async def rate_limit_posts(request: Request, call_next):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        retry_after = rate_limiter.check(client_ip)
        if retry_after is not None:
            return JSONResponse(
                {"success": False, "error": "rate_limited", "message": "Too many requests."},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=settings.session_max_age,
        https_only=settings.is_production,
        same_site=settings.session_same_site,
    )

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
