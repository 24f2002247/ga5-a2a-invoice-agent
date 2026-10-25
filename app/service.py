import uuid
import json
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas import (
    SendMessageRequest,
    TaskModel,
    TaskStatus,
    TaskState,
    ProposalBatchData,
    ReceiptBatchData,
    ExecutionItem
)
from app.models import TaskRecord, MessageRecord
from app.repository import TaskRepository
from app.idempotency import get_canonical_hash, in_flight_manager
from app.decision_engine import decide_invoice_packages


async def handle_message_send(
    request_data: SendMessageRequest,
    raw_message_dict: Dict[str, Any],
    principal: str,
    db: Session
) -> Dict[str, Any]:
    """
    Main handler for POST /a2a/message:send.
    Handles deduplication, semantic hashing, initial batch proposals, and result continuations.
    """
    msg = request_data.message
    msg_id = msg.messageId

    # Semantic hash ignores configuration and hashes key-sorted compact JSON of message only
    msg_hash = get_canonical_hash(raw_message_dict)

    repo = TaskRepository(db)

    # 1. Acquire concurrency lock for (principal, messageId)
    lock = await in_flight_manager.get_lock(principal, msg_id)
    async with lock:
        # Check idempotency in database
        existing_msg = repo.get_message(principal, msg_id)
        if existing_msg:
            if existing_msg.message_hash != msg_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="IDEMPOTENCY_CONFLICT: Message ID previously used with different content"
                )
            # Replay: return the stored response
            stored_resp = json.loads(existing_msg.response_json)
            # Also fetch latest task state to ensure fresh state if completed
            latest_task = repo.get_task(principal, existing_msg.task_id)
            if latest_task:
                return {"task": json.loads(latest_task.task_json)}
            return stored_resp

        # Process the incoming message part
        parts = raw_message_dict.get("parts", [])
        if not parts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incoming message has no parts"
            )

        part0 = parts[0]
        media_type = part0.get("mediaType", "")

        # -------------------------------------------------------------
        # INITIAL INVOICE CLAIM BATCH
        # -------------------------------------------------------------
        if media_type == "application/vnd.ga5.invoice-claim-batch+json":
            batch_data = part0.get("data", {})
            batch_id = batch_data.get("batchId") or f"batch_{uuid.uuid4().hex[:8]}"
            policy_rev = batch_data.get("policyRevision", "rev-1")
            packages = batch_data.get("packages", [])

            if not packages:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Claim batch must contain at least one package"
                )

            task_id = f"task_{uuid.uuid4().hex[:16]}"
            context_id = f"ctx_{uuid.uuid4().hex[:16]}"

            # AI invoice decisions with canonical package caching
            proposals = await decide_invoice_packages(packages, policy_rev, repo)

            # Strict Pydantic validation of proposals batch with graceful serialization
            try:
                proposal_batch = ProposalBatchData(
                    batchId=batch_id,
                    proposals=proposals
                )
                proposals_data = proposal_batch.model_dump()
            except Exception:
                proposals_data = {
                    "batchId": batch_id,
                    "proposals": [p.model_dump() for p in proposals]
                }

            proposal_artifact = {
                "mediaType": "application/vnd.ga5.invoice-action-proposals+json",
                "data": proposals_data
            }

            task_dict = {
                "id": task_id,
                "contextId": context_id,
                "status": {
                    "state": TaskState.INPUT_REQUIRED.value,
                    "message": "Invoice proposals awaiting review"
                },
                "history": [raw_message_dict],
                "artifacts": [proposal_artifact]
            }

            task_json = json.dumps(task_dict)
            response_json = json.dumps({"task": task_dict})

            task_record = TaskRecord(
                task_id=task_id,
                context_id=context_id,
                bearer_token=principal,
                batch_id=batch_id,
                state=TaskState.INPUT_REQUIRED.value,
                task_json=task_json
            )

            msg_record = MessageRecord(
                bearer_token=principal,
                message_id=msg_id,
                message_hash=msg_hash,
                task_id=task_id,
                response_json=response_json
            )

            repo.save_new_task_and_message(task_record, msg_record)
            return {"task": task_dict}

        # -------------------------------------------------------------
        # CONTINUATION RESULTS BATCH
        # -------------------------------------------------------------
        elif media_type == "application/vnd.ga5.invoice-action-results+json":
            req_task_id = raw_message_dict.get("taskId")
            req_context_id = raw_message_dict.get("contextId")

            if not req_task_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Continuation message must include taskId"
                )

            task_record = repo.get_task(principal, req_task_id)
            if not task_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Task not found"
                )

            # Validate context ID
            if req_context_id and task_record.context_id != req_context_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Context ID mismatch"
                )

            task_dict = json.loads(task_record.task_json)

            # Locate stored proposal artifact
            proposal_art = None
            for art in task_dict.get("artifacts", []):
                if art.get("mediaType") == "application/vnd.ga5.invoice-action-proposals+json":
                    proposal_art = art
                    break

            if not proposal_art:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Stored task has no invoice proposal artifact"
                )

            stored_batch_id = proposal_art["data"].get("batchId") or task_record.batch_id
            results_data = part0.get("data", {})
            cont_batch_id = results_data.get("batchId")

            if not cont_batch_id or cont_batch_id != stored_batch_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Batch ID mismatch: expected {stored_batch_id}, got {cont_batch_id}"
                )

            # Step 19: Post-cancellation continuation returns 409
            if task_record.state == TaskState.CANCELED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="TASK_CANCELED: Cannot continue a canceled task"
                )

            stored_proposals = {p["packageId"]: p for p in proposal_art["data"].get("proposals", [])}
            results_list = results_data.get("results", [])

            if not results_list:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Continuation message must include results array"
                )

            executions = []
            for res in results_list:
                pkg_id = res.get("packageId")
                if not pkg_id or pkg_id not in stored_proposals:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown or missing packageId: {pkg_id}"
                    )

                stored_prop = stored_proposals[pkg_id]
                outcome = res.get("outcome")
                if outcome not in ("ACCEPTED", "REJECTED"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid outcome for package {pkg_id}: {outcome}"
                    )

                # Validate actionId if present (Step 13: actionId mismatch returns 400)
                res_action_id = res.get("actionId")
                if res_action_id and res_action_id != stored_prop["actionId"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Action ID mismatch for package {pkg_id}: expected {stored_prop['actionId']}, got {res_action_id}"
                    )

                # Validate action if present (Step 14: action mismatch returns 400)
                res_action = res.get("action")
                if res_action and res_action != stored_prop["action"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Action mismatch for package {pkg_id}: expected {stored_prop['action']}, got {res_action}"
                    )

                # For ACCEPTED proposals, actionId and receiptNonce must be valid
                if outcome == "ACCEPTED":
                    if not res_action_id or res_action_id != stored_prop["actionId"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Missing or invalid actionId for accepted package {pkg_id}"
                        )
                    nonce = res.get("receiptNonce")
                    if not nonce:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Missing receiptNonce for accepted package {pkg_id}"
                        )
                    executions.append({
                        "packageId": pkg_id,
                        "actionId": stored_prop["actionId"],
                        "action": stored_prop["action"],
                        "receiptNonce": nonce,
                        "facts": stored_prop["facts"],
                        "evidenceRefs": stored_prop["evidenceRefs"]
                    })

            # Step 16: Terminal Task replay. After completed, replaying valid continuation returns completed task (200 OK)
            if task_record.state == TaskState.COMPLETED.value:
                resp_obj = {"task": task_dict}
                msg_rec = MessageRecord(
                    bearer_token=principal,
                    message_id=msg_id,
                    message_hash=msg_hash,
                    task_id=req_task_id,
                    response_json=json.dumps(resp_obj)
                )
                repo.save_message(msg_rec)
                return resp_obj

            # Create receipts artifact preserving proposals
            receipts_artifact = {
                "mediaType": "application/vnd.ga5.invoice-action-receipts+json",
                "data": {
                    "batchId": stored_batch_id,
                    "executions": executions
                }
            }

            task_dict["status"] = {
                "state": TaskState.COMPLETED.value,
                "message": "Invoice task completed with receipts"
            }
            task_dict["history"].append(raw_message_dict)
            task_dict["artifacts"].append(receipts_artifact)

            task_json = json.dumps(task_dict)
            response_json = json.dumps({"task": task_dict})

            msg_record = MessageRecord(
                bearer_token=principal,
                message_id=msg_id,
                message_hash=msg_hash,
                task_id=req_task_id,
                response_json=response_json
            )

            # Atomic database transition
            success = repo.atomic_complete_task(
                principal=principal,
                task_id=req_task_id,
                updated_task_json=task_json,
                continuation_msg=msg_record
            )
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="TASK_ALREADY_TERMINAL: Task was canceled or completed concurrently"
                )

            return {"task": task_dict}

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported part mediaType: {media_type}"
            )
