import httpx
import pytest
from workworld_api.main import app


@pytest.mark.asyncio
async def test_health_and_openapi_contract() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        openapi = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "workworld-api",
        "protocol_version": "1.0",
    }
    assert "/health" in openapi.json()["paths"]
    sdk_paths = {
        "/v1/agents",
        "/v1/agents/{agent_id}/credentials",
        "/v1/agents/{agent_id}/endpoints",
        "/v1/agent-auth/token",
        "/v1/agent-callbacks/capacity",
        "/v1/agent-callbacks/events",
        "/v1/agent-callbacks/artifacts/uploads",
        "/v1/agent-callbacks/artifacts/{artifact_id}/parts/{part_number}",
        "/v1/agent-callbacks/artifacts/{artifact_id}/complete",
        "/v1/agent-callbacks/artifacts/{artifact_id}/download",
    }
    assert sdk_paths <= set(openapi.json()["paths"])


@pytest.mark.asyncio
async def test_browser_cors_preflight_allows_profile_updates() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/v1/profile",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "PUT" in response.headers["access-control-allow-methods"]
