from types import SimpleNamespace

import aiosqlite
import pytest
import pytest_asyncio

from app.auth.staff import hash_password
from app.config import get_settings


@pytest_asyncio.fixture
async def sample_teacher(app):
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        cursor = await connection.execute(
            "INSERT INTO school_years (name, start_date, end_date, status) VALUES (?, ?, ?, 'active')",
            ("2026-2027", "2026-08-01", "2027-05-31"),
        )
        year_id = cursor.lastrowid
        teacher_cursor = await connection.execute(
            (
                "INSERT INTO teachers "
                "(first_name, last_name, email, password_hash, is_active, school_year_id) "
                "VALUES (?, ?, ?, ?, 1, ?)"
            ),
            ("Taylor", "Teacher", "teacher@example.com", hash_password("teacher-pass"), year_id),
        )
        teacher_id = teacher_cursor.lastrowid
        await connection.commit()
    return {"teacher_id": teacher_id, "school_year_id": year_id}


async def get_teacher_csrf_token(client):
    login_page = await client.get("/teacher/login")
    assert login_page.status_code == 200
    token = login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    return token


@pytest.mark.asyncio
async def test_teacher_login_redirects_to_dashboard(client, sample_teacher):
    token = await get_teacher_csrf_token(client)
    response = await client.post(
        "/auth/teacher/login",
        data={"email": "teacher@example.com", "password": "teacher-pass", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/teacher/dashboard"

    dashboard = await client.get("/teacher/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200
    assert "My Classes" in dashboard.text


@pytest.mark.asyncio
async def test_teacher_login_invalid_credentials_shows_flash(client, sample_teacher):
    token = await get_teacher_csrf_token(client)
    response = await client.post(
        "/auth/teacher/login",
        data={"email": "teacher@example.com", "password": "wrong-pass", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/teacher/login"

    login_page = await client.get("/teacher/login")
    assert "Invalid email or password." in login_page.text


@pytest.mark.asyncio
async def test_teacher_dashboard_empty_state(client, sample_teacher):
    token = await get_teacher_csrf_token(client)
    await client.post(
        "/auth/teacher/login",
        data={"email": "teacher@example.com", "password": "teacher-pass", "csrf_token": token},
        follow_redirects=False,
    )

    response = await client.get("/teacher/dashboard")
    assert response.status_code == 200
    assert "No classes yet. Create one to get started." in response.text


@pytest.mark.asyncio
async def test_teacher_dashboard_lists_classes_with_student_counts(client, sample_teacher):
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        class_cursor = await connection.execute(
            "INSERT INTO classes (name, teacher_id, school_year_id) VALUES (?, ?, ?)",
            ("Period 1", sample_teacher["teacher_id"], sample_teacher["school_year_id"]),
        )
        class_id = class_cursor.lastrowid
        student_cursor = await connection.execute(
            (
                "INSERT INTO students (first_name, last_name, email, pin, school_year_id) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            ("Sam", "Student", "sam@student.test", "123456", sample_teacher["school_year_id"]),
        )
        student_id = student_cursor.lastrowid
        await connection.execute(
            "INSERT INTO enrollments (class_id, student_id) VALUES (?, ?)",
            (class_id, student_id),
        )
        await connection.commit()

    token = await get_teacher_csrf_token(client)
    await client.post(
        "/auth/teacher/login",
        data={"email": "teacher@example.com", "password": "teacher-pass", "csrf_token": token},
        follow_redirects=False,
    )

    response = await client.get("/teacher/dashboard")
    assert response.status_code == 200
    assert "Period 1" in response.text
    assert ">1<" in response.text


@pytest.mark.asyncio
async def test_teacher_logout_clears_session(client, sample_teacher):
    token = await get_teacher_csrf_token(client)
    await client.post(
        "/auth/teacher/login",
        data={"email": "teacher@example.com", "password": "teacher-pass", "csrf_token": token},
        follow_redirects=False,
    )

    dashboard = await client.get("/teacher/dashboard")
    logout_token = dashboard.text.split('name="csrf_token" value="')[1].split('"')[0]
    logout = await client.post(
        "/auth/teacher/logout",
        data={"csrf_token": logout_token},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/teacher/login"

    dashboard = await client.get("/teacher/dashboard", follow_redirects=False)
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/teacher/login"


@pytest.mark.asyncio
async def test_teacher_dashboard_requires_auth(client):
    response = await client.get("/teacher/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/teacher/login"


@pytest.mark.asyncio
async def test_deactivated_teacher_cannot_login(client, sample_teacher):
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            "UPDATE teachers SET is_active = 0 WHERE email = ?",
            ("teacher@example.com",),
        )
        await connection.commit()

    token = await get_teacher_csrf_token(client)
    response = await client.post(
        "/auth/teacher/login",
        data={"email": "teacher@example.com", "password": "teacher-pass", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/teacher/login"


def test_require_teacher_rejects_none_session_value():
    from app.teacher.routes import require_teacher

    request = SimpleNamespace(session={"teacher_id": None})
    assert require_teacher(request) is False
