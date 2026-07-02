import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.student import destroy_student_session
from app.config import get_settings
from app.shared.helpers import ensure_utc, flash, get_display_timezone, parse_iso_datetime, pop_flash, utc_now


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/student", tags=["student"])
templates = Jinja2Templates(
    directory=[
        Path(__file__).resolve().parent / "templates",
        Path(__file__).resolve().parent.parent / "shared" / "templates",
    ]
)


def require_student(request: Request) -> bool:
    return request.session.get("student_id") is not None


def render_student_template(request: Request, name: str, context: dict[str, Any]):
    base_context = {
        "flash": pop_flash(request),
        "student_name": request.session.get("student_name") or "Student",
    }
    base_context.update(context)
    return templates.TemplateResponse(request=request, name=name, context=base_context)


def format_time(value: datetime) -> str:
    tz = get_display_timezone()
    return ensure_utc(value).astimezone(tz).strftime("%I:%M %p").lstrip("0")


def format_duration(clock_in_time: datetime, clock_out_time: datetime) -> str:
    cin = ensure_utc(clock_in_time)
    cout = ensure_utc(clock_out_time)
    delta = cout - cin
    total_seconds = max(int(delta.total_seconds()), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_duration_seconds(total_seconds: int) -> str:
    seconds = max(total_seconds, 0)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_log_date(value: date) -> str:
    return value.strftime("%a, %b %d").replace(" 0", " ")


async def get_active_school_year_id(connection: aiosqlite.Connection) -> int | None:
    async with connection.execute(
        "SELECT id FROM school_years WHERE status = 'active' ORDER BY id DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def validate_student_session(
    connection: aiosqlite.Connection,
    request: Request,
) -> tuple[int, int | None] | None:
    student_id = request.session.get("student_id")
    if student_id is None:
        return None

    active_school_year_id = await get_active_school_year_id(connection)
    if active_school_year_id is not None:
        async with connection.execute(
            "SELECT id FROM students WHERE id = ? AND school_year_id = ?",
            (student_id, active_school_year_id),
        ) as cursor:
            active_student = await cursor.fetchone()
        if not active_student:
            flash(request, "Your session has expired. Please sign in again.", "error")
            destroy_student_session(request.session)
            return None
    else:
        async with connection.execute("SELECT id FROM students WHERE id = ?", (student_id,)) as cursor:
            student_exists = await cursor.fetchone()
        if not student_exists:
            flash(request, "Your session has expired. Please sign in again.", "error")
            destroy_student_session(request.session)
            return None

    return int(student_id), active_school_year_id


async def get_open_punch(
    connection: aiosqlite.Connection,
    student_id: int,
    school_year_id: int,
) -> aiosqlite.Row | None:
    original_factory = connection.row_factory
    connection.row_factory = aiosqlite.Row
    try:
        async with connection.execute(
            (
                "SELECT id, clock_in_time FROM punches "
                "WHERE student_id = ? AND school_year_id = ? AND clock_out_time IS NULL "
                "ORDER BY id DESC LIMIT 1"
            ),
            (student_id, school_year_id),
        ) as cursor:
            return await cursor.fetchone()
    finally:
        connection.row_factory = original_factory


async def get_weekly_log(
    connection: aiosqlite.Connection,
    student_id: int,
    school_year_id: int | None = None,
) -> tuple[list[dict[str, str]], str]:
    now = utc_now()
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    query = (
        "SELECT p.clock_in_time, p.clock_out_time "
        "FROM punches p "
        "WHERE p.student_id = ? AND p.clock_in_time >= ? AND p.clock_in_time < ? "
    )
    params: list[Any] = [student_id, week_start.isoformat(), week_end.isoformat()]
    if school_year_id is not None:
        query += "AND p.school_year_id = ? "
        params.append(school_year_id)

    query += "ORDER BY p.clock_in_time DESC"

    original_factory = connection.row_factory
    connection.row_factory = aiosqlite.Row
    try:
        async with connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()
    finally:
        connection.row_factory = original_factory

    by_date: dict[date, dict[str, Any]] = {}
    for row in rows:
        clock_in = parse_iso_datetime(row["clock_in_time"])
        if clock_in is None:
            continue

        key = clock_in.date()
        bucket = by_date.get(key)
        if bucket is None:
            bucket = {
                "first_clock_in": clock_in,
                "latest_clock_out": None,
                "has_open": False,
                "daily_seconds": 0,
            }
            by_date[key] = bucket

        if clock_in < bucket["first_clock_in"]:
            bucket["first_clock_in"] = clock_in

        db_clock_out_value = row["clock_out_time"]
        clock_out = parse_iso_datetime(db_clock_out_value)
        if clock_out is None:
            if db_clock_out_value is not None:
                # Corrupt — not null but unparseable; skip the row
                continue
            bucket["has_open"] = True
            continue

        if clock_out >= clock_in:
            session_seconds = int((clock_out - clock_in).total_seconds())
            bucket["daily_seconds"] += session_seconds
            latest_clock_out = bucket["latest_clock_out"]
            if latest_clock_out is None or clock_out > latest_clock_out:
                bucket["latest_clock_out"] = clock_out

    weekly_log: list[dict[str, str]] = []
    week_total_seconds = 0
    for log_date in sorted(by_date.keys(), reverse=True):
        bucket = by_date[log_date]
        daily_seconds = bucket["daily_seconds"]
        week_total_seconds += daily_seconds

        latest_clock_out = bucket["latest_clock_out"]
        has_open = bucket["has_open"]
        clock_out_display = ""
        if not has_open and latest_clock_out is not None:
            clock_out_display = format_time(latest_clock_out)
        elif has_open and latest_clock_out is not None:
            clock_out_display = format_time(latest_clock_out) + " (open)"

        weekly_log.append(
            {
                "date": format_log_date(log_date),
                "clock_in": format_time(bucket["first_clock_in"]),
                "clock_out": clock_out_display,
                "daily_total": format_duration_seconds(daily_seconds) if daily_seconds > 0 else "",
            }
        )

    week_total = format_duration_seconds(week_total_seconds)
    return weekly_log, week_total


@router.get("/login")
async def student_login_page(request: Request):
    return render_student_template(
        request,
        "login.html",
        {
            "error_message": request.query_params.get("error", ""),
            "guidance_message": request.query_params.get("guidance", ""),
        },
    )


@router.get("/clock")
async def clock_screen(request: Request):
    if not require_student(request):
        return RedirectResponse(url="/student/login", status_code=303)

    settings = get_settings()
    in_session = False
    weekly_log: list[dict[str, str]] = []
    week_total = "0m"

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            validated = await validate_student_session(connection, request)
            if validated is None:
                return RedirectResponse(url="/student/login", status_code=303)

            student_id, school_year_id = validated
            if school_year_id is not None:
                open_punch = await get_open_punch(connection, student_id, school_year_id)
                in_session = open_punch is not None
                weekly_log, week_total = await get_weekly_log(connection, student_id, school_year_id)
    except Exception:
        logger.exception("Failed to load clock screen data")
        in_session = False

    return render_student_template(
        request,
        "clock.html",
        {
            "in_session": in_session,
            "current_time": format_time(utc_now()),
            "weekly_log": weekly_log,
            "week_total": week_total,
        },
    )


@router.get("/clock/log")
async def clock_log(request: Request):
    if not require_student(request):
        return JSONResponse({"success": False, "error": "unauthorized"}, status_code=401)

    settings = get_settings()
    weekly_log: list[dict[str, str]] = []
    week_total = "0m"

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            validated = await validate_student_session(connection, request)
            if validated is None:
                return JSONResponse({"success": False, "error": "unauthorized"}, status_code=401)

            student_id, school_year_id = validated
            if school_year_id is None:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "no_active_school_year",
                        "message": "No active school year.",
                    },
                    status_code=400,
                )
            weekly_log, week_total = await get_weekly_log(connection, student_id, school_year_id)
    except Exception:
        logger.exception("Failed to load weekly log partial")
        weekly_log = []
        week_total = "0m"

    return templates.TemplateResponse(
        request=request,
        name="partials/weekly_log.html",
        context={"weekly_log": weekly_log, "week_total": week_total},
    )


@router.post("/clock-in")
async def clock_in(request: Request):
    if not require_student(request):
        return JSONResponse(
            {"success": False, "error": "unauthorized", "message": "Please sign in."},
            status_code=401,
        )

    settings = get_settings()
    now = utc_now()

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            validated = await validate_student_session(connection, request)
            if validated is None:
                return JSONResponse(
                    {"success": False, "error": "unauthorized", "message": "Please sign in."},
                    status_code=401,
                )

            student_id, school_year_id = validated
            if school_year_id is None:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "no_active_year",
                        "message": "Couldn't record punch. Try again.",
                    },
                    status_code=400,
                )

            existing = await get_open_punch(connection, student_id, school_year_id)
            if existing:
                try:
                    clocked_in_time = datetime.fromisoformat(existing["clock_in_time"])
                except (ValueError, TypeError):
                    clocked_in_time = now
                return JSONResponse(
                    {
                        "success": False,
                        "error": "already_clocked_in",
                        "time": format_time(clocked_in_time),
                        "message": f"Already clocked in at {format_time(clocked_in_time)}.",
                    },
                    status_code=200,
                )

            try:
                await connection.execute(
                    "INSERT INTO punches (student_id, clock_in_time, school_year_id) VALUES (?, ?, ?)",
                    (student_id, now.isoformat(), school_year_id),
                )
            except aiosqlite.IntegrityError:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "already_clocked_in",
                        "time": format_time(now),
                        "message": f"Already clocked in at {format_time(now)}.",
                    },
                    status_code=200,
                )
            await connection.commit()

        return JSONResponse(
            {
                "success": True,
                "action": "clock_in",
                "time": format_time(now),
                "message": f"Clocked in at {format_time(now)}",
            }
        )
    except Exception:
        logger.exception("Clock-in failed unexpectedly")
        return JSONResponse(
            {"success": False, "error": "server_error", "message": "Couldn't record punch. Try again."},
            status_code=500,
        )


@router.post("/clock-out")
async def clock_out(request: Request):
    if not require_student(request):
        return JSONResponse(
            {"success": False, "error": "unauthorized", "message": "Please sign in."},
            status_code=401,
        )

    settings = get_settings()
    now = utc_now()

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            validated = await validate_student_session(connection, request)
            if validated is None:
                return JSONResponse(
                    {"success": False, "error": "unauthorized", "message": "Please sign in."},
                    status_code=401,
                )

            student_id, school_year_id = validated
            if school_year_id is None:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "no_active_year",
                        "message": "Couldn't record punch. Try again.",
                    },
                    status_code=400,
                )

            existing = await get_open_punch(connection, student_id, school_year_id)
            if not existing:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "not_clocked_in",
                        "message": "Not clocked in.",
                    },
                    status_code=200,
                )

            try:
                clock_in_dt = datetime.fromisoformat(existing["clock_in_time"])
            except (ValueError, TypeError):
                clock_in_dt = now

            cursor = await connection.execute(
                "UPDATE punches SET clock_out_time = ? WHERE id = ? AND clock_out_time IS NULL",
                (now.isoformat(), existing["id"]),
            )
            await connection.commit()

            if cursor.rowcount == 0:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "not_clocked_in",
                        "message": "Not clocked in.",
                    },
                    status_code=200,
                )

        return JSONResponse(
            {
                "success": True,
                "action": "clock_out",
                "time": format_time(now),
                "duration": format_duration(clock_in_dt, now),
                "message": f"Clocked out \u2014 {format_duration(clock_in_dt, now)} session",
            }
        )
    except Exception:
        logger.exception("Clock-out failed unexpectedly")
        return JSONResponse(
            {"success": False, "error": "server_error", "message": "Couldn't record punch. Try again."},
            status_code=500,
        )
