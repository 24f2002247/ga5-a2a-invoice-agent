import sqlite3
import json
import uuid
import httpx

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
d = json.loads(row[0])
packages = d['history'][0]['parts'][0]['data']['packages']

fresh_id = f"fresh_{uuid.uuid4().hex[:8]}"
fresh_principal = f"bearer_{uuid.uuid4().hex[:8]}"
headers = {
    'Authorization': f'Bearer {fresh_principal}',
    'A2A-Version': '1.0',
    'Content-Type': 'application/a2a+json'
}

# 1. Send claim batch
msg_init = {
    'message': {
        'messageId': fresh_id,
        'role': 'ROLE_USER',
        'parts': [{
            'mediaType': 'application/vnd.ga5.invoice-claim-batch+json',
            'data': {'batchId': f'batch_{fresh_id}', 'policyRevision': 'rev-2026', 'packages': packages}
        }]
    }
}
r1 = httpx.post('https://ga5-a2a-invoice-agent.onrender.com/a2a/message:send', json=msg_init, headers=headers, timeout=25)
assert r1.status_code == 200, f'Init failed: {r1.text}'
task = r1.json()['task']
t_id = task['id']
ctx_id = task['contextId']
props = task['artifacts'][0]['data']['proposals']

# 2. Test no-op empty results continuation
msg_noop = {
    'message': {
        'messageId': f'noop_{fresh_id}',
        'taskId': t_id,
        'contextId': ctx_id,
        'role': 'ROLE_USER',
        'parts': [{
            'mediaType': 'application/vnd.ga5.invoice-action-results+json',
            'data': {'batchId': f'batch_{fresh_id}', 'results': []}
        }]
    }
}
r_noop = httpx.post('https://ga5-a2a-invoice-agent.onrender.com/a2a/message:send', json=msg_noop, headers=headers, timeout=25)
assert r_noop.status_code == 200, f'Noop failed: {r_noop.text}'
task_noop = r_noop.json()['task']
assert task_noop['status']['state'] == 'TASK_STATE_INPUT_REQUIRED', f'State should remain INPUT_REQUIRED, got: {task_noop["status"]["state"]}'
print('Empty results no-op passed: state is TASK_STATE_INPUT_REQUIRED')

# 3. Send results continuation with accepted/rejected mix
results = []
for i, p in enumerate(props):
    outcome = 'ACCEPTED' if i % 2 == 0 else 'REJECTED'
    nonce = f'receipt_nonce_{uuid.uuid4().hex[:16]}' if outcome == 'ACCEPTED' else None
    results.append({
        'packageId': p['packageId'],
        'actionId': p['actionId'],
        'action': p['action'],
        'outcome': outcome,
        'receiptNonce': nonce
    })

msg_cont = {
    'message': {
        'messageId': f'cont_{fresh_id}',
        'taskId': t_id,
        'contextId': ctx_id,
        'role': 'ROLE_USER',
        'parts': [{
            'mediaType': 'application/vnd.ga5.invoice-action-results+json',
            'data': {'batchId': f'batch_{fresh_id}', 'results': results}
        }]
    }
}
r2 = httpx.post('https://ga5-a2a-invoice-agent.onrender.com/a2a/message:send', json=msg_cont, headers=headers, timeout=25)
assert r2.status_code == 200, f'Continuation failed: {r2.text}'
comp_task = r2.json()['task']
assert comp_task['status']['state'] == 'TASK_STATE_COMPLETED', f'Expected COMPLETED, got {comp_task["status"]["state"]}'
execs = comp_task['artifacts'][1]['data']['executions']
print(f'Continuation passed: state=COMPLETED, executions={len(execs)} (expected 6)')
print('First execution evidenceRefs:', execs[0]['evidenceRefs'])
