import aiosqlite
import pytest

from app.config import get_settings


_OVERRIDE_TIMEZONE = "America/Chicago"


@pytest.mark.asyncio
async def test_database_rows_do_not_leak_within_test(app):
    settings = get_settings()

    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            "INSERT INTO school_years (name, start_date, end_date, status) VALUES (?, ?, ?, 'active')",
            ("Isolated Year", "2026-08-20", "2027-05-28"),
        )
        await connection.commit()

        async with connection.execute("SELECT COUNT(*) FROM school_years") as cursor:
            count = (await cursor.fetchone())[0]

    assert count == 1


@pytest.mark.asyncio
async def test_database_rows_from_previous_test_are_not_present(app):
    settings = get_settings()

    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute("SELECT COUNT(*) FROM school_years") as cursor:
            count = (await cursor.fetchone())[0]

    assert count == 0


def test_display_timezone_override_sets_value(monkeypatch):
    monkeypatch.setenv("DISPLAY_TIMEZONE", _OVERRIDE_TIMEZONE)
    get_settings.cache_clear()

    assert get_settings().display_timezone == _OVERRIDE_TIMEZONE


def test_display_timezone_override_from_previous_test_does_not_leak():
    assert get_settings().display_timezone != _OVERRIDE_TIMEZONE
