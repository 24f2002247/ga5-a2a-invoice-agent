from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class TaskRecord(Base):
    __tablename__ = "a2a_tasks"

    task_id = Column(String(64), primary_key=True, index=True)
    context_id = Column(String(64), nullable=False, index=True)
    bearer_token = Column(String(256), nullable=False, index=True)
    batch_id = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False, index=True)
    task_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class MessageRecord(Base):
    __tablename__ = "a2a_messages"

    bearer_token = Column(String(256), primary_key=True)
    message_id = Column(String(128), primary_key=True)
    message_hash = Column(String(64), nullable=False)
    task_id = Column(String(64), nullable=False, index=True)
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("bearer_token", "message_id", name="uq_principal_message"),
    )


class DecisionCacheRecord(Base):
    __tablename__ = "a2a_decision_cache"

    canonical_content_hash = Column(String(64), primary_key=True)
    action = Column(String(32), nullable=False)
    action_id = Column(String(64), nullable=False)
    facts_json = Column(Text, nullable=False)
    evidence_refs_json = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
