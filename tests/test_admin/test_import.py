import io

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


@pytest.mark.asyncio
async def test_import_form_loads(client):
    await login_admin(client)
    year_location = await create_year(client)

    response = await client.get(f"{year_location}/import")
    assert response.status_code == 200
    assert "Import Users" in response.text


@pytest.mark.asyncio
async def test_import_valid_csv_preview_and_confirm(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    import_page = await client.get(f"{year_location}/import")
    token = import_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    csv_content = (
        "PIN,firstName,lastName,Email,Password\n"
        "123456,Jane,Student,jane@student.edu,\n"
        ",Terry,Teacher,terry@school.edu,StrongPass1\n"
    )
    files = {"file": ("users.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    preview_response = await client.post(
        f"/admin/years/{year_id}/import",
        data={"csrf_token": token},
        files=files,
        follow_redirects=False,
    )

    assert preview_response.status_code == 200
    assert "2 valid rows, 0 errors" in preview_response.text
    assert "✔ Valid" in preview_response.text

    confirm_token = preview_response.text.split('name="csrf_token" value="')[1].split('"')[0]
    confirm_response = await client.post(
        f"/admin/years/{year_id}/import/confirm",
        data={"csrf_token": confirm_token, "skip_invalid": "on"},
        follow_redirects=False,
    )
    assert confirm_response.status_code == 303
    assert confirm_response.headers["location"] == f"/admin/years/{year_id}"

    detail = await client.get(confirm_response.headers["location"])
    assert "1 students, 1 teachers created. 0 duplicates skipped, 0 errors." in detail.text


@pytest.mark.asyncio
async def test_import_missing_columns_shows_error(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    import_page = await client.get(f"{year_location}/import")
    token = import_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    csv_content = "firstName,lastName\nOnly,Names\n"
    files = {"file": ("broken.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

    response = await client.post(
        f"/admin/years/{year_id}/import",
        data={"csrf_token": token},
        files=files,
        follow_redirects=False,
    )

    assert response.status_code == 303
    follow = await client.get(response.headers["location"])
    assert "Missing required column(s): PIN" in follow.text


@pytest.mark.asyncio
async def test_import_duplicate_pin_and_cancel(client):
    await login_admin(client)
    year_location = await create_year(client)
    year_id = year_location.rsplit("/", 1)[1]

    import_page = await client.get(f"{year_location}/import")
    token = import_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    csv_content = (
        "PIN,firstName,lastName,Email,Password\n"
        "111111,Alpha,One,,\n"
        "111111,Beta,Two,,\n"
    )
    files = {"file": ("dupe.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    preview_response = await client.post(
        f"/admin/years/{year_id}/import",
        data={"csrf_token": token},
        files=files,
        follow_redirects=False,
    )

    assert preview_response.status_code == 200
    assert "Duplicate PIN found." in preview_response.text
    assert "1 valid rows, 1 errors" in preview_response.text

    cancel_token = preview_response.text.split('name="csrf_token" value="')[1].split('"')[0]
    cancel_response = await client.post(
        f"/admin/years/{year_id}/import/cancel",
        data={"csrf_token": cancel_token},
        follow_redirects=False,
    )
    assert cancel_response.status_code == 303
    assert cancel_response.headers["location"] == f"/admin/years/{year_id}"
