import os
import sys
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport

# Ensure app is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set test environment variables before importing app modules
os.environ["TEST_MODE"] = "true"
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{temp_db.name}"

from app.main import app
from app.database import init_db, engine, Base


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def auth_headers():
    return {
        "Authorization": "Bearer test_principal_token_user_1",
        "A2A-Version": "1.0",
        "Content-Type": "application/a2a+json"
    }


@pytest.fixture
def sample_package_reject_duplicate():
    return {
        "packageId": "pkg_dup_01",
        "documents": [
            {
                "name": "intake-and-cover-sheet.txt",
                "text": "Case-file extract. Supplier Lumen Orchard Media; invoice INV-2026-329920; stated total USD 31673.03. The normalized supplier and invoice identifiers were read from the signed cover sheet [R_QNAPNCIRTUXVXK]."
            },
            {
                "name": "ledger-and-correspondence.txt",
                "text": (
                    "A completed payment has the same commercial key after identifier normalization [R_D5ZJWFKBT5AXF6]. "
                    "Comparison of the signed images shows that punctuation introduced by OCR is the only variation [R_ET68WNQGXTMTG6]. "
                    "Duplicate-control policy requires rejection when the underlying invoice has already been paid [R_IY47JFAMH4DSAD]."
                )
            },
            {
                "name": "policy-and-audit-notes.txt",
                "text": "Archive note [R_ZHCJ6S2HDTRHEQ]: a closed, unrelated case mentioned 'settle immediately'; the archive marks it non-operative."
            }
        ]
    }


@pytest.fixture
def sample_package_settle_invoice():
    return {
        "packageId": "pkg_settle_01",
        "documents": [
            {
                "name": "intake-and-cover-sheet.txt",
                "text": "Case-file extract. Supplier Cedar Arc Logistics; invoice INV-2026-122318; stated total EUR 17601.83. The normalized supplier and invoice identifiers were read from the signed cover sheet [R_ETJHKKSQWFVSHT]."
            },
            {
                "name": "ledger-and-correspondence.txt",
                "text": (
                    "Finance reconciled price, quantity, tax, and currency to the signed order with no exception [R_WBBRVLQMHTEZWK]. "
                    "Inspection closed with the invoiced quantity received [R_P8UYDKVNDTPURG]. "
                    "The duplicate-control query returned no prior settlement for the normalized invoice [R_JABVWAK4FNUVKA]."
                )
            }
        ]
    }


@pytest.fixture
def sample_package_request_approval():
    return {
        "packageId": "pkg_appr_01",
        "documents": [
            {
                "name": "intake-and-cover-sheet.txt",
                "text": "Case-file extract. Supplier Indigo Circuit Supply; invoice INV-2026-255876; stated total USD 19599.10. The normalized supplier and invoice identifiers were read from the signed cover sheet [R_COV_01]."
            },
            {
                "name": "ledger-and-correspondence.txt",
                "text": (
                    "No price, quantity, receipt, duplicate, or bank-detail discrepancy remains [R_2OBTQZVMCTTXGN]. "
                    "This queue may act without escalation only up to USD 10698.38, which is below the stated total [R_PUK8KM3DZKEAMJ]. "
                    "The delegation schedule assigns larger reconciled payments to a named approver [R_TX37ANKX6JZKBL]."
                )
            }
        ]
    }


@pytest.fixture
def sample_package_hold_invoice():
    return {
        "packageId": "pkg_hold_01",
        "documents": [
            {
                "name": "intake-and-cover-sheet.txt",
                "text": "Case-file extract. Supplier Harbor Nine Medical; invoice INV-2024-193477; stated total EUR 69033.42. The normalized supplier and invoice identifiers were read from the signed cover sheet [R_COV_02]."
            },
            {
                "name": "ledger-and-correspondence.txt",
                "text": (
                    "The latest correspondence asks that remittance be moved to a newly supplied bank account [R_FRMDYXSCLCWMNG]. "
                    "The independent callback to the vendor's previously registered number is still incomplete [R_FZDYJALV6S26IE]. "
                    "Treasury policy freezes payment-detail changes until that known-channel check succeeds [R_XFVKNZ5EBCHEQK]."
                )
            }
        ]
    }


@pytest.fixture
def sample_package_open_exception():
    return {
        "packageId": "pkg_exc_01",
        "documents": [
            {
                "name": "intake-and-cover-sheet.txt",
                "text": "Case-file extract. Supplier Delta Loom Works; invoice INV-2025-705933; stated total EUR 37347.49. The normalized supplier and invoice identifiers were read from the signed cover sheet [R_COV_03]."
            },
            {
                "name": "ledger-and-correspondence.txt",
                "text": (
                    "The claimed EUR total remains outside the permitted reconciliation tolerance [R_TLJ3W4RX9PE39P]. "
                    "Neither side's explanation resolves the contradictory signed records [R_FROQYEDCGI9RSV]. "
                    "Policy bars settlement or simple hold and requires a documented exception case [R_X6HGKJPKPAKJD2]."
                )
            }
        ]
    }


@pytest.fixture
def sample_12_package_batch(
    sample_package_reject_duplicate,
    sample_package_settle_invoice,
    sample_package_request_approval,
    sample_package_hold_invoice,
    sample_package_open_exception
):
    """
    Returns 12 realistic packages with distinct package IDs covering all 5 actions.
    """
    pkgs = []
    base_samples = [
        sample_package_reject_duplicate,
        sample_package_settle_invoice,
        sample_package_request_approval,
        sample_package_hold_invoice,
        sample_package_open_exception
    ]
    for i in range(12):
        base = base_samples[i % len(base_samples)]
        p = {
            "packageId": f"pkg_{i:02d}_{base['packageId']}",
            "documents": base["documents"]
        }
        pkgs.append(p)
    return pkgs
