import pytest


async def get_csrf_token(client):
    login_page = await client.get("/admin/login")
    assert login_page.status_code == 200
    token = (
        login_page.text.split('name="csrf_token" value="')[1]
        .split('"')[0]
    )
    return token


@pytest.mark.asyncio
async def test_valid_admin_login_redirects_to_dashboard(client):
    token = await get_csrf_token(client)
    response = await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/dashboard"

    dashboard_response = await client.get("/admin/dashboard", follow_redirects=False)
    assert dashboard_response.status_code == 200


@pytest.mark.asyncio
async def test_invalid_admin_login_sets_flash_error(client):
    token = await get_csrf_token(client)
    response = await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "wrong-password", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"

    login_page = await client.get("/admin/login")
    assert login_page.status_code == 200
    assert "Invalid email or password." in login_page.text


@pytest.mark.asyncio
async def test_admin_logout_clears_session(client):
    token = await get_csrf_token(client)
    await client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )

    logout_response = await client.post("/auth/logout", follow_redirects=False)
    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/admin/login"

    dashboard_response = await client.get("/admin/dashboard", follow_redirects=False)
    assert dashboard_response.status_code == 303
    assert dashboard_response.headers["location"] == "/admin/login"
