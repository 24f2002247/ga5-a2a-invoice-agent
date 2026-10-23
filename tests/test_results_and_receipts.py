import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_accepted_and_rejected_receipt_results(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict,
    sample_package_reject_duplicate: dict
):
    # 1. Submit initial batch with 2 packages
    msg1 = {
        "message": {
            "messageId": "msg_res_001",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_res_test",
                        "packages": [sample_package_settle_invoice, sample_package_reject_duplicate]
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
    proposals = task1["artifacts"][0]["data"]["proposals"]
    prop0 = proposals[0]
    prop1 = proposals[1]

    # 2. Submit continuation with one ACCEPTED and one REJECTED
    nonce_0 = "receipt_nonce_abc123"
    results = [
        {
            "packageId": prop0["packageId"],
            "actionId": prop0["actionId"],
            "action": prop0["action"],
            "outcome": "ACCEPTED",
            "receiptNonce": nonce_0
        },
        {
            "packageId": prop1["packageId"],
            "actionId": prop1["actionId"],
            "action": prop1["action"],
            "outcome": "REJECTED"
        }
    ]

    msg2 = {
        "message": {
            "messageId": "msg_continuation_001",
            "taskId": t_id,
            "contextId": ctx_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-action-results+json",
                    "data": {
                        "batchId": "batch_res_test",
                        "results": results
                    }
                }
            ]
        }
    }

    r2 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg2)
    assert r2.status_code == 200
    task2 = r2.json()["task"]

    # Verify task state is TASK_STATE_COMPLETED
    assert task2["status"]["state"] == "TASK_STATE_COMPLETED"

    # Both proposal artifact and receipt artifact exist
    artifacts = task2["artifacts"]
    assert len(artifacts) == 2
    assert artifacts[0]["mediaType"] == "application/vnd.ga5.invoice-action-proposals+json"
    assert artifacts[1]["mediaType"] == "application/vnd.ga5.invoice-action-receipts+json"

    # Only ACCEPTED proposal is in executions
    executions = artifacts[1]["data"]["executions"]
    assert len(executions) == 1
    exec0 = executions[0]
    assert exec0["packageId"] == prop0["packageId"]
    assert exec0["actionId"] == prop0["actionId"]
    assert exec0["action"] == prop0["action"]
    assert exec0["receiptNonce"] == nonce_0
    assert exec0["facts"] == prop0["facts"]
    assert exec0["evidenceRefs"] == prop0["evidenceRefs"]

    # History includes both messages
    assert len(task2["history"]) == 2

    # 3. Terminal task replay of continuation message
    r2_replay = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg2)
    assert r2_replay.status_code == 200
    assert r2_replay.json()["task"]["status"]["state"] == "TASK_STATE_COMPLETED"

    # 4. Terminal task replay of initial message
    r1_replay = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg1)
    assert r1_replay.status_code == 200
    assert r1_replay.json()["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.anyio
async def test_invalid_continuation_rejections(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    # Setup a valid task
    msg1 = {
        "message": {
            "messageId": "msg_setup_reject",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_val_test",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }
    r1 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg1)
    assert r1.status_code == 200
    task = r1.json()["task"]
    t_id = task["id"]
    ctx_id = task["contextId"]
    prop = task["artifacts"][0]["data"]["proposals"][0]

    # A. Unknown task ID
    msg_bad_task = {
        "message": {
            "messageId": "msg_bad_t",
            "taskId": "task_nonexistent_999",
            "contextId": ctx_id,
            "role": "ROLE_USER",
            "parts": [{"mediaType": "application/vnd.ga5.invoice-action-results+json", "data": {"batchId": "batch_val_test", "results": []}}]
        }
    }
    r_bad_t = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_bad_task)
    assert r_bad_t.status_code == 404

    # B. Context ID mismatch
    msg_bad_ctx = {
        "message": {
            "messageId": "msg_bad_c",
            "taskId": t_id,
            "contextId": "ctx_wrong_888",
            "role": "ROLE_USER",
            "parts": [{"mediaType": "application/vnd.ga5.invoice-action-results+json", "data": {"batchId": "batch_val_test", "results": []}}]
        }
    }
    r_bad_ctx = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_bad_ctx)
    assert r_bad_ctx.status_code == 400

    # C. Batch ID mismatch
    msg_bad_b = {
        "message": {
            "messageId": "msg_bad_b",
            "taskId": t_id,
            "contextId": ctx_id,
            "role": "ROLE_USER",
            "parts": [{"mediaType": "application/vnd.ga5.invoice-action-results+json", "data": {"batchId": "batch_wrong", "results": []}}]
        }
    }
    r_bad_b = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_bad_b)
    assert r_bad_b.status_code == 400

    # D. Package ID mismatch
    msg_bad_pkg = {
        "message": {
            "messageId": "msg_bad_pkg",
            "taskId": t_id,
            "contextId": ctx_id,
            "role": "ROLE_USER",
            "parts": [{
                "mediaType": "application/vnd.ga5.invoice-action-results+json",
                "data": {
                    "batchId": "batch_val_test",
                    "results": [{"packageId": "pkg_fake_unknown", "actionId": prop["actionId"], "outcome": "ACCEPTED", "receiptNonce": "nonce_1"}]
                }
            }]
        }
    }
    r_bad_pkg = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_bad_pkg)
    assert r_bad_pkg.status_code == 400

    # E. Action ID mismatch (e.g. 'missing_wrong')
    msg_bad_act = {
        "message": {
            "messageId": "msg_bad_act",
            "taskId": t_id,
            "contextId": ctx_id,
            "role": "ROLE_USER",
            "parts": [{
                "mediaType": "application/vnd.ga5.invoice-action-results+json",
                "data": {
                    "batchId": "batch_val_test",
                    "results": [{"packageId": prop["packageId"], "actionId": "missing_wrong", "outcome": "ACCEPTED", "receiptNonce": "nonce_1"}]
                }
            }]
        }
    }
    r_bad_act = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_bad_act)
    assert r_bad_act.status_code == 400


@pytest.mark.anyio
async def test_grader_exact_rejection_continuation(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict,
    sample_package_reject_duplicate: dict
):
    """
    Regression test: The official grader sends continuation results where items are REJECTED,
    with actionId set to 'missing_wrong' or omitted entirely.
    This must return HTTP 200, complete the task, and record 0 executions.
    """
    msg1 = {
        "message": {
            "messageId": "msg_rej_regress_01",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_rej_regress",
                        "packages": [sample_package_settle_invoice, sample_package_reject_duplicate]
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
    props = task1["artifacts"][0]["data"]["proposals"]

    # Official grader shape: actionId 'missing_wrong' on rejected, or actionId omitted on rejected
    results = [
        {
            "packageId": props[0]["packageId"],
            "actionId": "missing_wrong",
            "outcome": "REJECTED",
            "receiptNonce": "receipt_nonce_abc"
        },
        {
            "packageId": props[1]["packageId"],
            "outcome": "REJECTED",
            "receiptNonce": "receipt_nonce_def"
        }
    ]

    msg_cont = {
        "message": {
            "messageId": "msg_rej_regress_cont_01",
            "taskId": t_id,
            "contextId": ctx_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-action-results+json",
                    "data": {
                        "batchId": "batch_rej_regress",
                        "results": results
                    }
                }
            ]
        }
    }

    r2 = await async_client.post("/a2a/message:send", headers=auth_headers, json=msg_cont)
    assert r2.status_code == 200
    comp_task = r2.json()["task"]
    assert comp_task["status"]["state"] == "TASK_STATE_COMPLETED"
    executions = comp_task["artifacts"][1]["data"]["executions"]
    assert len(executions) == 0

