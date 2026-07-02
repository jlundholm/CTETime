import logging
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.shared.helpers import (
    ensure_utc,
    flash,
    get_csrf_token,
    get_display_timezone,
    get_week_start,
    pop_flash,
    validate_csrf_token,
)


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


def format_seconds(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    total_seconds = max(int(seconds), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_timestamp(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return ""
    tz = get_display_timezone()
    return parsed.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%I:%M %p").lstrip("0")


def _normalize_date(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        datetime.fromisoformat(stripped)
    except ValueError:
        return None
    return stripped[:10]


def _week_start_for(date_value: datetime) -> datetime:
    return get_week_start(date_value)


def _check_export_rate_limit(request: Request) -> JSONResponse | None:
    rate_limiter = request.app.state.export_rate_limiter
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
    return None


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
async def class_detail(
    request: Request,
    class_id: int,
    sort: str = Query("name"),
    order: str = Query("asc"),
):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    settings = get_settings()
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date().isoformat()
    week_start = _week_start_for(now_utc).date().isoformat()

    sort_map = {
        "name": "name",
        "today": "today_punch",
        "week": "week_seconds",
        "pin": "s.pin",
    }
    sort_column = sort_map.get(sort, sort_map["name"])
    sort_key = sort if sort in sort_map else "name"
    order_dir = "ASC" if order == "asc" else "DESC"
    order_key = "asc" if order == "asc" else "desc"
    order_clause = (
        f"s.last_name {order_dir}, s.first_name {order_dir}"
        if sort_column == "name"
        else f"{sort_column} {order_dir}, s.last_name ASC, s.first_name ASC"
    )

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            class_row = await _load_teacher_class(connection, class_id, teacher_id)
            if class_row is None:
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            async with connection.execute(
                (
                    "SELECT s.id, s.first_name, s.last_name, s.pin, "
                    "       COALESCE(t.today_punch, '') AS today_punch, "
                    "       COALESCE(t.has_open, 0) AS has_open, "
                    "       COALESCE(w.week_seconds, 0) AS week_seconds "
                    "FROM students s "
                    "JOIN enrollments e ON e.student_id = s.id "
                    "LEFT JOIN ("
                    "    SELECT student_id, MAX(clock_in_time) AS today_punch, "
                    "           MAX(CASE WHEN clock_out_time IS NULL THEN 1 ELSE 0 END) AS has_open "
                    "    FROM punches "
                    "    WHERE date(clock_in_time) = ? AND school_year_id = ? "
                    "    GROUP BY student_id"
                    ") t ON t.student_id = s.id "
                    "LEFT JOIN ("
                    "    SELECT student_id, "
                    "           SUM(CASE WHEN clock_out_time IS NOT NULL "
                    "                    THEN (julianday(clock_out_time) - julianday(clock_in_time)) * 86400 "
                    "                    ELSE 0 END) AS week_seconds "
                    "    FROM punches "
                    "    WHERE date(clock_in_time) >= ? AND date(clock_in_time) <= ? AND school_year_id = ? "
                    "    GROUP BY student_id"
                    ") w ON w.student_id = s.id "
                    "WHERE e.class_id = ? "
                    f"ORDER BY {order_clause}"
                ),
                (today, school_year_id, week_start, today, school_year_id, class_id),
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
            "students": [
                {
                    **dict(row),
                    "today_status": "Clocked in" if row["has_open"] else format_timestamp(row["today_punch"]),
                    "week_total": format_seconds(row["week_seconds"]),
                }
                for row in students_rows
            ],
            "available_students": [dict(row) for row in available_rows],
            "sort": sort_key,
            "order": order_key,
        },
        active_page="dashboard",
    )


@router.get("/classes/{class_id}/students/{student_id}/punches")
async def student_punches_partial(request: Request, class_id: int, student_id: int):
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
                    "WHERE s.id = ? AND e.class_id = ?"
                ),
                (student_id, class_id),
            ) as student_cursor:
                student_row = await student_cursor.fetchone()

            if student_row is None:
                return templates.TemplateResponse(
                    request=request,
                    name="partials/student_punches.html",
                    context={
                        "student": None,
                        "punches": [],
                        "format_timestamp": format_timestamp,
                        "format_seconds": format_seconds,
                    },
                )

            async with connection.execute(
                (
                    "SELECT p.clock_in_time, p.clock_out_time, p.manual, "
                    "       CASE WHEN p.clock_out_time IS NOT NULL "
                    "            THEN (julianday(p.clock_out_time) - julianday(p.clock_in_time)) * 86400 "
                    "            ELSE NULL END AS duration_seconds "
                    "FROM punches p "
                    "WHERE p.student_id = ? AND p.school_year_id = ? "
                    "ORDER BY p.clock_in_time DESC"
                ),
                (student_id, school_year_id),
            ) as punches_cursor:
                punches_rows = await punches_cursor.fetchall()
    except Exception:
        logger.exception("Failed to load student punches partial")
        return templates.TemplateResponse(
            request=request,
            name="partials/student_punches.html",
            context={
                "student": None,
                "punches": [],
                "format_timestamp": format_timestamp,
                "format_seconds": format_seconds,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/student_punches.html",
        context={
            "student": dict(student_row),
            "punches": [dict(row) for row in punches_rows],
            "format_timestamp": format_timestamp,
            "format_seconds": format_seconds,
        },
    )


@router.get("/students/{student_id}")
async def student_detail(
    request: Request,
    student_id: int,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    normalized_from = _normalize_date(from_date)
    normalized_to = _normalize_date(to_date)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                (
                    "SELECT DISTINCT s.id, s.first_name, s.last_name, s.pin "
                    "FROM students s "
                    "JOIN enrollments e ON e.student_id = s.id "
                    "JOIN classes c ON c.id = e.class_id "
                    "WHERE s.id = ? AND s.school_year_id = ? AND c.teacher_id = ?"
                ),
                (student_id, school_year_id, teacher_id),
            ) as student_cursor:
                student_row = await student_cursor.fetchone()

            if student_row is None:
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            query = (
                "SELECT p.clock_in_time, p.clock_out_time, p.manual, "
                "       CASE WHEN p.clock_out_time IS NOT NULL "
                "            THEN (julianday(p.clock_out_time) - julianday(p.clock_in_time)) * 86400 "
                "            ELSE NULL END AS duration_seconds "
                "FROM punches p "
                "WHERE p.student_id = ? AND p.school_year_id = ?"
            )
            params: list[Any] = [student_id, school_year_id]

            if normalized_from:
                query += " AND date(p.clock_in_time) >= ?"
                params.append(normalized_from)
            if normalized_to:
                query += " AND date(p.clock_in_time) <= ?"
                params.append(normalized_to)

            query += " ORDER BY p.clock_in_time DESC"

            async with connection.execute(query, params) as punches_cursor:
                punches_rows = await punches_cursor.fetchall()
    except Exception:
        logger.exception("Failed to load student detail")
        flash(request, "Unable to load student detail. Please try again.", "error")
        return RedirectResponse(url="/teacher/dashboard", status_code=303)

    return render_teacher_template(
        request,
        "student.html",
        {
            "student": dict(student_row),
            "punches": [dict(row) for row in punches_rows],
            "from_date": normalized_from or "",
            "to_date": normalized_to or "",
            "format_timestamp": format_timestamp,
            "format_seconds": format_seconds,
        },
        active_page="dashboard",
    )


@router.get("/classes/{class_id}/export")
async def export_class_csv(
    request: Request,
    class_id: int,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    rate_check = _check_export_rate_limit(request)
    if rate_check is not None:
        return rate_check

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    normalized_from = _normalize_date(from_date)
    normalized_to = _normalize_date(to_date)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            class_row = await _load_teacher_class(connection, class_id, teacher_id)
            if class_row is None:
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            query = (
                "SELECT s.first_name, s.last_name, p.clock_in_time, p.clock_out_time, p.manual "
                "FROM punches p "
                "JOIN enrollments e ON p.student_id = e.student_id AND e.class_id = ? "
                "JOIN students s ON s.id = p.student_id "
                "WHERE p.school_year_id = ?"
            )
            params: list[Any] = [class_id, school_year_id]

            if normalized_from:
                query += " AND date(p.clock_in_time) >= ?"
                params.append(normalized_from)
            if normalized_to:
                query += " AND date(p.clock_in_time) <= ?"
                params.append(normalized_to)

            query += " ORDER BY s.last_name, s.first_name, p.clock_in_time"

            async with connection.execute(query, params) as rows_cursor:
                rows = await rows_cursor.fetchall()
    except Exception:
        logger.exception("Failed to export class CSV")
        return RedirectResponse(url=f"/teacher/classes/{class_id}", status_code=303)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["First Name", "Last Name", "Clock In", "Clock Out", "Manual"])
    for row in rows:
        writer.writerow(
            [
                row["first_name"],
                row["last_name"],
                row["clock_in_time"],
                row["clock_out_time"] or "",
                "Yes" if row["manual"] else "No",
            ]
        )

    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="class-{class_id}-punches.csv"'
    return response


@router.get("/students/{student_id}/export")
async def export_student_csv(
    request: Request,
    student_id: int,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
):
    if not require_teacher(request):
        return RedirectResponse(url="/teacher/login", status_code=303)

    rate_check = _check_export_rate_limit(request)
    if rate_check is not None:
        return rate_check

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return RedirectResponse(url="/teacher/login", status_code=303)

    normalized_from = _normalize_date(from_date)
    normalized_to = _normalize_date(to_date)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                (
                    "SELECT s.first_name, s.last_name "
                    "FROM students s "
                    "JOIN enrollments e ON e.student_id = s.id "
                    "JOIN classes c ON c.id = e.class_id "
                    "WHERE s.id = ? AND s.school_year_id = ? AND c.teacher_id = ?"
                ),
                (student_id, school_year_id, teacher_id),
            ) as student_cursor:
                student_row = await student_cursor.fetchone()

            if student_row is None:
                return RedirectResponse(url="/teacher/dashboard", status_code=303)

            query = (
                "SELECT p.clock_in_time, p.clock_out_time, p.manual "
                "FROM punches p "
                "WHERE p.student_id = ? AND p.school_year_id = ?"
            )
            params: list[Any] = [student_id, school_year_id]

            if normalized_from:
                query += " AND date(p.clock_in_time) >= ?"
                params.append(normalized_from)
            if normalized_to:
                query += " AND date(p.clock_in_time) <= ?"
                params.append(normalized_to)

            query += " ORDER BY p.clock_in_time"

            async with connection.execute(query, params) as rows_cursor:
                rows = await rows_cursor.fetchall()
    except Exception:
        logger.exception("Failed to export student CSV")
        return RedirectResponse(url=f"/teacher/students/{student_id}", status_code=303)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["First Name", "Last Name", "Clock In", "Clock Out", "Manual"])
    for row in rows:
        writer.writerow(
            [
                student_row["first_name"],
                student_row["last_name"],
                row["clock_in_time"],
                row["clock_out_time"] or "",
                "Yes" if row["manual"] else "No",
            ]
        )

    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="student-{student_id}-punches.csv"'
    return response


@router.post("/students/{student_id}/manual-punch")
async def manual_punch(
    request: Request,
    student_id: int,
    punch_type: str = Form(...),
    timestamp: str = Form(...),
    csrf_token: str = Form(...),
):
    if not require_teacher(request):
        return JSONResponse({"success": False, "error": "unauthorized"}, status_code=401)

    teacher_id = request.session.get("teacher_id")
    school_year_id = request.session.get("school_year_id")
    if teacher_id is None or school_year_id is None:
        return JSONResponse({"success": False, "error": "unauthorized"}, status_code=401)

    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        return JSONResponse({"success": False, "error": "Invalid form submission."}, status_code=403)

    if punch_type not in {"clock_in", "clock_out"}:
        return JSONResponse({"success": False, "error": "Invalid punch type."}, status_code=400)

    try:
        parsed_timestamp = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return JSONResponse({"success": False, "error": "Invalid timestamp format."}, status_code=400)

    if parsed_timestamp.tzinfo is None:
        tz = get_display_timezone()
        local_dt = parsed_timestamp.replace(tzinfo=tz)
    else:
        local_dt = parsed_timestamp
    punch_timestamp = local_dt.astimezone(timezone.utc)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                (
                    "SELECT DISTINCT s.id "
                    "FROM students s "
                    "JOIN enrollments e ON e.student_id = s.id "
                    "JOIN classes c ON c.id = e.class_id "
                    "WHERE s.id = ? AND s.school_year_id = ? AND c.teacher_id = ?"
                ),
                (student_id, school_year_id, teacher_id),
            ) as student_cursor:
                student_row = await student_cursor.fetchone()

            if student_row is None:
                return JSONResponse({"success": False, "error": "Student not found."}, status_code=404)

            async with connection.execute(
                (
                    "SELECT id, clock_in_time FROM punches "
                    "WHERE student_id = ? AND school_year_id = ? AND clock_out_time IS NULL "
                    "ORDER BY clock_in_time DESC LIMIT 1"
                ),
                (student_id, school_year_id),
            ) as open_cursor:
                open_punch = await open_cursor.fetchone()

            if punch_type == "clock_in":
                if open_punch:
                    return JSONResponse(
                        {
                            "success": False,
                            "error": f"Student is already clocked in since {open_punch['clock_in_time']}.",
                        }
                    )

                try:
                    await connection.execute(
                        "INSERT INTO punches (student_id, clock_in_time, manual, school_year_id) VALUES (?, ?, 1, ?)",
                        (student_id, punch_timestamp.isoformat(), school_year_id),
                    )
                except aiosqlite.IntegrityError:
                    return JSONResponse(
                        {"success": False, "error": "Student is already clocked in."}
                    )
            else:
                if not open_punch:
                    return JSONResponse({"success": False, "error": "Student is not clocked in."})

                try:
                    clock_in_dt = datetime.fromisoformat(open_punch["clock_in_time"])
                except (TypeError, ValueError):
                    clock_in_dt = None
                if clock_in_dt is not None and punch_timestamp < ensure_utc(clock_in_dt):
                    return JSONResponse(
                        {"success": False, "error": "Clock-out time must be after clock-in time."}
                    )

                update_cursor = await connection.execute(
                    "UPDATE punches SET clock_out_time = ?, manual = 1 WHERE id = ? AND clock_out_time IS NULL",
                    (punch_timestamp.isoformat(), open_punch["id"]),
                )
                if update_cursor.rowcount == 0:
                    return JSONResponse({"success": False, "error": "Student is not clocked in."})

            await connection.commit()
    except Exception:
        logger.exception("Failed to record manual punch")
        return JSONResponse({"success": False, "error": "Couldn't record punch. Try again."}, status_code=500)

    return JSONResponse({"success": True})


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
