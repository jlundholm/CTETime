import aiosqlite
import pytest


async def create_school_year(client, name: str, status: str) -> int:
    create_form = await client.get("/admin/years/create")
    token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = await client.post(
        "/admin/years/create",
        data={
            "name": name,
            "start_date": "2026-08-20",
            "end_date": "2027-05-28",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    year_id = int(response.headers["location"].rsplit("/", 1)[1])
    if status == "ended":
        year_page = await client.get(response.headers["location"])
        end_token = year_page.text.split('name="csrf_token" value="')[1].split('"')[0]
        await client.post(
            f"{response.headers['location']}/end",
            data={"csrf_token": end_token},
            follow_redirects=False,
        )
    return year_id


async def login_admin(client):
    login_page = await client.get("/admin/login")
    token = login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303


async def create_student_pin(client, app, *, pin: str, year_status: str = "active"):
    await login_admin(client)
    year_id = await create_school_year(client, "2026-2027", year_status)
    settings = app.state.settings if hasattr(app.state, "settings") else None
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            "INSERT INTO students (first_name, last_name, email, pin, school_year_id) VALUES (?, ?, ?, ?, ?)",
            ("Jane", "Student", "jane@student.edu", pin, year_id),
        )
        await connection.commit()


@pytest.mark.asyncio
async def test_valid_pin_login_creates_session_and_redirect_hint(client, app):
    await create_student_pin(client, app, pin="123456")

    response = await client.post("/auth/student/login", data={"pin": "123456"})
    assert response.status_code == 200
    assert response.json() == {"success": True, "redirect": "/student/clock"}

    clock_response = await client.get("/student/clock", follow_redirects=False)
    assert clock_response.status_code == 200
    assert "Clock In" in clock_response.text


@pytest.mark.asyncio
async def test_invalid_pin_returns_incorrect_pin_error(client, app):
    await create_student_pin(client, app, pin="123456")

    response = await client.post("/auth/student/login", data={"pin": "654321"})
    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "Incorrect PIN."
    assert payload["failures"] == 1
    assert payload["locked"] is False


@pytest.mark.asyncio
async def test_three_failed_attempts_returns_teacher_guidance(client, app):
    await create_student_pin(client, app, pin="123456")

    for _ in range(2):
        response = await client.post("/auth/student/login", data={"pin": "999999"})
        assert response.status_code == 401
        assert response.json()["error"] == "Incorrect PIN."

    third = await client.post("/auth/student/login", data={"pin": "999999"})
    assert third.status_code == 401
    payload = third.json()
    assert payload["error"] == "See your teacher for your PIN."
    assert payload["failures"] == 3
    assert payload["locked"] is False


@pytest.mark.asyncio
async def test_pin_for_ended_school_year_is_rejected(client, app):
    await create_student_pin(client, app, pin="111111", year_status="ended")

    response = await client.post("/auth/student/login", data={"pin": "111111"})
    assert response.status_code == 401
    assert response.json()["error"] == "Incorrect PIN."


@pytest.mark.asyncio
async def test_login_page_renders_backspace_key(client):
    response = await client.get("/student/login")
    assert response.status_code == 200
    assert 'data-action="backspace"' in response.text
    assert 'aria-label="Backspace"' in response.text
