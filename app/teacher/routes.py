import logging
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.shared.helpers import flash, get_csrf_token, pop_flash


router = APIRouter(prefix="/teacher", tags=["teacher"])
logger = logging.getLogger(__name__)
templates = Jinja2Templates(
    directory=[
        Path(__file__).resolve().parent / "templates",
        Path(__file__).resolve().parent.parent / "shared" / "templates",
    ]
)


def require_teacher(request: Request) -> bool:
    return request.session.get("teacher_id") is not None


def render_teacher_template(request: Request, name: str, context: dict[str, Any], active_page: str | None = None):
    base_context = {
        "flash": pop_flash(request),
        "teacher_name": request.session.get("teacher_name") or "Teacher",
        "csrf_token": get_csrf_token(request),
        "active_page": active_page,
    }
    base_context.update(context)
    return templates.TemplateResponse(request=request, name=name, context=base_context)


@router.get("/login")
async def teacher_login_page(request: Request):
    return render_teacher_template(request, "login.html", {}, active_page=None)


@router.get("/dashboard")
async def teacher_dashboard(request: Request):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    classes: list[dict[str, Any]] = []

    if teacher_id is not None and school_year_id is not None:
        settings = get_settings()
        try:
            async with aiosqlite.connect(settings.database_path) as connection:
                connection.row_factory = aiosqlite.Row
                async with connection.execute(
                    (
                        "SELECT c.id, c.name, COUNT(e.id) AS student_count "
                        "FROM classes c "
                        "LEFT JOIN enrollments e ON e.class_id = c.id "
                        "WHERE c.teacher_id = ? AND c.school_year_id = ? "
                        "GROUP BY c.id "
                        "ORDER BY c.name"
                    ),
                    (teacher_id, school_year_id),
                ) as cursor:
                    rows = await cursor.fetchall()
                    classes = [dict(row) for row in rows]
        except aiosqlite.Error:
            logger.exception("Failed to load teacher dashboard classes")
            flash(request, "Unable to load classes. Please try again.", "error")

    return render_teacher_template(request, "dashboard.html", {"classes": classes}, active_page="dashboard")
