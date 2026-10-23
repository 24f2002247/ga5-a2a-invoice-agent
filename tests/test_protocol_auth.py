import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_missing_bearer_token(async_client: AsyncClient):
    headers = {
        "A2A-Version": "1.0",
        "Content-Type": "application/a2a+json"
    }
    # No Authorization header
    resp = await async_client.get("/a2a/tasks", headers=headers)
    assert resp.status_code == 401

    # Non-Bearer scheme
    headers["Authorization"] = "Basic dXNlcjpwYXNz"
    resp = await async_client.get("/a2a/tasks", headers=headers)
    assert resp.status_code == 401

    # Empty Bearer
    headers["Authorization"] = "Bearer   "
    resp = await async_client.get("/a2a/tasks", headers=headers)
    assert resp.status_code == 401

    # Completely missing headers on GET /tasks and GET /a2a/tasks returns 401 (LIST_AUTH_REQUIRED)
    resp_no_headers = await async_client.get("/a2a/tasks")
    assert resp_no_headers.status_code == 401
    resp_root_tasks = await async_client.get("/tasks")
    assert resp_root_tasks.status_code == 401


@pytest.mark.anyio
async def test_missing_or_unsupported_a2a_version(async_client: AsyncClient, auth_headers: dict):
    # Missing A2A-Version
    headers = dict(auth_headers)
    del headers["A2A-Version"]
    resp = await async_client.get("/a2a/tasks", headers=headers)
    assert resp.status_code == 400

    # Unsupported version 2.0
    headers["A2A-Version"] = "2.0"
    resp = await async_client.get("/a2a/tasks", headers=headers)
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_invalid_media_type(async_client: AsyncClient, auth_headers: dict):
    headers = dict(auth_headers)
    headers["Content-Type"] = "application/xml"
    body = {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": []}}
    resp = await async_client.post("/a2a/message:send", headers=headers, json=body)
    assert resp.status_code == 415


@pytest.mark.anyio
async def test_response_envelope_and_media_type(async_client: AsyncClient, auth_headers: dict):
    resp = await async_client.get("/a2a/tasks", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/a2a+json")
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
    # Ensure response size is well under 512 KiB
    assert len(resp.content) < 512 * 1024
