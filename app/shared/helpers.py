import csv
import io
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from app.shared.models import ImportPreview, ImportRow


MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_PREVIEW_ROWS = 100


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_display_timezone() -> ZoneInfo:
    from app.config import get_settings

    return ZoneInfo(get_settings().display_timezone)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_week_start(value: datetime) -> datetime:
    current = ensure_utc(value)
    from app.config import get_settings

    week_start_day = get_settings().week_start_day
    days_since_week_start = (current.weekday() - week_start_day) % 7
    return current - timedelta(days=days_since_week_start)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return ensure_utc(parsed)


def generate_pin(existing_pins: set[str]) -> str:
    while True:
        pin = f"{secrets.randbelow(1_000_000):06d}"
        if pin not in existing_pins:
            return pin


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session["flash"] = {"message": message, "category": category}


def pop_flash(request: Request) -> dict[str, Any] | None:
    return request.session.pop("flash", None)


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = uuid4().hex
        request.session["csrf_token"] = token
    return token


def validate_csrf_token(request: Request, csrf_token: str) -> None:
    expected = request.session.get("csrf_token")
    if not expected or expected != csrf_token:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    request.session["csrf_token"] = uuid4().hex


def rotate_csrf_token(request: Request) -> None:
    request.session.pop("csrf_token", None)


def parse_csv(file_content: bytes) -> tuple[list[dict[str, str]], list[str]]:
    try:
        text = file_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [(h or "").strip() for h in (reader.fieldnames or [])]
    seen_headers: set[str] = set()
    unique_fieldnames: list[str] = []
    for h in fieldnames:
        if h and h not in seen_headers:
            seen_headers.add(h)
            unique_fieldnames.append(h)

    rows: list[dict[str, str]] = []
    for row in reader:
        normalized: dict[str, str] = {}
        for key in unique_fieldnames:
            value = row.get(key, "")
            normalized[key] = (value or "").strip()
        if any(v for v in normalized.values()):
            rows.append(normalized)
    return rows, unique_fieldnames


def required_columns_for_rows(rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> list[str]:
    headers = set(fieldnames) if fieldnames else (set(rows[0].keys()) if rows else set())
    missing = [column for column in ["PIN", "firstName", "lastName"] if column not in headers]

    requires_password = any(not (row.get("PIN") or "").strip() for row in rows)
    if requires_password and "Password" not in headers:
        missing.append("Password")

    return missing


def validate_import_rows(rows: list[dict[str, str]], existing_pins: set[str]) -> ImportPreview:
    seen_pins = set(existing_pins)
    parsed_rows: list[ImportRow] = []
    valid_count = 0
    error_count = 0
    duplicate_count = 0

    for index, raw_row in enumerate(rows, start=1):
        pin = (raw_row.get("PIN") or "").strip()
        first_name = (raw_row.get("firstName") or "").strip()
        last_name = (raw_row.get("lastName") or "").strip()
        email = (raw_row.get("Email") or "").strip() or None
        password = (raw_row.get("Password") or "").strip() or None

        role = "student" if pin else "teacher"
        errors: list[str] = []

        if len(first_name) == 0:
            errors.append("First name is required.")
        elif len(first_name) > 100:
            errors.append("First name must be 100 characters or fewer.")

        if len(last_name) == 0:
            errors.append("Last name is required.")
        elif len(last_name) > 100:
            errors.append("Last name must be 100 characters or fewer.")

        if role == "student":
            if not re.fullmatch(r"[0-9]{6}", pin):
                errors.append("PIN must be exactly 6 digits (0-9).")
            if pin in seen_pins:
                errors.append("Duplicate PIN found.")
                duplicate_count += 1
            else:
                seen_pins.add(pin)
        else:
            if not pin and not password:
                errors.append("Provide a PIN for a student or a Password for a teacher.")
            if not password:
                errors.append("Password is required for teachers.")
            elif len(password) < 8:
                errors.append("Password must be at least 8 characters.")
            elif len(password) > 128:
                errors.append("Password must be at most 128 characters.")

        if email:
            if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                errors.append("Invalid email format.")
            elif len(email) > 320:
                errors.append("Email must be 320 characters or fewer.")

        import_row = ImportRow(
            row_num=index,
            pin=pin or None,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=password,
            role=role,
            errors=errors,
        )

        if errors:
            error_count += 1
        else:
            valid_count += 1

        parsed_rows.append(import_row)

    return ImportPreview(
        rows=parsed_rows,
        total_rows=len(parsed_rows),
        valid_count=valid_count,
        error_count=error_count,
        duplicate_count=duplicate_count,
    )
