import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_agent_card_schema_and_url(async_client: AsyncClient):
    response = await async_client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/json")

    data = response.json()

    # Nonempty name, description, and version
    assert data.get("name") and isinstance(data["name"], str)
    assert data.get("description") and isinstance(data["description"], str)
    assert data.get("version") and isinstance(data["version"], str)

    # Object-valued capabilities
    assert isinstance(data.get("capabilities"), dict)

    # invoice_action_agent skill
    skills = data.get("skills", [])
    assert len(skills) >= 1
    skill = next((s for s in skills if s.get("id") == "invoice_action_agent"), None)
    assert skill is not None
    assert skill.get("name")
    assert skill.get("description")
    assert isinstance(skill.get("tags"), list)
    assert len(skill["tags"]) > 0

    # supportedInterfaces
    interfaces = data.get("supportedInterfaces", [])
    assert len(interfaces) >= 1
    iface = interfaces[0]
    assert iface.get("protocolBinding") == "HTTP+JSON"
    assert iface.get("protocolVersion") == "1.0"
    assert iface.get("url", "").endswith("/a2a")

    # defaultInputModes and defaultOutputModes
    assert "application/vnd.ga5.invoice-claim-batch+json" in data.get("defaultInputModes", [])
    out_modes = data.get("defaultOutputModes", [])
    assert "application/vnd.ga5.invoice-action-proposals+json" in out_modes
    assert "application/vnd.ga5.invoice-action-receipts+json" in out_modes
