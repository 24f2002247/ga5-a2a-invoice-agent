import json
from typing import Dict, Any, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas import TaskState
from app.models import TaskRecord
from app.repository import TaskRepository


def get_task_by_id(principal: str, task_id: str, db: Session) -> Dict[str, Any]:
    repo = TaskRepository(db)
    record = repo.get_task(principal, task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    task_dict = json.loads(record.task_json)
    return {"task": task_dict, **task_dict}


def list_user_tasks(principal: str, db: Session) -> Dict[str, Any]:
    repo = TaskRepository(db)
    records = repo.list_tasks(principal)
    tasks = [json.loads(r.task_json) for r in records]
    return {"tasks": tasks}


def cancel_task_by_id(principal: str, task_id: str, db: Session) -> Dict[str, Any]:
    repo = TaskRepository(db)
    record = repo.get_task(principal, task_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    if record.state in (TaskState.COMPLETED.value, TaskState.CANCELED.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TASK_ALREADY_TERMINAL: Cannot cancel terminal task"
        )

    task_dict = json.loads(record.task_json)
    task_dict["status"] = {
        "state": TaskState.CANCELED.value,
        "message": "Task canceled by user"
    }

    # Atomically cancel in database
    success = repo.atomic_cancel_task(principal, task_id, json.dumps(task_dict))
    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TASK_ALREADY_TERMINAL: Task completed or canceled concurrently"
        )

    return {"task": task_dict, **task_dict}
