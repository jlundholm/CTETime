from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.admin.routes import router as admin_router
from app.auth.routes import router as auth_router
from app.config import get_settings
from app.database import run_migrations
from app.student.routes import router as student_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
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

    return app


app = create_app()
