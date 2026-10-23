from typing import Dict, Any
from app.config import settings


def get_agent_card(base_url_override: str = "") -> Dict[str, Any]:
    url = base_url_override.strip() if base_url_override else settings.normalized_public_base_url
    if not url.endswith("/a2a"):
        url = f"{url.rstrip('/')}/a2a"

    return {
        "name": "A2A Invoice Agent",
        "description": "Autonomous evidence-based invoice auditor and durable settlement agent under A2A 1.0",
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "batchProcessing": True,
            "idempotency": True
        },
        "skills": [
            {
                "id": "invoice_action_agent",
                "name": "invoice_action_agent",
                "description": "Audits invoice packages, proposes safe actions, and executes verified receipts",
                "tags": ["finance", "invoice", "audit", "a2a"]
            }
        ],
        "supportedInterfaces": [
            {
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
                "url": url
            }
        ],
        "defaultInputModes": [
            "application/vnd.ga5.invoice-claim-batch+json"
        ],
        "defaultOutputModes": [
            "application/vnd.ga5.invoice-action-proposals+json",
            "application/vnd.ga5.invoice-action-receipts+json"
        ]
    }
