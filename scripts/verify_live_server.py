import sys
import requests
import json
import sqlite3

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8030"
HEADERS = {
    "Authorization": "Bearer verify_live_principal_001",
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
        "messageId": "live_msg_001",
        "role": "ROLE_USER",
        "parts": [
            {
                "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                "data": {
                    "batchId": "batch_live_12",
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
proposals = task["artifacts"][0]["data"]["proposals"]
print(f"Initial Propose 200 OK: Task ID={task_id}, State={task['status']['state']}")
print(f"Total proposals returned: {len(proposals)}")
for i, p in enumerate(proposals):
    print(f"  [{i:02d}] {p['packageId']}: {p['action']:<18} | {p['facts']['currency']} {p['facts']['amountMinor']} | Refs: {p['evidenceRefs']}")

print("\n=== 3. Idempotent Replay of Initial Request ===")
r_replay = requests.post(f"{BASE_URL}/a2a/message:send", headers=HEADERS, json=msg_batch)
assert r_replay.status_code == 200
assert r_replay.json()["task"]["id"] == task_id
print("Replay 200 OK: returned same task!")

print("\n=== 4. Idempotency Conflict (Reused messageId with changed payload) ===")
msg_conflict = {
    "message": {
        "messageId": "live_msg_001",
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
        "messageId": "live_msg_cont_001",
        "taskId": task_id,
        "contextId": ctx_id,
        "role": "ROLE_USER",
        "parts": [
            {
                "mediaType": "application/vnd.ga5.invoice-action-results+json",
                "data": {
                    "batchId": "batch_live_12",
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

print("\n=== ALL LIVE SERVER INTEGRATION CHECKS PASSED PERFECTLY ===")
