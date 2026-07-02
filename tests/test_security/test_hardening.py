import aiosqlite
import pytest

from tests.test_student.test_auth import create_student_pin


async def _admin_login(client):
    form = await client.get("/admin/login")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return token


@pytest.mark.asyncio
async def test_csrf_token_rotates_and_old_token_is_rejected(client):
    await _admin_login(client)

    create_form = await client.get("/admin/years/create")
    token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]

    create_response = await client.post(
        "/admin/years/create",
        data={
            "name": "2027-2028",
            "start_date": "2027-08-20",
            "end_date": "2028-05-28",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    detail = await client.get(create_response.headers["location"])
    new_token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    assert new_token != token

    rejected = await client.post(
        "/admin/years/create",
        data={
            "name": "2028-2029",
            "start_date": "2028-08-20",
            "end_date": "2029-05-28",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert rejected.headers["location"] == "/admin/login"


@pytest.mark.asyncio
async def test_post_rate_limit_returns_429_and_retry_after(client):
    for _ in range(60):
        response = await client.post("/auth/student/login", data={"pin": "123456"})
        assert response.status_code in {401, 200}

    limited = await client.post("/auth/student/login", data={"pin": "123456"})
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After") is not None
    payload = limited.json()
    assert payload["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_tampered_student_session_is_cleared_and_redirected(client, app):
    await create_student_pin(client, app, pin="123456")
    await client.post("/auth/student/login", data={"pin": "123456"})

    from app.config import get_settings

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute("DELETE FROM students WHERE pin = ?", ("123456",))
        await connection.commit()

    clock_page = await client.get("/student/clock", follow_redirects=False)
    assert clock_page.status_code == 303
    assert clock_page.headers["location"] == "/student/login"

    clock_in = await client.post("/student/clock-in")
    assert clock_in.status_code == 401
    assert clock_in.json()["error"] == "unauthorized"
