import re

import aiosqlite
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse

from app.auth.staff import (
    authenticate_admin,
    authenticate_teacher,
    create_session,
    create_teacher_session,
    destroy_session,
    destroy_teacher_session,
)
from app.auth.student import create_student_session, destroy_student_session, verify_student_pin
from app.config import get_settings
from app.shared.helpers import flash, validate_csrf_token


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Session expired. Please try again.", "error")
        return RedirectResponse(url="/admin/login", status_code=303)

    settings = get_settings()
    auth_result = await authenticate_admin(settings.database_path, email, password)

    if not auth_result:
        flash(request, "Invalid email or password.", "error")
        return RedirectResponse(url="/admin/login", status_code=303)

    create_session(request.session, auth_result)
    return RedirectResponse(url="/admin/dashboard", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    destroy_session(request.session)
    return RedirectResponse(url="/admin/login", status_code=303)


@router.post("/student/login")
async def student_login(request: Request, pin: str = Form(...)):
    normalized_pin = pin.strip()
    if not re.fullmatch(r"[0-9]{6}", normalized_pin):
        failures = request.session.get("student_pin_failures", 0) + 1
        request.session["student_pin_failures"] = failures
        message = "Incorrect PIN." if failures < 3 else "See your teacher for your PIN."
        return JSONResponse(
            {"success": False, "error": message, "failures": failures, "locked": False},
            status_code=401,
        )

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        auth_result = await verify_student_pin(connection, normalized_pin)

    if not auth_result:
        failures = request.session.get("student_pin_failures", 0) + 1
        request.session["student_pin_failures"] = failures
        message = "Incorrect PIN." if failures < 3 else "See your teacher for your PIN."
        return JSONResponse(
            {"success": False, "error": message, "failures": failures, "locked": False},
            status_code=401,
        )

    create_student_session(request, auth_result)
    return JSONResponse({"success": True, "redirect": "/student/clock"})


@router.post("/student/logout")
async def student_logout(request: Request):
    destroy_student_session(request.session)
    return RedirectResponse(url="/student/login", status_code=303)


@router.post("/teacher/login")
async def teacher_login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(...),
):
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Session expired. Please try again.", "error")
        return RedirectResponse(url="/teacher/login", status_code=303)

    settings = get_settings()
    auth_result = await authenticate_teacher(settings.database_path, email, password)

    if not auth_result:
        flash(request, "Invalid email or password.", "error")
        return RedirectResponse(url="/teacher/login", status_code=303)

    create_teacher_session(request.session, auth_result)
    return RedirectResponse(url="/teacher/dashboard", status_code=303)


@router.post("/teacher/logout")
async def teacher_logout(request: Request, csrf_token: str = Form(...)):
    try:
        validate_csrf_token(request, csrf_token)
    except HTTPException:
        flash(request, "Session expired. Please try again.", "error")
        return RedirectResponse(url="/teacher/dashboard", status_code=303)

    destroy_teacher_session(request.session)
    flash(request, "Logged out.", "success")
    return RedirectResponse(url="/teacher/login", status_code=303)
