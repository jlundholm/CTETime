import logging
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.shared.helpers import flash, get_csrf_token, pop_flash, validate_csrf_token


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


async def _load_teacher_class(connection: aiosqlite.Connection, class_id: int, teacher_id: int) -> dict[str, Any] | None:
    async with connection.execute(
        "SELECT id, name, school_year_id FROM classes WHERE id = ? AND teacher_id = ?",
        (class_id, teacher_id),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


@router.post("/classes/create")
async def create_class(request: Request, name: str = Form(""), csrf_token: str = Form(...)):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url="/teacher/dashboard", status_code=303)

    class_name = name.strip()
    if not class_name:
        flash(request, "Class name is required.", "error")
        return RedirectResponse(url="/teacher/dashboard", status_code=303)
    if len(class_name) > 120:
        flash(request, "Class name must be 120 characters or fewer.", "error")
        return RedirectResponse(url="/teacher/dashboard", status_code=303)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            await connection.execute(
                "INSERT INTO classes (name, teacher_id, school_year_id) VALUES (?, ?, ?)",
                (class_name, teacher_id, school_year_id),
            )
            await connection.commit()
    except aiosqlite.Error:
        logger.exception("Failed to create class")
        flash(request, "Unable to create class. Please try again.", "error")
        return RedirectResponse(url="/teacher/dashboard", status_code=303)

    flash(request, "Class created.", "success")
    return RedirectResponse(url="/teacher/dashboard", status_code=303)


@router.get("/classes/{class_id}")
async def class_detail(request: Request, class_id: int):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            class_row = await _load_teacher_class(connection, class_id, teacher_id)
            if class_row is None:
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            async with connection.execute(
                (
                    "SELECT s.id, s.first_name, s.last_name, s.pin "
                    "FROM students s "
                    "JOIN enrollments e ON e.student_id = s.id "
                    "WHERE e.class_id = ? "
                    "ORDER BY s.last_name, s.first_name"
                ),
                (class_id,),
            ) as students_cursor:
                students_rows = await students_cursor.fetchall()

            async with connection.execute(
                (
                    "SELECT s.id, s.first_name, s.last_name, s.pin "
                    "FROM students s "
                    "WHERE s.school_year_id = ? "
                    "AND s.id NOT IN (SELECT student_id FROM enrollments WHERE class_id = ?) "
                    "ORDER BY s.last_name, s.first_name"
                ),
                (school_year_id, class_id),
            ) as available_cursor:
                available_rows = await available_cursor.fetchall()
    except aiosqlite.Error:
        logger.exception("Failed to load class detail")
        flash(request, "Unable to load class details. Please try again.", "error")
        return RedirectResponse(url="/teacher/dashboard", status_code=303)

    return render_teacher_template(
        request,
        "class.html",
        {
            "class_row": class_row,
            "students": [dict(row) for row in students_rows],
            "available_students": [dict(row) for row in available_rows],
        },
        active_page="dashboard",
    )


@router.post("/classes/{class_id}/rename")
async def rename_class(request: Request, class_id: int, name: str = Form(""), csrf_token: str = Form(...)):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    class_name = name.strip()
    if not class_name:
        flash(request, "Class name is required.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)
    if len(class_name) > 120:
        flash(request, "Class name must be 120 characters or fewer.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    teacher_id = request.session.get("teacher_id")
    if teacher_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            class_row = await _load_teacher_class(connection, class_id, teacher_id)
            if class_row is None:
                flash(request, "Class not found.", "error")
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            await connection.execute(
                "UPDATE classes SET name = ? WHERE id = ? AND teacher_id = ?",
                (class_name, class_id, teacher_id),
            )
            await connection.commit()
    except aiosqlite.Error:
        logger.exception("Failed to rename class")
        flash(request, "Unable to rename class. Please try again.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    flash(request, "Class renamed.", "success")
    return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)


@router.post("/classes/{class_id}/add-students")
async def add_students_to_class(
    request: Request,
    class_id: int,
    student_ids: list[int] = Form(default=[]),
    csrf_token: str = Form(...),
):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    if not student_ids:
        flash(request, "Select at least one student to add.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            class_row = await _load_teacher_class(connection, class_id, teacher_id)
            if class_row is None:
                flash(request, "Class not found.", "error")
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            normalized_ids = list(dict.fromkeys(student_ids))
            placeholders = ",".join("?" for _ in normalized_ids)
            query = (
                "SELECT id FROM students "
                "WHERE school_year_id = ? AND id IN (" + placeholders + ")"
            )
            params: list[Any] = [school_year_id, *normalized_ids]
            async with connection.execute(query, params) as cursor:
                valid_rows = await cursor.fetchall()
            valid_student_ids = [row["id"] for row in valid_rows]

            if not valid_student_ids:
                flash(request, "No valid students to add.", "error")
                return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

            for student_id in valid_student_ids:
                await connection.execute(
                    "INSERT OR IGNORE INTO enrollments (class_id, student_id) VALUES (?, ?)",
                    (class_id, student_id),
                )

            await connection.commit()
    except aiosqlite.Error:
        logger.exception("Failed to add students to class")
        flash(request, "Unable to add students. Please try again.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    flash(request, "Students added.", "success")
    return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)


@router.post("/classes/{class_id}/students/{student_id}/remove")
async def remove_student_from_class(request: Request, class_id: int, student_id: int, csrf_token: str = Form(...)):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            class_row = await _load_teacher_class(connection, class_id, teacher_id)
            if class_row is None:
                flash(request, "Class not found.", "error")
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            async with connection.execute(
                "SELECT id FROM students WHERE id = ? AND school_year_id = ?",
                (student_id, school_year_id),
            ) as student_cursor:
                student_row = await student_cursor.fetchone()

            if student_row is None:
                flash(request, "Student not found.", "error")
                return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

            delete_cursor = await connection.execute(
                "DELETE FROM enrollments WHERE class_id = ? AND student_id = ?",
                (class_id, student_id),
            )
            if delete_cursor.rowcount == 0:
                flash(request, "Student is not enrolled in this class.", "error")
                return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)
            await connection.commit()
    except aiosqlite.Error:
        logger.exception("Failed to remove student from class")
        flash(request, "Unable to remove student. Please try again.", "error")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    flash(request, "Student removed from class.", "success")
    return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)
