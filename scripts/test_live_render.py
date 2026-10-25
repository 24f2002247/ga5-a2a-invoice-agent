import sqlite3
import json
import httpx

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
d = json.loads(row[0])
packages = d['history'][0]['parts'][0]['data']['packages']

msg = {
    'message': {
        'messageId': 'test_debug_live_001',
        'role': 'ROLE_USER',
        'parts': [{
            'mediaType': 'application/vnd.ga5.invoice-claim-batch+json',
            'data': {
                'batchId': 'batch_debug_12',
                'policyRevision': 'rev-2026',
                'packages': packages
            }
        }]
    }
}
headers = {
    'Authorization': 'Bearer live_debug_token_123',
    'A2A-Version': '1.0',
    'Content-Type': 'application/a2a+json'
}
r = httpx.post('https://ga5-a2a-invoice-agent.onrender.com/a2a/message:send', json=msg, headers=headers, timeout=20)
print('Status:', r.status_code)
if r.status_code == 200:
    t = r.json().get('task', {})
    props = t.get('artifacts', [{}])[0].get('data', {}).get('proposals', [])
    print('Proposals count:', len(props))
    for p in props[:3]:
        print(p['packageId'], p['action'], p['evidenceRefs'], p['actionId'])
        print('  Rationale:', p['rationale'])
else:
    print('Error:', r.text)
