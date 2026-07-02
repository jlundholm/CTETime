import logging
from pathlib import Path
from sqlite3 import IntegrityError
from typing import Any

logger = logging.getLogger(__name__)

import aiosqlite
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.auth.staff import hash_password
from app.config import get_settings
from app.shared.helpers import (
    flash,
    generate_pin,
    get_csrf_token,
    parse_csv,
    pop_flash,
    required_columns_for_rows,
    validate_csrf_token,
    validate_import_rows,
)
from app.shared.models import ImportPreview, SchoolYearCreate, UserCreate, UserRole


router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(
    directory=[
        Path(__file__).resolve().parent / "templates",
        Path(__file__).resolve().parent.parent / "shared" / "templates",
    ]
)


def require_admin(request: Request) -> RedirectResponse | None:
    if "admin_id" not in request.session:
        return RedirectResponse(url="/admin/login", status_code=303)
    return None


def render_template(request: Request, name: str, context: dict[str, Any]):
    base_context = {
        "flash": pop_flash(request),
        "admin_name": request.session.get("admin_name") or "Administrator",
        "csrf_token": get_csrf_token(request),
    }
    base_context.update(context)
    return templates.TemplateResponse(request=request, name=name, context=base_context)


async def list_school_years(database_path: str) -> list[dict[str, Any]]:
    try:
        async with aiosqlite.connect(database_path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT id, name, start_date, end_date, status FROM school_years ORDER BY start_date DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except aiosqlite.Error:
        return []


async def get_school_year(database_path: str, year_id: int) -> dict[str, Any] | None:
    try:
        async with aiosqlite.connect(database_path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT id, name, start_date, end_date, status FROM school_years WHERE id = ?",
                (year_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    except aiosqlite.Error:
        return None


async def get_existing_student_pins(database_path: str, year_id: int) -> set[str]:
    try:
        async with aiosqlite.connect(database_path) as connection:
            async with connection.execute(
                "SELECT pin FROM students WHERE school_year_id = ?",
                (year_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return {row[0] for row in rows}
    except aiosqlite.Error:
        return set()


async def list_teachers(database_path: str, year_id: int) -> list[dict[str, Any]]:
    try:
        async with aiosqlite.connect(database_path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                (
                    "SELECT id, first_name, last_name, email, is_active "
                    "FROM teachers WHERE school_year_id = ? "
                    "ORDER BY last_name, first_name"
                ),
                (year_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except aiosqlite.Error:
        logger.exception("Failed to list teachers for year %s", year_id)
        return []


@router.get("/login")
async def admin_login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "flash": pop_flash(request),
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/dashboard")
async def admin_dashboard(request: Request):
    redirect = require_admin(request)
    if redirect:
        return redirect

    settings = get_settings()
    school_years = await list_school_years(settings.database_path)

    return render_template(
        request,
        "dashboard.html",
        {
            "school_years": school_years,
        },
    )


@router.get("/years/create")
async def create_school_year_form(request: Request):
    redirect = require_admin(request)
    if redirect:
        return redirect

    return render_template(
        request,
        "year.html",
        {
            "mode": "create",
            "values": {"name": "", "start_date": "", "end_date": ""},
            "errors": {},
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/years/create")
async def create_school_year(
    request: Request,
    name: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    csrf_token: str = Form(...),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url="/admin/login", status_code=303)

    values = {"name": name, "start_date": start_date, "end_date": end_date}

    try:
        payload = SchoolYearCreate.model_validate(values)
    except ValidationError as exc:
        errors = {"form": "Please correct the highlighted errors."}
        for error in exc.errors():
            loc = error.get("loc", ())
            msg = error["msg"]
            if "name" in loc:
                errors["name"] = msg
            else:
                errors["dates"] = msg
        return render_template(
            request,
            "year.html",
            {
                "mode": "create",
                "values": values,
                "errors": errors,
            },
        )

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            cursor = await connection.execute(
                (
                    "INSERT INTO school_years (name, start_date, end_date, status) "
                    "VALUES (?, ?, ?, 'active')"
                ),
                (
                    payload.name.strip(),
                    payload.start_date.isoformat(),
                    payload.end_date.isoformat(),
                ),
            )
            await connection.commit()
            year_id = cursor.lastrowid
            if year_id is None:
                return render_template(
                    request,
                    "year.html",
                    {
                        "mode": "create",
                        "values": values,
                        "errors": {"form": "Failed to create school year."},
                    },
                )
    except IntegrityError:
        return render_template(
            request,
            "year.html",
            {
                "mode": "create",
                "values": values,
                "errors": {"form": "Failed to create school year."},
            },
        )
    except aiosqlite.Error:
        return render_template(
            request,
            "year.html",
            {
                "mode": "create",
                "values": values,
                "errors": {"form": "A database error occurred."},
            },
        )

    flash(request, "School year created.", "success")
    return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)


@router.get("/years/{year_id}")
async def school_year_detail(request: Request, year_id: int):
    redirect = require_admin(request)
    if redirect:
        return redirect

    settings = get_settings()
    year = await get_school_year(settings.database_path, year_id)
    teachers = await list_teachers(settings.database_path, year_id)
    if not year:
        return RedirectResponse(url="/admin/dashboard", status_code=303)

    return render_template(
        request,
        "year.html",
        {
            "mode": "detail",
            "year": year,
            "teachers": teachers,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/years/{year_id}/users/create")
async def create_user_form(request: Request, year_id: int):
    redirect = require_admin(request)
    if redirect:
        return redirect

    settings = get_settings()
    year = await get_school_year(settings.database_path, year_id)
    if not year:
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    if year["status"] != "active":
        flash(request, "Only active school years can accept new users.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    existing_pins = await get_existing_student_pins(settings.database_path, year_id)
    generated_pin = generate_pin(existing_pins)
    values = {
        "role": UserRole.student.value,
        "first_name": "",
        "last_name": "",
        "email": "",
        "pin": generated_pin,
        "password": "",
    }
    return render_template(
        request,
        "user_create.html",
        {
            "year": year,
            "values": values,
            "errors": {},
        },
    )


@router.post("/years/{year_id}/users/create")
async def create_user(
    request: Request,
    year_id: int,
    role: str = Form(UserRole.student.value),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    pin: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(...),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url="/admin/login", status_code=303)

    settings = get_settings()
    year = await get_school_year(settings.database_path, year_id)
    if not year:
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    if year["status"] != "active":
        flash(request, "Only active school years can accept new users.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    normalized_role = role.strip().lower()
    values = {
        "role": normalized_role,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "pin": pin,
        "password": password,
    }
    errors: dict[str, str] = {}

    if normalized_role not in {UserRole.student.value, UserRole.teacher.value}:
        errors["role"] = "Select a valid role."

    try:
        payload = UserCreate.model_validate(
            {
                "role": normalized_role,
                "first_name": first_name.strip(),
                "last_name": last_name.strip(),
                "email": email.strip() or None,
                "pin": pin.strip() or None,
                "password": password if password else None,
            }
        )
    except ValidationError as exc:
        errors["form"] = "Please correct the highlighted errors."
        for error in exc.errors():
            loc = error.get("loc", ())
            msg = error["msg"]
            if "first_name" in loc:
                errors["first_name"] = msg
            elif "last_name" in loc:
                errors["last_name"] = msg
            elif "email" in loc:
                errors["email"] = msg
            elif "pin" in loc:
                errors["pin"] = msg
            elif "password" in loc:
                errors["password"] = msg
            elif "role" in loc:
                errors["role"] = msg
            else:
                errors["form"] = msg

        return render_template(
            request,
            "user_create.html",
            {
                "year": year,
                "values": values,
                "errors": errors,
            },
        )

    if payload.role == UserRole.student:
        entered_pin = payload.pin or ""
        if not entered_pin:
            errors["pin"] = "PIN is required for students."
        else:
            async with aiosqlite.connect(settings.database_path) as connection:
                async with connection.execute(
                    "SELECT pin FROM students WHERE pin = ? AND school_year_id = ?",
                    (entered_pin, year_id),
                ) as cursor:
                    existing = await cursor.fetchone()
                if existing:
                    errors["pin"] = "PIN must be unique."

        if errors:
            errors.setdefault("form", "Please correct the highlighted errors.")
            return render_template(
                request,
                "user_create.html",
                {
                    "year": year,
                    "values": values,
                    "errors": errors,
                },
            )

        try:
            async with aiosqlite.connect(settings.database_path) as connection:
                await connection.execute(
                    (
                        "INSERT INTO students (first_name, last_name, email, pin, school_year_id) "
                        "VALUES (?, ?, ?, ?, ?)"
                    ),
                    (
                        payload.first_name,
                        payload.last_name,
                        payload.email,
                        entered_pin,
                        year_id,
                    ),
                )
                await connection.commit()
        except IntegrityError:
            errors["pin"] = "PIN must be unique."
            errors["form"] = "Please correct the highlighted errors."
            return render_template(
                request,
                "user_create.html",
                {
                    "year": year,
                    "values": values,
                    "errors": errors,
                },
            )
        except aiosqlite.Error:
            errors["form"] = "A database error occurred."
            return render_template(
                request,
                "user_create.html",
                {
                    "year": year,
                    "values": values,
                    "errors": errors,
                },
            )

        flash(request, "Student created.", "success")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            await connection.execute(
                (
                    "INSERT INTO teachers "
                    "(first_name, last_name, email, password_hash, is_active, school_year_id) "
                    "VALUES (?, ?, ?, ?, 1, ?)"
                ),
                (
                    payload.first_name,
                    payload.last_name,
                    payload.email,
                    hash_password(payload.password or ""),
                    year_id,
                ),
            )
            await connection.commit()
    except aiosqlite.Error:
        errors["form"] = "A database error occurred."
        return render_template(
            request,
            "user_create.html",
            {
                "year": year,
                "values": values,
                "errors": errors,
            },
        )

    flash(request, "Teacher created.", "success")
    return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)


@router.post("/years/{year_id}/teachers/{teacher_id}/deactivate")
async def deactivate_teacher(request: Request, year_id: int, teacher_id: int, csrf_token: str = Form(...)):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url="/admin/login", status_code=303)

    settings = get_settings()
    year = await get_school_year(settings.database_path, year_id)
    if not year:
        flash(request, "School year not found.", "error")
        return RedirectResponse(url="/admin/dashboard", status_code=303)

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT is_active FROM teachers WHERE id = ? AND school_year_id = ?",
                (teacher_id, year_id),
            ) as cursor:
                teacher = await cursor.fetchone()

            if not teacher:
                flash(request, "Teacher not found.", "error")
                return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

            if not teacher["is_active"]:
                flash(request, "Teacher is already deactivated.", "error")
                return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

            await connection.execute(
                "UPDATE teachers SET is_active = 0 WHERE id = ? AND school_year_id = ?",
                (teacher_id, year_id),
            )
            await connection.commit()
    except aiosqlite.Error:
        flash(request, "A database error occurred.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    flash(request, "Teacher deactivated.", "success")
    return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)


@router.get("/years/{year_id}/import")
async def import_users_form(request: Request, year_id: int):
    redirect = require_admin(request)
    if redirect:
        return redirect

    settings = get_settings()
    year = await get_school_year(settings.database_path, year_id)
    if not year:
        return RedirectResponse(url="/admin/dashboard", status_code=303)

    preview = None
    preview_data = request.session.get("import_preview")
    if preview_data:
        try:
            preview = ImportPreview.model_validate(preview_data)
        except ValidationError:
            preview = None
            request.session.pop("import_preview", None)

    return render_template(
        request,
        "import.html",
        {
            "year": year,
            "preview": preview,
            "missing_columns": request.session.pop("import_missing_columns", []),
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/years/{year_id}/import")
async def import_users_upload(
    request: Request,
    year_id: int,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=303)

    settings = get_settings()
    year = await get_school_year(settings.database_path, year_id)
    if not year:
        return RedirectResponse(url="/admin/dashboard", status_code=303)

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        flash(request, "File is too large. Maximum size is 10 MB.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}/import", status_code=303)

    try:
        rows, fieldnames = parse_csv(content)
    except HTTPException:
        flash(request, "File must be UTF-8 encoded.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}/import", status_code=303)

    missing_columns = required_columns_for_rows(rows, fieldnames)

    if missing_columns:
        request.session.pop("import_preview", None)
        request.session["import_missing_columns"] = missing_columns
        flash(request, f"Missing required column(s): {', '.join(missing_columns)}", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}/import", status_code=303)

    existing_pins = await get_existing_student_pins(settings.database_path, year_id)
    preview = validate_import_rows(rows, existing_pins)
    truncated = preview.model_dump(mode="json")
    if len(truncated.get("rows", [])) > 100:
        truncated["rows"] = truncated["rows"][:100]
    request.session["import_preview"] = truncated
    request.session["import_year_id"] = year_id

    return render_template(
        request,
        "import.html",
        {
            "year": year,
            "preview": preview,
            "missing_columns": [],
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/years/{year_id}/import/confirm")
async def import_users_confirm(
    request: Request,
    year_id: int,
    csrf_token: str = Form(...),
    skip_invalid: str | None = Form(None),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=303)

    preview_data = request.session.get("import_preview")
    preview_year_id = request.session.get("import_year_id")
    if not preview_data or preview_year_id != year_id:
        flash(request, "No import preview found.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}/import", status_code=303)

    try:
        preview = ImportPreview.model_validate(preview_data)
    except ValidationError:
        flash(request, "Import preview data is corrupted. Please upload again.", "error")
        request.session.pop("import_preview", None)
        request.session.pop("import_year_id", None)
        return RedirectResponse(url=f"/admin/years/{year_id}/import", status_code=303)
    should_skip_invalid = skip_invalid is not None
    if preview.error_count > 0 and not should_skip_invalid:
        flash(request, "Resolve validation errors or enable skip invalid rows.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}/import", status_code=303)

    student_created = 0
    teacher_created = 0
    duplicates_skipped = 0
    errors = 0

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute("BEGIN")
        try:
            for row in preview.rows:
                if row.errors:
                    errors += 1
                    if any("Duplicate PIN" in error for error in row.errors):
                        duplicates_skipped += 1
                    if should_skip_invalid:
                        continue
                    continue

                if row.role == "student":
                    cursor = await connection.execute(
                        (
                            "INSERT OR IGNORE INTO students "
                            "(first_name, last_name, email, pin, school_year_id) "
                            "VALUES (?, ?, ?, ?, ?)"
                        ),
                        (row.first_name, row.last_name, row.email, row.pin, year_id),
                    )
                    if cursor.rowcount == 0:
                        duplicates_skipped += 1
                    else:
                        student_created += 1
                else:
                    teacher_email = row.email or f"teacher-{row.row_num}-{year_id}@placeholder.local"
                    cursor = await connection.execute(
                        (
                            "INSERT OR IGNORE INTO teachers "
                            "(first_name, last_name, email, password_hash, school_year_id) "
                            "VALUES (?, ?, ?, ?, ?)"
                        ),
                        (
                            row.first_name,
                            row.last_name,
                            teacher_email,
                            hash_password(row.password or ""),
                            year_id,
                        ),
                    )
                    if cursor.rowcount == 0:
                        duplicates_skipped += 1
                    else:
                        teacher_created += 1

            await connection.commit()
        except Exception:
            await connection.rollback()
            raise

    request.session.pop("import_preview", None)
    request.session.pop("import_year_id", None)

    flash(
        request,
        (
            f"{student_created} students, {teacher_created} teachers created. "
            f"{duplicates_skipped} duplicates skipped, {errors} errors."
        ),
        "success",
    )
    return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)


@router.post("/years/{year_id}/import/cancel")
async def import_users_cancel(request: Request, year_id: int, csrf_token: str = Form(...)):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=303)

    request.session.pop("import_preview", None)
    request.session.pop("import_year_id", None)
    request.session.pop("import_missing_columns", None)
    return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)


@router.post("/years/{year_id}/purge")
async def purge_school_year(
    request: Request,
    year_id: int,
    confirmation: str = Form(""),
    csrf_token: str = Form(...),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url="/admin/login", status_code=303)

    settings = get_settings()
    year = await get_school_year(settings.database_path, year_id)
    if not year:
        flash(request, "Year not found.", "error")
        return RedirectResponse(url="/admin/dashboard", status_code=303)

    if year["status"] != "ended":
        flash(request, "Only ended school years can be purged.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    if confirmation != "DELETE":
        flash(request, "Type DELETE to confirm.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            await connection.execute("BEGIN")
            try:
                async with connection.execute(
                    "SELECT status FROM school_years WHERE id = ?",
                    (year_id,),
                ) as cursor:
                    refreshed_year = await cursor.fetchone()

                if not refreshed_year or refreshed_year[0] != "ended":
                    await connection.rollback()
                    flash(request, "Only ended school years can be purged.", "error")
                    return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

                await connection.execute(
                    "DELETE FROM punches WHERE school_year_id = ?", (year_id,)
                )
                await connection.execute(
                    (
                        "DELETE FROM enrollments "
                        "WHERE student_id IN (SELECT id FROM students WHERE school_year_id = ?)"
                    ),
                    (year_id,),
                )
                await connection.execute(
                    (
                        "DELETE FROM enrollments "
                        "WHERE class_id IN (SELECT id FROM classes WHERE school_year_id = ?)"
                    ),
                    (year_id,),
                )
                await connection.execute(
                    "DELETE FROM classes WHERE school_year_id = ?", (year_id,)
                )
                await connection.execute(
                    "DELETE FROM students WHERE school_year_id = ?", (year_id,)
                )
                await connection.execute(
                    "UPDATE teachers SET school_year_id = NULL WHERE school_year_id = ?",
                    (year_id,),
                )
                await connection.execute(
                    "DELETE FROM school_years WHERE id = ? AND status = 'ended'",
                    (year_id,),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
    except aiosqlite.Error:
        flash(request, "A database error occurred.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    flash(request, "Data purged.", "success")
    return RedirectResponse(url="/admin/dashboard", status_code=303)


@router.post("/years/{year_id}/end")
async def end_school_year(request: Request, year_id: int, csrf_token: str = Form(...)):
    redirect = require_admin(request)
    if redirect:
        return redirect
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Invalid form submission. Please try again.", "error")
        return RedirectResponse(url="/admin/login", status_code=303)

    settings = get_settings()
    try:
        async with aiosqlite.connect(settings.database_path) as connection:
            cursor = await connection.execute(
                "UPDATE school_years SET status = 'ended' WHERE id = ? AND status = 'active'",
                (year_id,),
            )
            await connection.commit()
            if cursor.rowcount == 0:
                flash(request, "Year not found or already ended.", "error")
                return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)
    except aiosqlite.Error:
        flash(request, "A database error occurred.", "error")
        return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)

    flash(request, "School year ended.", "success")
    return RedirectResponse(url=f"/admin/years/{year_id}", status_code=303)
