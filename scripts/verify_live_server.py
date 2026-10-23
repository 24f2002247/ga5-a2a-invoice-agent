import sys
import requests
import json
import sqlite3
import uuid

RUN_ID = uuid.uuid4().hex[:6]
BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8030"
HEADERS = {
    "Authorization": f"Bearer verify_principal_{RUN_ID}",
    "A2A-Version": "1.0",
    "Content-Type": "application/a2a+json"
}

print("=== 1. Health & Discovery ===")
r_health = requests.get(f"{BASE_URL}/healthz")
assert r_health.status_code == 200, f"Health check failed: {r_health.text}"
print("Health OK:", r_health.json())

r_card = requests.get(f"{BASE_URL}/.well-known/agent-card.json")
assert r_card.status_code == 200, f"Agent card failed: {r_card.text}"
card = r_card.json()
print(f"Agent Card OK: name='{card['name']}' url='{card['supportedInterfaces'][0]['url']}'")

print("\n=== 1b. Protocol Header & Auth Checks ===")
# Missing Bearer token on GET /tasks and GET /a2a/tasks must return 401 (LIST_AUTH_REQUIRED)
r_no_auth = requests.get(f"{BASE_URL}/tasks")
assert r_no_auth.status_code == 401, f"Expected 401 for /tasks without auth, got {r_no_auth.status_code}"
r_no_auth_a2a = requests.get(f"{BASE_URL}/a2a/tasks")
assert r_no_auth_a2a.status_code == 401, f"Expected 401 for /a2a/tasks without auth, got {r_no_auth_a2a.status_code}"
print("LIST_AUTH_REQUIRED OK: 401 Unauthorized returned when Bearer token is missing")

# Bad A2A-Version header must return 400
r_bad_ver = requests.get(f"{BASE_URL}/a2a/tasks", headers={"Authorization": HEADERS["Authorization"], "A2A-Version": "0.9"})
assert r_bad_ver.status_code == 400, f"Expected 400 for bad A2A-Version, got {r_bad_ver.status_code}"
print("Bad A2A-Version OK: 400 Bad Request returned")

# Bad Media-Type on message:send must return 415
r_bad_media = requests.post(f"{BASE_URL}/a2a/message:send", headers={"Authorization": HEADERS["Authorization"], "A2A-Version": "1.0", "Content-Type": "application/xml"}, json={})
assert r_bad_media.status_code == 415, f"Expected 415 for bad Content-Type, got {r_bad_media.status_code}"
print("Media Type Check OK: 415 Unsupported Media Type returned")

print("\n=== 2. Propose Real 12-Package Batch ===")
# Fetch real 12 packages or fallback to self-contained test packages
try:
    conn = sqlite3.connect(r"C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
    row = c.fetchone()
    conn.close()
    real_task = json.loads(row["task_json"])
    pkgs = real_task["history"][0]["parts"][0]["data"]["packages"]
except Exception:
    pkgs = [
        {
            "packageId": f"pkg_{i:02d}",
            "documents": [
                {
                    "name": "intake-and-cover-sheet.txt",
                    "text": f"Supplier Vendor {i}; invoice INV-2026-{1000+i}; stated total USD {5000+i*100}.00. Cover ref [R_COV_{i}]."
                },
                {
                    "name": "ledger-and-correspondence.txt",
                    "text": (
                        f"Finance reconciled price, quantity, tax [R_REF_{i}_1]. "
                        f"Inspection closed [R_REF_{i}_2]. "
                        f"The duplicate-control query returned no prior settlement [R_REF_{i}_3]."
                    )
                }
            ]
        }
        for i in range(12)
    ]

msg_batch = {
    "message": {
        "messageId": f"live_msg_{RUN_ID}_001",
        "role": "ROLE_USER",
        "parts": [
            {
                "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                "data": {
                    "batchId": f"batch_live_{RUN_ID}",
                    "policyRevision": "rev-live",
                    "packages": pkgs
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

r_propose = requests.post(f"{BASE_URL}/a2a/message:send", headers=HEADERS, json=msg_batch)
assert r_propose.status_code == 200, f"Initial batch failed: {r_propose.status_code} {r_propose.text}"
task = r_propose.json()["task"]
task_id = task["id"]
ctx_id = task["contextId"]
assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", f"Initial propose must be INPUT_REQUIRED, got {task['status']['state']}"
proposals = task["artifacts"][0]["data"]["proposals"]
print(f"Initial Propose 200 OK: Task ID={task_id}, State={task['status']['state']}")
print(f"Total proposals returned: {len(proposals)}")
for i, p in enumerate(proposals):
    print(f"  [{i:02d}] {p['packageId']}: {p['action']:<18} | {p['facts']['currency']} {p['facts']['amountMinor']} | Refs: {p['evidenceRefs']}")

# Verify GET /tasks/{task_id} returns the Task directly
r_read_input_req = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=HEADERS)
assert r_read_input_req.status_code == 200
read_task = r_read_input_req.json()
assert read_task["id"] == task_id
assert read_task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
assert "task" not in read_task, "Task object must not have a nested 'task' field"
print("GET /tasks/{id} OK: observed TASK_STATE_INPUT_REQUIRED before continuation")

print("\n=== 3. Idempotent Replay of Initial Request ===")
r_replay = requests.post(f"{BASE_URL}/a2a/message:send", headers=HEADERS, json=msg_batch)
assert r_replay.status_code == 200
assert r_replay.json()["task"]["id"] == task_id
print("Replay 200 OK: returned same task!")

print("\n=== 4. Idempotency Conflict (Reused messageId with changed payload) ===")
msg_conflict = {
    "message": {
        "messageId": f"live_msg_{RUN_ID}_001",
        "role": "ROLE_USER",
        "parts": [
            {
                "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                "data": {
                    "batchId": "batch_different_content",
                    "packages": pkgs[:1]
                }
            }
        ]
    }
}
r_conflict = requests.post(f"{BASE_URL}/a2a/message:send", headers=HEADERS, json=msg_conflict)
assert r_conflict.status_code == 409
assert "IDEMPOTENCY_CONFLICT" in r_conflict.text
print(f"Conflict 409 OK: {r_conflict.json()}")

print("\n=== 5. Result Continuation Execution ===")
results = []
for i, p in enumerate(proposals):
    outcome = "ACCEPTED" if i in (0, 1, 2, 4, 7, 10) else "REJECTED"
    nonce = f"nonce_{p['actionId']}" if outcome == "ACCEPTED" else None
    results.append({
        "packageId": p["packageId"],
        "actionId": p["actionId"],
        "action": p["action"],
        "outcome": outcome,
        "receiptNonce": nonce
    })

msg_cont = {
    "message": {
        "messageId": f"live_msg_cont_{RUN_ID}_001",
        "taskId": task_id,
        "contextId": ctx_id,
        "role": "ROLE_USER",
        "parts": [
            {
                "mediaType": "application/vnd.ga5.invoice-action-results+json",
                "data": {
                    "batchId": f"batch_live_{RUN_ID}",
                    "results": results
                }
            }
        ]
    }
}

r_cont = requests.post(f"{BASE_URL}/a2a/message:send", headers=HEADERS, json=msg_cont)
assert r_cont.status_code == 200, f"Continuation failed: {r_cont.status_code} {r_cont.text}"
comp_task = r_cont.json()["task"]
assert comp_task["status"]["state"] == "TASK_STATE_COMPLETED"
executions = comp_task["artifacts"][1]["data"]["executions"]
print(f"Continuation 200 OK: State={comp_task['status']['state']}, Executions={len(executions)}/6 accepted")

print("\n=== 6. User Isolation Check ===")
OTHER_HEADERS = {
    "Authorization": "Bearer principal_different_user",
    "A2A-Version": "1.0",
    "Content-Type": "application/a2a+json"
}
r_other_list = requests.get(f"{BASE_URL}/a2a/tasks", headers=OTHER_HEADERS)
assert r_other_list.status_code == 200
assert len(r_other_list.json()["tasks"]) == 0
print("User Isolation OK: Other principal sees 0 tasks")

r_other_get = requests.get(f"{BASE_URL}/a2a/tasks/{task_id}", headers=OTHER_HEADERS)
assert r_other_get.status_code == 404
print("User Isolation OK: Other principal cannot read User 1 task (404)")

print("\n=== 7. Terminal Task Replay & Post-Completion Lifecycle ===")
# A. Replay continuation with a new message ID (battery step 16)
msg_cont_replay = {
    "message": {
        "messageId": f"live_msg_cont_replay_new_{RUN_ID}_002",
        "taskId": task_id,
        "contextId": ctx_id,
        "role": "ROLE_USER",
        "parts": msg_cont["message"]["parts"]
    }
}
r_replay_new = requests.post(f"{BASE_URL}/a2a/message:send", headers=HEADERS, json=msg_cont_replay)
assert r_replay_new.status_code == 200, f"Step 16 replay failed: {r_replay_new.status_code} {r_replay_new.text}"
assert r_replay_new.json()["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
print("Terminal Replay with new messageId OK: 200 returned completed task")

# B. Post-completion cancel (battery step 18)
r_cancel_post = requests.post(f"{BASE_URL}/a2a/tasks/{task_id}:cancel", headers=HEADERS)
assert r_cancel_post.status_code == 409, f"Post-completion cancel should return 409: {r_cancel_post.status_code}"
print("Post-Completion Cancel OK: 409 returned")

# C. Invalid continuation on completed task (actionId mismatch) must return 400
bad_results = list(results)
bad_results[0] = dict(bad_results[0])
bad_results[0]["actionId"] = "wrong_action_id_invalid"
msg_bad_cont = {
    "message": {
        "messageId": f"live_msg_bad_cont_{RUN_ID}",
        "taskId": task_id,
        "contextId": ctx_id,
        "role": "ROLE_USER",
        "parts": [
            {
                "mediaType": "application/vnd.ga5.invoice-action-results+json",
                "data": {
                    "batchId": f"batch_live_{RUN_ID}",
                    "results": bad_results
                }
            }
        ]
    }
}
r_bad_cont = requests.post(f"{BASE_URL}/a2a/message:send", headers=HEADERS, json=msg_bad_cont)
assert r_bad_cont.status_code == 400, f"Expected 400 for bad continuation on completed task, got {r_bad_cont.status_code}"
print("INVALID_CONTINUATION_ACCEPTED Prevention OK: 400 returned for mismatched continuation")

print("\n=== ALL LIVE SERVER INTEGRATION CHECKS PASSED PERFECTLY ===")
