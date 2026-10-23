import asyncio
import pytest
from httpx import AsyncClient
from unittest.mock import patch


@pytest.mark.anyio
async def test_initial_request_replay_and_reordered_keys(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    msg_orig = {
        "message": {
            "messageId": "msg_replay_001",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_rep",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        },
        "configuration": {
            "returnImmediately": False,
            "historyLength": 10
        }
    }

    # 1. First initial send
    resp1 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_orig)
    assert resp1.status_code == 200
    task1 = resp1.json()["task"]

    # 2. Exact Replay
    resp2 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_orig)
    assert resp2.status_code == 200
    task2 = resp2.json()["task"]
    assert task2["id"] == task1["id"]

    # 3. Reordered JSON keys in message
    msg_reordered = {
        "configuration": {
            "historyLength": 10,
            "returnImmediately": False
        },
        "message": {
            "parts": [
                {
                    "data": {
                        "packages": [sample_package_settle_invoice],
                        "batchId": "batch_rep"
                    },
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json"
                }
            ],
            "role": "ROLE_USER",
            "messageId": "msg_replay_001"
        }
    }

    resp3 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_reordered)
    assert resp3.status_code == 200
    task3 = resp3.json()["task"]
    assert task3["id"] == task1["id"]

    # 4. Changed configuration with identical message content -> should return same task without conflict
    msg_changed_conf = {
        "message": msg_orig["message"],
        "configuration": {
            "returnImmediately": True,
            "historyLength": 50
        }
    }
    resp4 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_changed_conf)
    assert resp4.status_code == 200
    assert resp4.json()["task"]["id"] == task1["id"]


@pytest.mark.anyio
async def test_changed_content_idempotency_conflict(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict,
    sample_package_reject_duplicate: dict
):
    msg_1 = {
        "message": {
            "messageId": "msg_conflict_test",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_c1",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }

    resp1 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_1)
    assert resp1.status_code == 200
    task1 = resp1.json()["task"]

    # Reusing messageId with altered packages
    msg_conflict = {
        "message": {
            "messageId": "msg_conflict_test",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_c2",
                        "packages": [sample_package_reject_duplicate]
                    }
                }
            ]
        }
    }

    resp_conflict = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_conflict)
    assert resp_conflict.status_code == 409
    err = resp_conflict.json()
    assert "IDEMPOTENCY_CONFLICT" in str(err)

    # Verify original task is unaltered
    resp_get = await async_client.get(f"/a2a/tasks/{task1['id']}", headers=auth_headers)
    assert resp_get.status_code == 200
    task_res = resp_get.json()
    task_obj = task_res.get("task", task_res)
    assert task_obj["id"] == task1["id"]
    assert task_obj["artifacts"][0]["data"]["batchId"] == "batch_c1"


@pytest.mark.anyio
async def test_concurrent_identical_initial_requests(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    msg = {
        "message": {
            "messageId": "msg_concurrent_001",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_conc",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }

    # Launch 5 concurrent identical requests
    tasks = [
        async_client.post("/a2a/message:send", headers=auth_headers, json=msg)
        for _ in range(5)
    ]
    responses = await asyncio.gather(*tasks)

    for r in responses:
        assert r.status_code == 200

    task_ids = {r.json()["task"]["id"] for r in responses}
    # Exactly one task created
    assert len(task_ids) == 1


@pytest.mark.anyio
async def test_no_model_calls_for_polls_replays_cancel(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    msg = {
        "message": {
            "messageId": "msg_no_calls_test",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_nc",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }

    resp = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg)
    assert resp.status_code == 200
    task_id = resp.json()["task"]["id"]

    # In all of these operations, call_ai_model_batch should NEVER be called
    with patch("app.decision_engine.call_ai_model_batch") as mock_ai:
        # 1. Read task
        await async_client.get(f"/a2a/tasks/{task_id}", headers=auth_headers)
        # 2. List tasks
        await async_client.get("/a2a/tasks", headers=auth_headers)
        # 3. Replay initial request
        await async_client.post("/a2a/message:send", headers=auth_headers, json=msg)
        # 4. Cancel task
        await async_client.post(f"/a2a/tasks/{task_id}:cancel", headers=auth_headers)

        assert mock_ai.call_count == 0
