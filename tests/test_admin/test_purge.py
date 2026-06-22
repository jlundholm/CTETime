import pytest


async def login_admin(client):
    form = await client.get("/admin/login")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )


async def create_year(client, name: str = "2026-2027") -> str:
    form = await client.get("/admin/years/create")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]
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
    return response.headers["location"]


async def end_year(client, year_location: str):
    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = await client.post(
        f"{year_location}/end",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    return response


async def seed_student(client, year_location: str) -> str:
    """Create a student in the given year and return the year_id."""
    year_id = year_location.rsplit("/", 1)[1]
    create_form = await client.get(f"{year_location}/users/create")
    token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "student",
            "first_name": "Purge",
            "last_name": "Test",
            "email": "",
            "pin": "999999",
            "password": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    return year_id


@pytest.mark.asyncio
async def test_purge_ended_year(client, test_database_path):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    await seed_student(client, year_location)

    await end_year(client, year_location)

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/admin/years/{year_id}/purge",
        data={"confirmation": "DELETE", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/dashboard"

    follow = await client.get(response.headers["location"])
    assert "Data purged." in follow.text

    detail_after = await client.get(year_location, follow_redirects=False)
    assert detail_after.status_code == 303


@pytest.mark.asyncio
async def test_purge_active_year_forbidden(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/admin/years/{year_id}/purge",
        data={"confirmation": "DELETE", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Only ended school years can be purged." in follow.text


@pytest.mark.asyncio
async def test_purge_wrong_confirmation(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    await end_year(client, year_location)

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/admin/years/{year_id}/purge",
        data={"confirmation": "delete", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Type DELETE to confirm." in follow.text


@pytest.mark.asyncio
async def test_purge_removes_data(client, test_database_path):
    import aiosqlite

    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    await seed_student(client, year_location)

    create_form = await client.get(f"{year_location}/users/create")
    create_token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "teacher",
            "first_name": "Purge",
            "last_name": "Teacher",
            "email": "purge.teacher@school.edu",
            "pin": "",
            "password": "StrongPass1",
            "csrf_token": create_token,
        },
        follow_redirects=False,
    )

    await end_year(client, year_location)

    async with aiosqlite.connect(test_database_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        async with connection.execute(
            "SELECT id FROM teachers WHERE school_year_id = ? LIMIT 1",
            (int(year_id),),
        ) as cursor:
            teacher_id = (await cursor.fetchone())[0]
        async with connection.execute(
            "SELECT id FROM students WHERE school_year_id = ? LIMIT 1",
            (int(year_id),),
        ) as cursor:
            student_id = (await cursor.fetchone())[0]
        class_cursor = await connection.execute(
            "INSERT INTO classes (name, teacher_id, school_year_id) VALUES (?, ?, ?)",
            ("Purge Class", teacher_id, int(year_id)),
        )
        class_id = class_cursor.lastrowid
        await connection.execute(
            "INSERT INTO enrollments (class_id, student_id) VALUES (?, ?)",
            (class_id, student_id),
        )
        await connection.execute(
            (
                "INSERT INTO punches (student_id, clock_in_time, clock_out_time, manual, school_year_id) "
                "VALUES (?, datetime('now'), datetime('now'), 0, ?)"
            ),
            (student_id, int(year_id)),
        )
        await connection.commit()

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/purge",
        data={"confirmation": "DELETE", "csrf_token": token},
        follow_redirects=False,
    )

    async with aiosqlite.connect(test_database_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        async with connection.execute(
            "SELECT COUNT(*) FROM students WHERE school_year_id = ?", (int(year_id),)
        ) as cursor:
            student_count = (await cursor.fetchone())[0]
        async with connection.execute(
            "SELECT COUNT(*) FROM classes WHERE school_year_id = ?", (int(year_id),)
        ) as cursor:
            class_count = (await cursor.fetchone())[0]
        async with connection.execute(
            "SELECT COUNT(*) FROM punches WHERE school_year_id = ?", (int(year_id),)
        ) as cursor:
            punch_count = (await cursor.fetchone())[0]
        async with connection.execute("SELECT COUNT(*) FROM enrollments") as cursor:
            enrollment_count = (await cursor.fetchone())[0]
        async with connection.execute(
            "SELECT COUNT(*) FROM school_years WHERE id = ?", (int(year_id),)
        ) as cursor:
            year_count = (await cursor.fetchone())[0]

    assert student_count == 0
    assert class_count == 0
    assert punch_count == 0
    assert enrollment_count == 0
    assert year_count == 0


@pytest.mark.asyncio
async def test_purge_teachers_preserved(client, test_database_path):
    import aiosqlite

    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    create_form = await client.get(f"{year_location}/users/create")
    token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "teacher",
            "first_name": "Keep",
            "last_name": "Teacher",
            "email": "keep@school.edu",
            "pin": "",
            "password": "StrongPass1",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    await end_year(client, year_location)

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/purge",
        data={"confirmation": "DELETE", "csrf_token": token},
        follow_redirects=False,
    )

    async with aiosqlite.connect(test_database_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        async with connection.execute(
            "SELECT COUNT(*) FROM teachers WHERE email = ?", ("keep@school.edu",)
        ) as cursor:
            count = (await cursor.fetchone())[0]
        async with connection.execute(
            "SELECT school_year_id FROM teachers WHERE email = ?", ("keep@school.edu",)
        ) as cursor:
            teacher_row = await cursor.fetchone()

    assert count == 1
    assert teacher_row is not None
    assert teacher_row[0] is None


@pytest.mark.asyncio
async def test_purge_requires_csrf(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]
    await end_year(client, year_location)

    response = await client.post(
        f"/admin/years/{year_id}/purge",
        data={"confirmation": "DELETE", "csrf_token": "bad-token"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Invalid form submission" in follow.text


@pytest.mark.asyncio
async def test_purge_button_not_on_active_year(client):
    await login_admin(client)
    year_location = await create_year(client)

    detail = await client.get(year_location)
    assert detail.status_code == 200
    assert "Purge Data" not in detail.text
    assert "Danger Zone" not in detail.text


@pytest.mark.asyncio
async def test_purge_button_disabled_until_delete_confirmation(client):
    await login_admin(client)
    year_location = await create_year(client)
    await end_year(client, year_location)

    detail = await client.get(year_location)
    assert detail.status_code == 200
    assert 'id="purge-submit" disabled' in detail.text
