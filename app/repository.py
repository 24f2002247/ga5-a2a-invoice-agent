import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, update, insert
from sqlalchemy.exc import IntegrityError

from app.models import TaskRecord, MessageRecord, DecisionCacheRecord


class TaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_message(self, principal: str, message_id: str) -> Optional[MessageRecord]:
        stmt = select(MessageRecord).where(
            MessageRecord.bearer_token == principal,
            MessageRecord.message_id == message_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_task(self, principal: str, task_id: str) -> Optional[TaskRecord]:
        stmt = select(TaskRecord).where(
            TaskRecord.bearer_token == principal,
            TaskRecord.task_id == task_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_tasks(self, principal: str) -> List[TaskRecord]:
        stmt = select(TaskRecord).where(
            TaskRecord.bearer_token == principal
        ).order_by(TaskRecord.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def save_new_task_and_message(self, task_record: TaskRecord, message_record: MessageRecord):
        """
        Atomically persists new task and idempotency message record.
        """
        try:
            self.db.add(task_record)
            self.db.add(message_record)
            self.db.commit()
            self.db.refresh(task_record)
        except IntegrityError:
            self.db.rollback()
            raise

    def atomic_complete_task(
        self,
        principal: str,
        task_id: str,
        updated_task_json: str,
        continuation_msg: MessageRecord
    ) -> bool:
        """
        Atomically transitions task from TASK_STATE_INPUT_REQUIRED to TASK_STATE_COMPLETED.
        If another operation (like cancellation) transitioned the task first, rowcount will be 0.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            update(TaskRecord)
            .where(
                TaskRecord.task_id == task_id,
                TaskRecord.bearer_token == principal,
                TaskRecord.state == "TASK_STATE_INPUT_REQUIRED"
            )
            .values(
                state="TASK_STATE_COMPLETED",
                task_json=updated_task_json,
                updated_at=now
            )
        )
        result = self.db.execute(stmt)
        if result.rowcount == 0:
            self.db.rollback()
            return False

        # Add continuation message record
        self.db.add(continuation_msg)
        self.db.commit()
        return True

    def atomic_cancel_task(
        self,
        principal: str,
        task_id: str,
        updated_task_json: str
    ) -> bool:
        """
        Atomically transitions task from TASK_STATE_INPUT_REQUIRED to TASK_STATE_CANCELED.
        Returns True if won the race, False if already in a terminal state or not found.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            update(TaskRecord)
            .where(
                TaskRecord.task_id == task_id,
                TaskRecord.bearer_token == principal,
                TaskRecord.state == "TASK_STATE_INPUT_REQUIRED"
            )
            .values(
                state="TASK_STATE_CANCELED",
                task_json=updated_task_json,
                updated_at=now
            )
        )
        result = self.db.execute(stmt)
        if result.rowcount == 0:
            self.db.rollback()
            return False

        self.db.commit()
        return True

    def save_message(self, message_record: MessageRecord):
        """
        Saves a message record for idempotency deduplication.
        Silently ignores duplicate primary/unique keys.
        """
        try:
            self.db.add(message_record)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
        except Exception:
            self.db.rollback()

    def get_cached_decision(self, canonical_content_hash: str) -> Optional[DecisionCacheRecord]:
        stmt = select(DecisionCacheRecord).where(
            DecisionCacheRecord.canonical_content_hash == canonical_content_hash
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def save_cached_decision(
        self,
        canonical_content_hash: str,
        action: str,
        action_id: str,
        facts_json: str,
        evidence_refs_json: str,
        rationale: str
    ):
        try:
            record = DecisionCacheRecord(
                canonical_content_hash=canonical_content_hash,
                action=action,
                action_id=action_id,
                facts_json=facts_json,
                evidence_refs_json=evidence_refs_json,
                rationale=rationale
            )
            self.db.merge(record)
            self.db.commit()
        except Exception:
            self.db.rollback()
