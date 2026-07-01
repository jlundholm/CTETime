import pytest


@pytest.mark.asyncio
async def test_app_starts_and_login_surface_is_available(client):
    response = await client.get("/student/login")

    assert response.status_code == 200
    assert "CTE Time" in response.text
