import pytest

from app.auth.staff import verify_password
from app.shared.helpers import generate_pin


async def login_admin(client):
    form = await client.get("/admin/login")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]
    resp = await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return resp


async def create_year(client, name: str = "2026-2027") -> str:
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
    assert response.status_code == 303
    return response.headers["location"]


@pytest.mark.asyncio
async def test_dashboard_empty_state(client):
    await login_admin(client)

    response = await client.get("/admin/dashboard")
    assert response.status_code == 200
    assert "No school years set up." in response.text
    assert "Create School Year" in response.text


@pytest.mark.asyncio
async def test_create_school_year_redirects_to_detail(client):
    await login_admin(client)

    create_form = await client.get("/admin/years/create")
    assert create_form.status_code == 200

    csrf_token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = await client.post(
        "/admin/years/create",
        data={
            "name": "2026-2027",
            "start_date": "2026-08-20",
            "end_date": "2027-05-28",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/years/")

    detail = await client.get(response.headers["location"])
    assert detail.status_code == 200
    assert "2026-2027" in detail.text
    assert "Active" in detail.text


@pytest.mark.asyncio
async def test_create_school_year_validation_error(client):
    await login_admin(client)
    create_form = await client.get("/admin/years/create")
    token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        "/admin/years/create",
        data={
            "name": "",
            "start_date": "2027-08-20",
            "end_date": "2027-05-28",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Please correct the highlighted errors." in response.text


@pytest.mark.asyncio
async def test_end_school_year_sets_status_to_ended(client):
    await login_admin(client)
    create_form = await client.get("/admin/years/create")
    token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    create_response = await client.post(
        "/admin/years/create",
        data={
            "name": "2025-2026",
            "start_date": "2025-08-20",
            "end_date": "2026-05-28",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    detail_page = await client.get(create_response.headers["location"])
    end_token = detail_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    end_response = await client.post(
        f"{create_response.headers['location']}/end",
        data={"csrf_token": end_token},
        follow_redirects=False,
    )

    assert end_response.status_code == 303

    ended_detail = await client.get(create_response.headers["location"])
    assert "Ended" in ended_detail.text
    assert "End School Year" not in ended_detail.text


@pytest.mark.asyncio
async def test_end_already_ended_year_shows_error(client):
    await login_admin(client)
    create_form = await client.get("/admin/years/create")
    token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    create_response = await client.post(
        "/admin/years/create",
        data={
            "name": "2024-2025",
            "start_date": "2024-08-20",
            "end_date": "2025-05-28",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    detail_page = await client.get(create_response.headers["location"])
    end_token = detail_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"{create_response.headers['location']}/end",
        data={"csrf_token": end_token},
        follow_redirects=False,
    )

    login_page = await client.get("/admin/login")
    end_token2 = login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    second_end = await client.post(
        f"{create_response.headers['location']}/end",
        data={"csrf_token": end_token2},
        follow_redirects=False,
    )
    assert second_end.status_code == 303

    follow = await client.get(second_end.headers["location"])
    assert "Year not found or already ended." in follow.text
    assert "Ended" in follow.text


@pytest.mark.asyncio
async def test_create_student(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    form = await client.get(f"/admin/years/{year_id}/users/create")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "student",
            "first_name": "Jane",
            "last_name": "Student",
            "email": "jane@student.edu",
            "pin": "123456",
            "password": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    detail = await client.get(response.headers["location"])
    assert "Student created." in detail.text
    assert "Jane Student" not in detail.text


@pytest.mark.asyncio
async def test_create_student_no_pin(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    form = await client.get(f"/admin/years/{year_id}/users/create")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "student",
            "first_name": "No",
            "last_name": "Pin",
            "email": "",
            "pin": "",
            "password": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "PIN is required for students." in response.text


@pytest.mark.asyncio
async def test_create_teacher(client, test_database_path):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    form = await client.get(f"/admin/years/{year_id}/users/create")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "teacher",
            "first_name": "Terry",
            "last_name": "Teacher",
            "email": "terry@school.edu",
            "pin": "",
            "password": "StrongPass1",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    detail = await client.get(response.headers["location"])
    assert "Teacher created." in detail.text
    assert "Terry Teacher" in detail.text
    assert "Active" in detail.text

    import aiosqlite

    async with aiosqlite.connect(test_database_path) as connection:
        connection.row_factory = aiosqlite.Row
        async with connection.execute(
            "SELECT password_hash FROM teachers WHERE school_year_id = ? AND email = ?",
            (int(year_id), "terry@school.edu"),
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None
    assert row["password_hash"] != "StrongPass1"
    assert verify_password("StrongPass1", row["password_hash"])


@pytest.mark.asyncio
async def test_create_duplicate_pin(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    form = await client.get(f"/admin/years/{year_id}/users/create")
    token = form.text.split('name="csrf_token" value="')[1].split('"')[0]
    first = await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "student",
            "first_name": "Alpha",
            "last_name": "One",
            "email": "",
            "pin": "111111",
            "password": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert first.status_code == 303

    detail = await client.get(first.headers["location"])
    token_2 = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    second = await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "student",
            "first_name": "Beta",
            "last_name": "Two",
            "email": "",
            "pin": "111111",
            "password": "",
            "csrf_token": token_2,
        },
        follow_redirects=False,
    )

    assert second.status_code == 200
    assert "PIN must be unique." in second.text


@pytest.mark.asyncio
async def test_deactivate_teacher(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    create_form = await client.get(f"/admin/years/{year_id}/users/create")
    create_token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "teacher",
            "first_name": "Dana",
            "last_name": "Active",
            "email": "dana@school.edu",
            "pin": "",
            "password": "StrongPass1",
            "csrf_token": create_token,
        },
        follow_redirects=False,
    )

    detail = await client.get(f"/admin/years/{year_id}")
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    marker = f"/admin/years/{year_id}/teachers/"
    teacher_id = detail.text.split(marker)[1].split("/deactivate")[0]

    response = await client.post(
        f"/admin/years/{year_id}/teachers/{teacher_id}/deactivate",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303

    refreshed = await client.get(response.headers["location"])
    assert "Teacher deactivated." in refreshed.text
    assert "Deactivated" in refreshed.text


@pytest.mark.asyncio
async def test_no_delete_option(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    detail = await client.get(f"/admin/years/{year_id}")
    assert detail.status_code == 200
    assert "Delete" not in detail.text


@pytest.mark.asyncio
async def test_deactivate_not_found(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]

    response = await client.post(
        f"/admin/years/{year_id}/teachers/99999/deactivate",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Teacher not found." in follow.text


@pytest.mark.asyncio
async def test_create_user_csrf_failure(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    response = await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "student",
            "first_name": "Bad",
            "last_name": "Csrf",
            "email": "",
            "pin": "123456",
            "password": "",
            "csrf_token": "invalid-token",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Invalid form submission" in follow.text


@pytest.mark.asyncio
async def test_deactivate_csrf_failure(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    response = await client.post(
        f"/admin/years/{year_id}/teachers/1/deactivate",
        data={"csrf_token": "invalid-token"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Invalid form submission" in follow.text


@pytest.mark.asyncio
async def test_create_user_ended_year(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/end",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    create_form = await client.get(f"/admin/years/{year_id}/users/create")
    assert create_form.status_code == 303

    detail2 = await client.get(year_location)
    token2 = detail2.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "student",
            "first_name": "Late",
            "last_name": "User",
            "email": "",
            "pin": "654321",
            "password": "",
            "csrf_token": token2,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Only active school years can accept new users." in follow.text


@pytest.mark.asyncio
async def test_generate_pin_uniqueness(client):
    existing = {"000000", "111111", "222222"}
    pin = generate_pin(existing)
    assert pin not in existing
    assert len(pin) == 6
    assert pin.isdigit()


@pytest.mark.asyncio
async def test_deactivate_already_inactive(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    create_form = await client.get(f"{year_location}/users/create")
    create_token = create_form.text.split('name="csrf_token" value="')[1].split('"')[0]
    await client.post(
        f"/admin/years/{year_id}/users/create",
        data={
            "role": "teacher",
            "first_name": "Twice",
            "last_name": "Deact",
            "email": "twice@school.edu",
            "pin": "",
            "password": "StrongPass1",
            "csrf_token": create_token,
        },
        follow_redirects=False,
    )

    detail = await client.get(year_location)
    token = detail.text.split('name="csrf_token" value="')[1].split('"')[0]
    marker = f"/admin/years/{year_id}/teachers/"
    teacher_id = detail.text.split(marker)[1].split("/deactivate")[0]

    await client.post(
        f"/admin/years/{year_id}/teachers/{teacher_id}/deactivate",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    detail2 = await client.get(year_location)
    token2 = detail2.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = await client.post(
        f"/admin/years/{year_id}/teachers/{teacher_id}/deactivate",
        data={"csrf_token": token2},
        follow_redirects=False,
    )
    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Teacher is already deactivated." in follow.text
