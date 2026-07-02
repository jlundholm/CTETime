from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from tests.test_student.test_auth import create_student_pin


def _csrf_headers(client, response_text: str) -> dict[str, str]:
    token = response_text.split('data-csrf-token="')[1].split('"')[0]
    return {"X-CSRF-Token": token}


async def _clock_page_csrf(client) -> dict[str, str]:
    page = await client.get("/student/clock")
    return _csrf_headers(client, page.text)


async def insert_punch(
    app,
    *,
    student_id: int,
    school_year_id: int,
    clock_in_time: str,
    clock_out_time: str | None,
):
    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            (
                "INSERT INTO punches (student_id, clock_in_time, clock_out_time, school_year_id) "
                "VALUES (?, ?, ?, ?)"
            ),
            (student_id, clock_in_time, clock_out_time, school_year_id),
        )
        await connection.commit()


@pytest.mark.asyncio
async def test_clock_screen_requires_auth(client):
    response = await client.get("/student/clock", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/student/login"


@pytest.mark.asyncio
async def test_clock_screen_loads_with_initial_button_states(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    response = await client.get("/student/clock")
    assert response.status_code == 200
    assert 'id="clock-in-btn"' in response.text
    assert 'id="clock-out-btn"' in response.text
    assert 'class="clock-button clock-out disabled"' in response.text


@pytest.mark.asyncio
async def test_clock_in_creates_open_punch(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)

    response = await client.post("/student/clock-in", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["action"] == "clock_in"
    assert "Clocked in at" in payload["message"]

    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute(
            "SELECT clock_out_time FROM punches WHERE clock_out_time IS NULL"
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_clock_in_twice_returns_already_clocked_in(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)

    first = await client.post("/student/clock-in", headers=headers)
    assert first.status_code == 200

    second = await client.post("/student/clock-in", headers=headers)
    payload = second.json()
    assert payload["success"] is False
    assert payload["error"] == "already_clocked_in"
    assert "Already clocked in at" in payload["message"]


@pytest.mark.asyncio
async def test_clock_out_after_clock_in_sets_clock_out_time(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)
    await client.post("/student/clock-in", headers=headers)

    response = await client.post("/student/clock-out", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["action"] == "clock_out"
    assert "duration" in payload
    assert "Clocked out" in payload["message"]


@pytest.mark.asyncio
async def test_clock_out_without_open_session_returns_message(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)

    response = await client.post("/student/clock-out", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "not_clocked_in"
    assert payload["message"] == "Not clocked in."


@pytest.mark.asyncio
async def test_clock_actions_handle_no_active_school_year(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)

    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute("UPDATE school_years SET status = 'ended'")
        await connection.commit()

    response = await client.post("/student/clock-in", headers=headers)
    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["message"] == "Couldn't record punch. Try again."


@pytest.mark.asyncio
async def test_clock_javascript_is_loaded_on_clock_screen(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    response = await client.get("/student/clock")
    assert response.status_code == 200
    assert '/static/js/clock.js' in response.text


@pytest.mark.asyncio
async def test_clock_in_requires_auth(client):
    response = await client.post("/student/clock-in")
    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_weekly_log_shows_punches_and_week_total(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute("SELECT id, school_year_id FROM students WHERE pin = ?", ("123456",)) as cursor:
            student_row = await cursor.fetchone()
    student_id = student_row[0]
    school_year_id = student_row[1]

    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    first_in = monday.replace(hour=8, minute=0, second=0, microsecond=0)
    first_out = monday.replace(hour=10, minute=0, second=0, microsecond=0)
    second_day = monday + timedelta(days=1)
    second_in = second_day.replace(hour=9, minute=0, second=0, microsecond=0)
    second_out = second_day.replace(hour=12, minute=30, second=0, microsecond=0)

    await insert_punch(
        app,
        student_id=student_id,
        school_year_id=school_year_id,
        clock_in_time=first_in.isoformat(),
        clock_out_time=first_out.isoformat(),
    )
    await insert_punch(
        app,
        student_id=student_id,
        school_year_id=school_year_id,
        clock_in_time=second_in.isoformat(),
        clock_out_time=second_out.isoformat(),
    )

    response = await client.get("/student/clock")
    assert response.status_code == 200
    assert "weekly-log-table" in response.text
    assert "Week Total" in response.text


@pytest.mark.asyncio
async def test_weekly_log_partial_endpoint_requires_auth(client):
    response = await client.get("/student/clock/log")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_weekly_log_partial_endpoint_renders_for_authenticated_student(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    response = await client.get("/student/clock/log")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_weekly_log_partial_updates_after_clock_in(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    before = await client.get("/student/clock/log")
    assert before.status_code == 200
    assert "weekly-log-table" not in before.text

    headers = await _clock_page_csrf(client)
    clock_in = await client.post("/student/clock-in", headers=headers)
    assert clock_in.status_code == 200
    assert clock_in.json()["success"] is True

    after = await client.get("/student/clock/log")
    assert after.status_code == 200
    assert "weekly-log-table" in after.text


@pytest.mark.asyncio
async def test_student_logout_clears_session_and_redirects(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    response = await client.post("/auth/student/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/student/login"

    follow_up = await client.get("/student/clock", follow_redirects=False)
    assert follow_up.status_code == 303
    assert follow_up.headers["location"] == "/student/login"


@pytest.mark.asyncio
async def test_student_logout_does_not_close_open_punch(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)
    await client.post("/student/clock-in", headers=headers)

    logout_response = await client.post("/auth/student/logout", follow_redirects=False)
    assert logout_response.status_code == 303

    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute(
            "SELECT clock_out_time FROM punches ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None


@pytest.mark.asyncio
async def test_clock_out_requires_auth(client):
    response = await client.post("/student/clock-out")
    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_clock_in_handles_db_error(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)

    original_connect = aiosqlite.connect

    class _MockDB:
        async def __aenter__(self):
            raise Exception("Simulated DB failure")

        async def __aexit__(self, *args):
            pass

    try:
        aiosqlite.connect = lambda *a, **kw: _MockDB()
        response = await client.post("/student/clock-in", headers=headers)
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert payload["error"] == "server_error"
    finally:
        aiosqlite.connect = original_connect


@pytest.mark.asyncio
async def test_clock_out_closes_prior_year_open_punch_when_active_year_changes(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})
    headers = await _clock_page_csrf(client)

    clock_in_response = await client.post("/student/clock-in", headers=headers)
    assert clock_in_response.status_code == 200
    assert clock_in_response.json()["success"] is True

    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute(
            "SELECT id, school_year_id FROM students WHERE pin = ?",
            ("123456",),
        ) as cursor:
            student_id, original_year_id = await cursor.fetchone()

        await connection.execute("UPDATE school_years SET status = 'ended' WHERE id = ?", (original_year_id,))
        year_cursor = await connection.execute(
            "INSERT INTO school_years (name, start_date, end_date, status) VALUES (?, ?, ?, 'active')",
            ("2027-2028", "2027-08-20", "2028-05-28"),
        )
        new_year_id = int(year_cursor.lastrowid)
        await connection.execute(
            "UPDATE students SET school_year_id = ? WHERE id = ?",
            (new_year_id, student_id),
        )
        await connection.commit()

    clock_out_response = await client.post("/student/clock-out", headers=headers)
    assert clock_out_response.status_code == 200
    payload = clock_out_response.json()
    assert payload["success"] is True
    assert payload["action"] == "clock_out"

    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute(
            "SELECT school_year_id, clock_out_time FROM punches WHERE student_id = ? ORDER BY id",
            (student_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == original_year_id
    assert rows[0][1] is not None


@pytest.mark.asyncio
async def test_get_active_school_year_id_prefers_most_recent_active(app):
    from app.config import get_settings
    from app.student.routes import get_active_school_year_id

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            "INSERT INTO school_years (name, start_date, end_date, status) VALUES (?, ?, ?, 'active')",
            ("2026-2027", "2026-08-20", "2027-05-28"),
        )
        second = await connection.execute(
            "INSERT INTO school_years (name, start_date, end_date, status) VALUES (?, ?, ?, 'active')",
            ("2027-2028", "2027-08-20", "2028-05-28"),
        )
        await connection.commit()
        year_id = await get_active_school_year_id(connection)

    assert year_id == int(second.lastrowid)


@pytest.mark.asyncio
async def test_weekly_log_excludes_future_punches(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute("SELECT id, school_year_id FROM students WHERE pin = ?", ("123456",)) as cursor:
            student_row = await cursor.fetchone()

    student_id = int(student_row[0])
    school_year_id = int(student_row[1])
    now = datetime.now(timezone.utc)

    await insert_punch(
        app,
        student_id=student_id,
        school_year_id=school_year_id,
        clock_in_time=(now - timedelta(hours=2)).isoformat(),
        clock_out_time=(now - timedelta(hours=1)).isoformat(),
    )
    await insert_punch(
        app,
        student_id=student_id,
        school_year_id=school_year_id,
        clock_in_time=(now + timedelta(hours=1)).isoformat(),
        clock_out_time=(now + timedelta(hours=2)).isoformat(),
    )

    response = await client.get("/student/clock/log")
    assert response.status_code == 200
    assert "1h 0m" in response.text
    assert "2h 0m" not in response.text


@pytest.mark.asyncio
async def test_week_start_day_setting_changes_student_weekly_total(client, app, monkeypatch):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    from app.config import get_settings
    import app.student.routes as student_routes

    fixed_now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)  # Wednesday
    monkeypatch.setattr(student_routes, "utc_now", lambda: fixed_now)

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute("SELECT id, school_year_id FROM students WHERE pin = ?", ("123456",)) as cursor:
            student_row = await cursor.fetchone()

    student_id = int(student_row[0])
    school_year_id = int(student_row[1])

    sunday_in = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
    sunday_out = datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc)
    monday_in = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
    monday_out = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)

    await insert_punch(
        app,
        student_id=student_id,
        school_year_id=school_year_id,
        clock_in_time=sunday_in.isoformat(),
        clock_out_time=sunday_out.isoformat(),
    )
    await insert_punch(
        app,
        student_id=student_id,
        school_year_id=school_year_id,
        clock_in_time=monday_in.isoformat(),
        clock_out_time=monday_out.isoformat(),
    )

    monkeypatch.setenv("WEEK_START_DAY", "0")
    get_settings.cache_clear()
    monday_week = await client.get("/student/clock/log")
    assert monday_week.status_code == 200
    assert "1h 0m" in monday_week.text

    monkeypatch.setenv("WEEK_START_DAY", "6")
    get_settings.cache_clear()
    sunday_week = await client.get("/student/clock/log")
    assert sunday_week.status_code == 200
    assert "2h 0m" in sunday_week.text
