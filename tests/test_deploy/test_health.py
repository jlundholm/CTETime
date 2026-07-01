import pytest


@pytest.mark.asyncio
async def test_app_starts_and_login_surface_is_available(client):
    response = await client.get("/student/login")

    assert response.status_code == 200
    assert "CTE Time" in response.text


@pytest.mark.asyncio
async def test_health_endpoint_returns_expected_payload(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "1.0.0",
        "database": "connected",
    }


@pytest.mark.asyncio
async def test_health_endpoint_reports_database_disconnected(client, monkeypatch):
    def _raise_connect(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.main.aiosqlite.connect", _raise_connect)

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "1.0.0",
        "database": "disconnected",
    }
