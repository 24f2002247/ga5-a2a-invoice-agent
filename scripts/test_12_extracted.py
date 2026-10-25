import sys
sys.path.insert(0, r'C:\Users\Jayraj\.gemini\antigravity\scratch\ga5-q2-a2a-invoice-agent')
import sqlite3, json
from app.decision_engine import extract_package_facts_and_evidence, build_proposal_from_facts
from app.idempotency import get_canonical_hash

conn = sqlite3.connect(r'C:\Users\Jayraj\.gemini\antigravity\scratch\tds-ga3\ga3_state.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT task_json FROM a2a_tasks WHERE task_id = 'task_dafa6ba20170'")
row = c.fetchone()
d = json.loads(row['task_json'])
packages = d['history'][0]['parts'][0]['data']['packages']
for idx, pkg in enumerate(packages):
    pkg_id = pkg.get('packageId')
    pkg_hash = get_canonical_hash(pkg)
    facts, refs, action, decisive_para = extract_package_facts_and_evidence(pkg)
    prop = build_proposal_from_facts(pkg_id, pkg_hash, facts, refs, action, decisive_para)
    print(f"=== PKG {idx}: {pkg_id} ===")
    print("Action:", prop.action.value)
    print("EvidenceRefs:", prop.evidenceRefs)
    print("Facts:", prop.facts.model_dump())
    print("Rationale:", prop.rationale)
