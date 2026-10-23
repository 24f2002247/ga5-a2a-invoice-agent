from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class ActionType(str, Enum):
    SETTLE_INVOICE = "settle_invoice"
    REQUEST_APPROVAL = "request_approval"
    HOLD_INVOICE = "hold_invoice"
    REJECT_DUPLICATE = "reject_duplicate"
    OPEN_EXCEPTION = "open_exception"


class TaskState(str, Enum):
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    COMPLETED = "TASK_STATE_COMPLETED"
    CANCELED = "TASK_STATE_CANCELED"


class RoleType(str, Enum):
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


class ProposalFacts(BaseModel):
    vendorName: str = Field(..., min_length=1, description="Supplier or vendor name")
    invoiceNumber: str = Field(..., min_length=1, description="Invoice identifier")
    amountMinor: int = Field(..., ge=0, description="Amount in minor currency units (cents/paise)")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")


class InvoiceProposal(BaseModel):
    packageId: str = Field(..., min_length=1)
    actionId: str = Field(..., min_length=12, description="Durable unique action identifier")
    action: ActionType
    facts: ProposalFacts
    evidenceRefs: List[str] = Field(..., min_length=3, max_length=3, description="Exactly 3 decisive evidence references")
    rationale: str = Field(..., min_length=60, max_length=1500, description="60-1500 chars rationale mentioning action and 2 refs")

    @model_validator(mode="after")
    def validate_rationale_contents(self):
        action_val = self.action.value if isinstance(self.action, ActionType) else str(self.action)
        if action_val not in self.rationale:
            raise ValueError(f"Rationale must explicitly mention action '{action_val}'")
        
        # Check that at least two evidence references are cited in the rationale
        cited_count = sum(1 for ref in self.evidenceRefs if ref in self.rationale or ref.strip("[]") in self.rationale)
        if cited_count < 2:
            raise ValueError(f"Rationale must cite at least two evidence references from {self.evidenceRefs}")
        return self


class ProposalBatchData(BaseModel):
    batchId: str = Field(..., min_length=1)
    proposals: List[InvoiceProposal]

    @field_validator("proposals")
    @classmethod
    def validate_unique_ids(cls, v: List[InvoiceProposal]):
        pkg_ids = set()
        act_ids = set()
        for p in v:
            if p.packageId in pkg_ids:
                raise ValueError(f"Duplicate packageId in batch: {p.packageId}")
            if p.actionId in act_ids:
                raise ValueError(f"Duplicate actionId in batch: {p.actionId}")
            pkg_ids.add(p.packageId)
            act_ids.add(p.actionId)
        return v


class ExecutionItem(BaseModel):
    packageId: str
    actionId: str
    action: ActionType
    receiptNonce: str
    facts: ProposalFacts
    evidenceRefs: List[str]


class ReceiptBatchData(BaseModel):
    batchId: str
    executions: List[ExecutionItem]


class ArtifactPart(BaseModel):
    mediaType: str
    data: Dict[str, Any]


class TaskStatus(BaseModel):
    state: TaskState
    message: Optional[str] = None


class TaskModel(BaseModel):
    id: str
    contextId: str
    status: TaskStatus
    history: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)


class MessagePart(BaseModel):
    mediaType: str
    data: Dict[str, Any]


class IncomingMessage(BaseModel):
    messageId: str = Field(..., min_length=1)
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    role: str = "ROLE_USER"
    parts: List[MessagePart] = Field(..., min_length=1)


class SendMessageRequest(BaseModel):
    message: IncomingMessage
    configuration: Optional[Dict[str, Any]] = None


class ContinuationResultItem(BaseModel):
    packageId: str
    actionId: Optional[str] = None
    action: Optional[str] = None
    outcome: str
    receiptNonce: Optional[str] = None
