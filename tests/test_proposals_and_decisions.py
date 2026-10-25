import pytest
from httpx import AsyncClient
from unittest.mock import patch

from app.schemas import InvoiceProposal, ActionType


@pytest.mark.anyio
async def test_valid_initial_batch_returning_200(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_12_package_batch: list
):
    req_body = {
        "message": {
            "messageId": "msg_initial_12_pkg",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_test_12",
                        "policyRevision": "rev-2026-v1",
                        "packages": sample_12_package_batch
                    }
                }
            ]
        },
        "configuration": {
            "returnImmediately": False,
            "acceptedOutputModes": [
                "application/vnd.ga5.invoice-action-proposals+json",
                "application/vnd.ga5.invoice-action-receipts+json"
            ]
        }
    }

    resp = await async_client.post("/a2a/message:send", headers=auth_headers, json=req_body)
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/a2a+json")

    data = resp.json()
    assert "task" in data
    task = data["task"]

    # Verify task state is TASK_STATE_INPUT_REQUIRED
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"

    # Exactly one proposal artifact part
    artifacts = task.get("artifacts", [])
    assert len(artifacts) == 1
    proposal_art = artifacts[0]
    assert proposal_art["mediaType"] == "application/vnd.ga5.invoice-action-proposals+json"

    proposals = proposal_art["data"]["proposals"]
    assert len(proposals) == 12

    # Verify no receipt artifact is present in initial response
    for art in artifacts:
        assert art["mediaType"] != "application/vnd.ga5.invoice-action-receipts+json"


@pytest.mark.anyio
async def test_all_five_invoice_actions(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_reject_duplicate: dict,
    sample_package_settle_invoice: dict,
    sample_package_request_approval: dict,
    sample_package_hold_invoice: dict,
    sample_package_open_exception: dict
):
    packages = [
        sample_package_reject_duplicate,
        sample_package_settle_invoice,
        sample_package_request_approval,
        sample_package_hold_invoice,
        sample_package_open_exception
    ]

    req_body = {
        "message": {
            "messageId": "msg_five_actions",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_5_actions",
                        "packages": packages
                    }
                }
            ]
        }
    }

    resp = await async_client.post("/a2a/message:send", headers=auth_headers, json=req_body)
    assert resp.status_code == 200
    proposals = resp.json()["task"]["artifacts"][0]["data"]["proposals"]

    action_map = {p["packageId"]: p["action"] for p in proposals}
    assert action_map["pkg_dup_01"] == ActionType.REJECT_DUPLICATE.value
    assert action_map["pkg_settle_01"] == ActionType.SETTLE_INVOICE.value
    assert action_map["pkg_appr_01"] == ActionType.REQUEST_APPROVAL.value
    assert action_map["pkg_hold_01"] == ActionType.HOLD_INVOICE.value
    assert action_map["pkg_exc_01"] == ActionType.OPEN_EXCEPTION.value


@pytest.mark.anyio
async def test_evidence_extraction_and_rationale_validation(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_reject_duplicate: dict
):
    req_body = {
        "message": {
            "messageId": "msg_evidence_test",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_evid",
                        "packages": [sample_package_reject_duplicate]
                    }
                }
            ]
        }
    }

    resp = await async_client.post("/a2a/message:send", headers=auth_headers, json=req_body)
    assert resp.status_code == 200
    proposal = resp.json()["task"]["artifacts"][0]["data"]["proposals"][0]

    # Validate strict Pydantic model validation on output
    proposal_obj = InvoiceProposal(**proposal)

    # Durable unique actionId of at least 12 chars
    assert len(proposal_obj.actionId) >= 12

    # Exactly 3 decisive evidence references
    assert len(proposal_obj.evidenceRefs) == 3
    for ref in proposal_obj.evidenceRefs:
        assert ref.startswith("[R_") and ref.endswith("]")

    # Rationale 60 - 1500 chars
    assert 60 <= len(proposal_obj.rationale) <= 1500
    assert proposal_obj.action.value in proposal_obj.rationale

    # Facts accurately extracted from cover sheet
    assert proposal_obj.facts.vendorName == "Lumen Orchard Media"
    assert proposal_obj.facts.invoiceNumber == "INV-2026-329920"
    assert proposal_obj.facts.currency == "USD"
    assert proposal_obj.facts.amountMinor == 3167303


@pytest.mark.anyio
async def test_model_failure_graceful_fallback(
    async_client: AsyncClient,
    auth_headers: dict,
    sample_package_settle_invoice: dict
):
    # Simulate an AI model failure or network error
    req_body = {
        "message": {
            "messageId": "msg_fallback_test",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_fallback",
                        "packages": [sample_package_settle_invoice]
                    }
                }
            ]
        }
    }

    with patch("app.decision_engine.call_ai_model_batch", return_value=None):
        resp = await async_client.post("/a2a/message:send", headers=auth_headers, json=req_body)
        assert resp.status_code == 200
        proposals = resp.json()["task"]["artifacts"][0]["data"]["proposals"]
        assert len(proposals) == 1
        assert proposals[0]["action"] == "settle_invoice"


@pytest.mark.anyio
async def test_battery_minimal_package_and_malformed_resilience(
    async_client: AsyncClient,
    auth_headers: dict
):
    """
    Ensures that packages with no explicit citations or minimal structure return 200 OK
    without throwing unhandled 500 exceptions, and malformed bodies return 400.
    """
    # 1. Minimal package with no bracketed citations (battery protocol test scenario)
    minimal_pkg_msg = {
        "message": {
            "messageId": "msg_battery_minimal_001",
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_battery_min",
                        "packages": [
                            {
                                "packageId": "pkg_min_01",
                                "documents": [{"name": "doc1.txt", "text": "Minimal battery test text without citations."}]
                            },
                            {
                                "packageId": "pkg_min_02",
                                "documents": [{"name": "doc2.txt", "text": "Another test invoice without citations."}]
                            }
                        ]
                    }
                }
            ]
        }
    }
    resp = await async_client.post("/a2a/message:send", headers=auth_headers, json=minimal_pkg_msg)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    proposals = resp.json()["task"]["artifacts"][0]["data"]["proposals"]
    assert len(proposals) == 2
    for p in proposals:
        assert len(p["evidenceRefs"]) == 3
        assert len(p["actionId"]) >= 12
        assert 60 <= len(p["rationale"]) <= 1500
    # Ensure distinct action IDs
    assert proposals[0]["actionId"] != proposals[1]["actionId"]

    # 2. Schema malformed body (e.g. invalid message structure) must return 400 Bad Request, NOT 500
    bad_schema_msg = {
        "message": {
            "messageId": "msg_bad_schema",
            "role": "ROLE_USER",
            "parts": "not_a_list"
        }
    }
    resp_bad = await async_client.post("/a2a/message:send", headers=auth_headers, json=bad_schema_msg)
    assert resp_bad.status_code == 400
    assert "Invalid request schema" in resp_bad.text

