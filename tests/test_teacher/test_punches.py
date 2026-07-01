from datetime import datetime, timedelta, timezone

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


async def create_class(*, teacher_id: int, school_year_id: int, name: str) -> int:
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        cursor = await connection.execute(
            "INSERT INTO classes (name, teacher_id, school_year_id) VALUES (?, ?, ?)",
            (name, teacher_id, school_year_id),
        )
        await connection.commit()
        return int(cursor.lastrowid)


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


async def enroll_student(*, class_id: int, student_id: int):
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            "INSERT INTO enrollments (class_id, student_id) VALUES (?, ?)",
            (class_id, student_id),
        )
        await connection.commit()


async def add_punch(
    *,
    student_id: int,
    school_year_id: int,
    clock_in: datetime,
    clock_out: datetime | None,
    manual: int = 0,
):
    settings = get_settings()
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.execute(
            (
                "INSERT INTO punches (student_id, clock_in_time, clock_out_time, manual, school_year_id) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (
                student_id,
                clock_in.astimezone(timezone.utc).isoformat(),
                clock_out.astimezone(timezone.utc).isoformat() if clock_out else None,
                manual,
                school_year_id,
            ),
        )
        await connection.commit()


@pytest.mark.asyncio
async def test_class_detail_table_shows_time_columns_and_pin(client, teacher_session):
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
    await enroll_student(class_id=class_id, student_id=student_id)

    now = datetime.now(timezone.utc)
    await add_punch(
        student_id=student_id,
        school_year_id=teacher_session["school_year_id"],
        clock_in=now - timedelta(minutes=75),
        clock_out=now - timedelta(minutes=15),
    )

    response = await client.get(f"/teacher/classes/{class_id}")
    assert response.status_code == 200
    assert "Today's Punch" in response.text
    assert "Week Total" in response.text
    assert "PIN" in response.text
    assert "123456" in response.text


@pytest.mark.asyncio
async def test_sortable_columns_name_desc(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 2",
    )
    s1 = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Alex",
        last_name="Alpha",
        pin="111111",
    )
    s2 = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Zoe",
        last_name="Zulu",
        pin="222222",
    )
    await enroll_student(class_id=class_id, student_id=s1)
    await enroll_student(class_id=class_id, student_id=s2)

    response = await client.get(f"/teacher/classes/{class_id}?sort=name&order=desc")
    assert response.status_code == 200
    assert response.text.index("Zulu, Zoe") < response.text.index("Alpha, Alex")


@pytest.mark.asyncio
async def test_expand_student_punches_partial_shows_history_and_manual_label(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 3",
    )
    student_id = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Casey",
        last_name="Clock",
        pin="333333",
    )
    await enroll_student(class_id=class_id, student_id=student_id)

    now = datetime.now(timezone.utc)
    await add_punch(
        student_id=student_id,
        school_year_id=teacher_session["school_year_id"],
        clock_in=now - timedelta(hours=2),
        clock_out=now - timedelta(hours=1),
        manual=1,
    )

    response = await client.get(f"/teacher/classes/{class_id}/students/{student_id}/punches")
    assert response.status_code == 200
    assert "(manual)" in response.text
    assert "Clock In" in response.text


@pytest.mark.asyncio
async def test_student_detail_page_and_empty_state(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 4",
    )
    student_id = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Pat",
        last_name="Punch",
        pin="444444",
    )
    await enroll_student(class_id=class_id, student_id=student_id)

    empty_response = await client.get(f"/teacher/students/{student_id}")
    assert empty_response.status_code == 200
    assert "No punches for Pat this year." in empty_response.text

    now = datetime.now(timezone.utc)
    await add_punch(
        student_id=student_id,
        school_year_id=teacher_session["school_year_id"],
        clock_in=now - timedelta(hours=1),
        clock_out=now,
    )

    populated_response = await client.get(f"/teacher/students/{student_id}")
    assert populated_response.status_code == 200
    assert "Student punch history" in populated_response.text
    assert "PIN:" in populated_response.text


@pytest.mark.asyncio
async def test_class_csv_export_and_date_filter(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 5",
    )
    student_id = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Dana",
        last_name="Data",
        pin="555555",
    )
    await enroll_student(class_id=class_id, student_id=student_id)

    in_range = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
    out_range = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)

    await add_punch(
        student_id=student_id,
        school_year_id=teacher_session["school_year_id"],
        clock_in=in_range,
        clock_out=in_range + timedelta(hours=1),
    )
    await add_punch(
        student_id=student_id,
        school_year_id=teacher_session["school_year_id"],
        clock_in=out_range,
        clock_out=out_range + timedelta(hours=1),
    )

    response = await client.get(f"/teacher/classes/{class_id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "First Name,Last Name,Clock In,Clock Out,Manual" in response.text
    assert "Dana,Data" in response.text

    filtered = await client.get(f"/teacher/classes/{class_id}/export?from=2026-09-01&to=2026-09-30")
    assert filtered.status_code == 200
    assert "2026-09-15" in filtered.text
    assert "2026-10-01" not in filtered.text


@pytest.mark.asyncio
async def test_student_csv_export(client, teacher_session):
    class_id = await create_class(
        teacher_id=teacher_session["teacher_id"],
        school_year_id=teacher_session["school_year_id"],
        name="Period 6",
    )
    student_id = await create_student(
        school_year_id=teacher_session["school_year_id"],
        first_name="Eli",
        last_name="Export",
        pin="666666",
    )
    await enroll_student(class_id=class_id, student_id=student_id)

    now = datetime.now(timezone.utc)
    await add_punch(
        student_id=student_id,
        school_year_id=teacher_session["school_year_id"],
        clock_in=now - timedelta(hours=1),
        clock_out=now,
        manual=1,
    )

    response = await client.get(f"/teacher/students/{student_id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "Eli,Export" in response.text
    assert ",Yes" in response.text
