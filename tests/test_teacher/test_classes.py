import aiosqlite
import pytest
import pytest_asyncio

from app.auth.staff import hash_password
from app.config import get_settings


async def get_teacher_csrf_token(client):
    login_page = await client.get("/teacher/login")
    assert login_page.status_code == 200
    return login_page.text.split('name="csrf_token" value="')[1].split('"')[0]


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


@pytest_asyncio.fixture
async def teacher_session(client, sample_teacher):
    token = await get_teacher_csrf_token(client)
    response = await client.post(
        "/auth/teacher/login",
        data={"email": "teacher@example.com", "password": "teacher-pass", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/teacher/dashboard"
    return sample_teacher


async def create_student(*, school_year_id: int, first_name: str, last_name: str, pin: str) -> int:
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        cursor = await connection.execute(
            (
                "INSERT INTO students (first_name, last_name, email, pin, school_year_id) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (first_name, last_name, f"{first_name.lower()}@student.test", pin, school_year_id),
        )
        await connection.commit()
        return int(cursor.lastrowid)


async def create_class(*, teacher_id: int, school_year_id: int, name: str = "Period 1") -> int:
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        cursor = await connection.execute(
            "INSERT INTO classes (name, teacher_id, school_year_id) VALUES (?, ?, ?)",
            (name, teacher_id, school_year_id),
        )
        await connection.commit()
        return int(cursor.lastrowid)


@pytest.mark.asyncio
async def test_create_class(client, teacher_session):
    dashboard = await client.get("/teacher/dashboard")
    csrf = dashboard.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        "/teacher/classes/create",
        data={"name": "Period 3", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/teacher/dashboard"

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute(
            "SELECT name, teacher_id, school_year_id FROM classes WHERE name = ?",
            ("Period 3",),
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "Period 3"
    assert row[1] == teacher_session["teacher_id"]
    assert row[2] == teacher_session["school_year_id"]


@pytest.mark.asyncio
async def test_class_detail(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 1",
    )
    student_id = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Sam",
        last_name="Student",
        pin="123456",
    )

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            "INSERT INTO enrollments (class_id, student_id) VALUES (?, ?)",
            (class_id, student_id),
        )
        await connection.commit()

    response = await client.get(f"/teacher/classes/{class_id}")

    assert response.status_code == 200
    assert "Period 1" in response.text
    assert "Student, Sam" in response.text
    assert "123456" in response.text
    assert "Add Students" in response.text


@pytest.mark.asyncio
async def test_rename_class(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 1",
    )

    class_page = await client.get(f"/teacher/classes/{class_id}")
    csrf = class_page.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/teacher/classes/{class_id}/rename",
        data={"name": "Period 1A", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/teacher/classes/{class_id}"

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute("SELECT name FROM classes WHERE id = ?", (class_id,)) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "Period 1A"


@pytest.mark.asyncio
async def test_add_students(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 2",
    )
    sid_1 = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Alex",
        last_name="A",
        pin="111111",
    )
    sid_2 = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Bri",
        last_name="B",
        pin="222222",
    )

    class_page = await client.get(f"/teacher/classes/{class_id}")
    csrf = class_page.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/teacher/classes/{class_id}/add-students",
        data={"student_ids": [str(sid_1), str(sid_2)], "csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/teacher/classes/{class_id}"

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute(
            "SELECT student_id FROM enrollments WHERE class_id = ? ORDER BY student_id",
            (class_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    assert [row[0] for row in rows] == sorted([sid_1, sid_2])


@pytest.mark.asyncio
async def test_remove_student_preserves_punch_data(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 4",
    )
    student_id = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Casey",
        last_name="Clock",
        pin="333333",
    )

    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            "INSERT INTO enrollments (class_id, student_id) VALUES (?, ?)",
            (class_id, student_id),
        )
        await connection.execute(
            (
                "INSERT INTO punches (student_id, clock_in_time, clock_out_time, school_year_id) "
                "VALUES (?, ?, ?, ?)"
            ),
            (student_id, "2026-09-01T08:00:00+00:00", "2026-09-01T10:00:00+00:00", teacher_session["school_year_id"]),
        )
        await connection.commit()

    class_page = await client.get(f"/teacher/classes/{class_id}")
    csrf = class_page.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/teacher/classes/{class_id}/students/{student_id}/remove",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/teacher/classes/{class_id}"

    async with aiosqlite.connect(settings.database_path) as connection:
        async with connection.execute(
            "SELECT COUNT(*) FROM enrollments WHERE class_id = ? AND student_id = ?",
            (class_id, student_id),
        ) as cursor:
            enrollment_count = (await cursor.fetchone())[0]
        async with connection.execute(
            "SELECT COUNT(*) FROM punches WHERE student_id = ?",
            (student_id,),
        ) as cursor:
            punch_count = (await cursor.fetchone())[0]

    assert enrollment_count == 0
    assert punch_count == 1


@pytest.mark.asyncio
async def test_empty_roster_shows_message(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Empty Class",
    )

    response = await client.get(f"/teacher/classes/{class_id}")

    assert response.status_code == 200
    assert "No students in this class." in response.text
    assert "Add Students" in response.text


@pytest.mark.asyncio
async def test_no_delete_class_route_or_button(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="No Removal",
    )

    detail = await client.get(f"/teacher/classes/{class_id}")
    assert detail.status_code == 200
    assert "/delete" not in detail.text

    delete_response = await client.post(f"/teacher/classes/{class_id}/delete", follow_redirects=False)
    assert delete_response.status_code == 404
