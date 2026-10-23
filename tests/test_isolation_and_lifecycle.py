import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.anyio
async def test_user_isolation(
    async_client: AsyncClient,
    sample_package_settle_invoice: dict
):
    headers_user_a = {
        "Authorization": "Bearer principal_user_A",
        "A2A-Version": "1.0",
        "Content-Type": "application/a2a+json"
    }
    headers_user_b = {
        "Authorization": "Bearer principal_user_B",
        "A2A-Version": "1.0",
        "Content-Type": "application/a2a+json"
    }

    # User B starts with empty task list
    resp_b_initial = await async_client.get("/a2a/tasks", headers=headers_user_b)
    assert resp_b_initial.status_code == 200
    assert resp_b_initial.json()["tasks"] == []

    # User A creates a task
    msg_a = {
        "message": {
            "messageId": "msg_user_a_001",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_user_a",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }
    resp_a_create = await async_client.post("/a2a/message:send", headers=headers_user_a, json=msg_a)
    assert resp_a_create.status_code == 200
    task_a_id = resp_a_create.json()["task"]["id"]

    # User A sees the task in list
    resp_a_list = await async_client.get("/a2a/tasks", headers=headers_user_a)
    assert resp_a_list.status_code == 200
    assert len(resp_a_list.json()["tasks"]) == 1
    assert resp_a_list.json()["tasks"][0]["id"] == task_a_id

    # User B list still has 0 tasks
    resp_b_list = await async_client.get("/a2a/tasks", headers=headers_user_b)
    assert resp_b_list.status_code == 200
    assert len(resp_b_list.json()["tasks"]) == 0

    # User B attempts to read User A's task -> 404
    resp_b_read = await async_client.get(f"/a2a/tasks/{task_a_id}", headers=headers_user_b)
    assert resp_b_read.status_code == 404

    # User B attempts to cancel User A's task -> 404
    resp_b_cancel = await async_client.post(f"/a2a/tasks/{task_a_id}:cancel", headers=headers_user_b)
    assert resp_b_cancel.status_code == 404

    # User B attempts continuation on User A's task -> 404
    msg_b_cont = {
        "message": {
            "messageId": "msg_user_b_attack",
            "taskId": task_a_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-action-results+json",
                    "data": {"batchId": "batch_user_a", "results": []}
                }
            ]
        }
    }
    resp_b_cont = await async_client.post("/a2a/message:send", headers=headers_user_b, json=msg_b_cont)
    assert resp_b_cont.status_code == 404


@pytest.mark.anyio
async def test_nonterminal_cancellation(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    msg = {
        "message": {
            "messageId": "msg_cancel_001",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_cancel_test",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }
    r_create = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg)
    assert r_create.status_code == 200
    t_id = r_create.json()["task"]["id"]

    # Cancel nonterminal task
    r_cancel = await async_client.post(f"/a2a/tasks/{t_id}:cancel", headers=auth_headers)
    assert r_cancel.status_code == 200
    data = r_cancel.json()
    task = data.get("task", data)
    assert task["status"]["state"] == "TASK_STATE_CANCELED"

    # Attempting to cancel again returns 409
    r_cancel_again = await async_client.post(f"/a2a/tasks/{t_id}:cancel", headers=auth_headers)
    assert r_cancel_again.status_code == 409

    # Verify canceled task contains NO receipt artifact
    for art in task.get("artifacts", []):
        assert art["mediaType"] != "application/vnd.ga5.invoice-action-receipts+json"


@pytest.mark.anyio
async def test_cancellation_versus_receipt_race(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    msg1 = {
        "message": {
            "messageId": "msg_race_init",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_race",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }
    r1 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg1)
    assert r1.status_code == 200
    task1 = r1.json()["task"]
    t_id = task1["id"]
    ctx_id = task1["contextId"]
    prop = task1["artifacts"][0]["data"]["proposals"][0]

    msg_cont = {
        "message": {
            "messageId": "msg_race_cont",
            "taskId": t_id,
            "contextId": ctx_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-action-results+json",
                    "data": {
                        "batchId": "batch_race",
                        "results": [
                            {
                                "packageId": prop["packageId"],
                                "actionId": prop["actionId"],
                                "action": prop["action"],
                                "outcome": "ACCEPTED",
                                "receiptNonce": "nonce_race_999"
                            }
                        ]
                    }
                }
            ]
        }
    }

    # Concurrently execute cancel and result continuation
    cancel_coro = async_client.post(f"/a2a/tasks/{t_id}:cancel", headers=auth_headers)
    cont_coro = async_client.post("/a2a/message:send", headers=auth_headers, json=msg_cont)

    results = await asyncio.gather(cancel_coro, cont_coro)
    status_codes = [r.status_code for r in results]

    # Exactly one operation returns HTTP 200, and the losing operation returns HTTP 409
    assert 200 in status_codes
    assert 409 in status_codes
    assert len(status_codes) == 2


@pytest.mark.anyio
async def test_persistence_across_app_restart(
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    # Create task on instance 1
    transport1 = ASGITransport(app=app)
    async with AsyncClient(transport=transport1, base_url="http://testserver") as client1:
        msg = {
            "message": {
                "messageId": "msg_restart_test",
                "role": "ROLE_USER",
                "parts": [
                    {
                        "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                        "data": {
                            "batchId": "batch_restart",
                            "packages": [sample_package_settle_invoice]
                        }
                    }
                ]
            }
        }
        r1 = await client1.post("/a2a/message:send", headers=auth_headers, json=msg)
        assert r1.status_code == 200
        task_id = r1.json()["task"]["id"]

    # Re-instantiate client (simulating restart reading from same DB)
    transport2 = ASGITransport(app=app)
    async with AsyncClient(transport=transport2, base_url="http://testserver") as client2:
        r2 = await client2.get(f"/a2a/tasks/{task_id}", headers=auth_headers)
        assert r2.status_code == 200
        task2_data = r2.json()
        task2_obj = task2_data.get("task", task2_data)
        assert task2_obj["id"] == task_id
        assert task2_obj["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
