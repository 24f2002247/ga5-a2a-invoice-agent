import json
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

logger = logging.getLogger("a2a_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from app.config import settings
from app.database import init_db, get_db
from app.schemas import SendMessageRequest
from app.agent_card import get_agent_card
from app.auth import verify_a2a_auth, verify_a2a_content_type
from app.service import handle_message_send
from app.task_manager import get_task_by_id, list_user_tasks, cancel_task_by_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    init_db()
    yield


app = FastAPI(
    title="A2A Invoice Agent",
    description="Autonomous A2A 1.0 Invoice Auditor and Settlement Agent",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for open cross-origin agent communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def _is_a2a_path(path: str) -> bool:
    return path.startswith("/a2a") or path.startswith("/tasks") or path.startswith("/message")


@app.middleware("http")
async def add_a2a_response_headers(request: Request, call_next):
    response = await call_next(request)
    if _is_a2a_path(request.url.path):
        response.headers["A2A-Version"] = "1.0"
    return response


# Exception handler to return application/a2a+json for /a2a routes and avoid leaking secrets
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    is_a2a = _is_a2a_path(request.url.path)
    media_type = "application/a2a+json" if is_a2a else "application/json"
    detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    logger.warning(f"HTTP {exc.status_code} on {request.method} {request.url.path}: {detail_msg}")
    
    if exc.status_code == status.HTTP_409_CONFLICT and "IDEMPOTENCY_CONFLICT" in detail_msg:
        content = {
            "error": "IDEMPOTENCY_CONFLICT",
            "code": "IDEMPOTENCY_CONFLICT",
            "detail": detail_msg
        }
    elif isinstance(exc.detail, str):
        content = {"error": exc.detail, "detail": exc.detail}
    else:
        content = exc.detail

    headers = {"A2A-Version": "1.0"} if is_a2a else {}
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        media_type=media_type,
        headers=headers
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    is_a2a = _is_a2a_path(request.url.path)
    media_type = "application/a2a+json" if is_a2a else "application/json"
    errors = exc.errors()
    # Log sanitized validation error without leaking sensitive body contents
    sanitized_errs = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in errors]
    logger.warning(f"Validation error on {request.method} {request.url.path}: {sanitized_errs}")
    headers = {"A2A-Version": "1.0"} if is_a2a else {}
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "Invalid request schema", "details": sanitized_errs},
        media_type=media_type,
        headers=headers
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    is_a2a = _is_a2a_path(request.url.path)
    media_type = "application/a2a+json" if is_a2a else "application/json"
    logger.error(f"Internal server error on {request.method} {request.url.path}: {exc}", exc_info=True)
    headers = {"A2A-Version": "1.0"} if is_a2a else {}
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "An internal server error occurred"},
        media_type=media_type,
        headers=headers
    )


# ---------------------------------------------------------------------
# UNPROTECTED HEALTH AND AGENT CARD ENDPOINTS
# ---------------------------------------------------------------------
@app.get("/healthz")
@app.head("/healthz")
@app.get("/health")
@app.head("/health")
@app.get("/")
async def health_check():
    return {"status": "ok", "service": "A2A Invoice Agent"}


@app.get("/.well-known/agent-card.json")
@app.head("/.well-known/agent-card.json")
async def agent_card_endpoint(request: Request):
    # If PUBLIC_BASE_URL is default/localhost, dynamically inspect request headers
    configured = settings.normalized_public_base_url
    if "localhost" in configured or "127.0.0.1" in configured:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        if host and "localhost" not in host and "127.0.0.1" not in host:
            dynamic_base = f"{proto}://{host}/a2a"
            card = get_agent_card(dynamic_base)
            return JSONResponse(content=card, media_type="application/json")

    card = get_agent_card()
    return JSONResponse(content=card, media_type="application/json")


# ---------------------------------------------------------------------
# PROTECTED A2A 1.0 ENDPOINTS (Mounted at both /a2a and root paths)
# ---------------------------------------------------------------------
@app.post("/a2a/message:send")
@app.post("/message:send")
async def message_send_endpoint(
    request: Request,
    principal: str = Depends(verify_a2a_auth),
    _ct = Depends(verify_a2a_content_type),
    db: Session = Depends(get_db)
):
    try:
        raw_body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON body"
        )

    if not isinstance(raw_body, dict) or "message" not in raw_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must include 'message'"
        )

    raw_msg_dict = raw_body["message"]
    try:
        req_data = SendMessageRequest(**raw_body)
    except Exception as ex:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request schema: {ex}"
        )

    resp_content = await handle_message_send(
        request_data=req_data,
        raw_message_dict=raw_msg_dict,
        principal=principal,
        db=db
    )
    return JSONResponse(content=resp_content, media_type="application/a2a+json", headers={"A2A-Version": "1.0"})


@app.get("/a2a/tasks/{task_id}")
@app.get("/tasks/{task_id}")
async def get_task_endpoint(
    task_id: str,
    principal: str = Depends(verify_a2a_auth),
    db: Session = Depends(get_db)
):
    task_content = get_task_by_id(principal=principal, task_id=task_id, db=db)
    return JSONResponse(content=task_content, media_type="application/a2a+json", headers={"A2A-Version": "1.0"})


@app.get("/a2a/tasks")
@app.get("/a2a/tasks/")
@app.get("/tasks")
@app.get("/tasks/")
async def list_tasks_endpoint(
    principal: str = Depends(verify_a2a_auth),
    db: Session = Depends(get_db)
):
    tasks_content = list_user_tasks(principal=principal, db=db)
    return JSONResponse(content=tasks_content, media_type="application/a2a+json", headers={"A2A-Version": "1.0"})


@app.post("/a2a/tasks/{task_id}:cancel")
@app.post("/tasks/{task_id}:cancel")
async def cancel_task_endpoint(
    task_id: str,
    principal: str = Depends(verify_a2a_auth),
    db: Session = Depends(get_db)
):
    canceled_content = cancel_task_by_id(principal=principal, task_id=task_id, db=db)
    return JSONResponse(content=canceled_content, media_type="application/a2a+json", headers={"A2A-Version": "1.0"})
