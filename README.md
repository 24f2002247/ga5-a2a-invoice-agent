# A2A 1.0 Invoice Agent (GA5 Question 2)

An enterprise-grade, autonomous invoice auditing and settlement agent implementing the official **A2A 1.0 HTTP+JSON protocol** with persistent task state, idempotency deduplication, evidence citation validation, user isolation, and atomic race condition prevention.

---

## 1. Architecture & Protocol Overview

The service exposes origin-level discovery and protected `/a2a` endpoints:

| Endpoint | Method | Auth | Media Type | Purpose |
|---|---|---|---|---|
| `/.well-known/agent-card.json` | `GET`, `HEAD` | None | `application/json` | A2A 1.0 Agent Card discovery |
| `/healthz` | `GET`, `HEAD` | None | `application/json` | Unprotected container health check |
| `/a2a/message:send` | `POST` | Bearer + A2A-Version | `application/a2a+json` | Initial invoice batch proposal & result continuation |
| `/a2a/tasks/{id}` | `GET` | Bearer + A2A-Version | `application/a2a+json` | Retrieve task state and artifacts |
| `/a2a/tasks` | `GET` | Bearer + A2A-Version | `application/a2a+json` | List all tasks scoped to authenticated principal |
| `/a2a/tasks/{id}:cancel` | `POST` | Bearer + A2A-Version | `application/a2a+json` | Atomically cancel nonterminal task |

### URL Prefix & Routing
- Configured public base URL ends in `/a2a` (e.g. `https://domain.com/a2a`).
- The Agent Card is served at the origin-level path `/.well-known/agent-card.json` (outside the `/a2a` prefix).
- Both standard and URL-encoded action colons (`:send` and `%3Asend`, `:cancel` and `%3Acancel`) are routed cleanly without 307 redirects.

---

## 2. A2A Protocol Compliance & Security

1. **Protocol Headers:**
   - `A2A-Version: 1.0` is strictly required on all `/a2a/*` endpoints (returns `400 Bad Request` if missing or unsupported).
   - `Authorization: Bearer <token>` is required on all `/a2a/*` endpoints (returns `401 Unauthorized` if missing/invalid).
   - `Content-Type: application/a2a+json` is required on all requests submitting a body.
   - All protected responses use `Content-Type: application/a2a+json`.
2. **ProtoJSON Enums:**
   - Role: `ROLE_USER`, `ROLE_AGENT`
   - State: `TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_COMPLETED`, `TASK_STATE_CANCELED`
3. **Response Envelope & Limits:**
   - Success responses return `{"task": Task}` or `{"tasks": [Task, ...]}`.
   - All responses remain well under the 512 KiB protocol ceiling.
   - Error messages do not leak internal credentials, stack traces, or other users' task metadata.

---

## 3. Invoice Decision Engine & Evidence Citations

Each package is evaluated across five mutually exclusive business actions:

1. `settle_invoice`: Fully reconciled 3-way match within autonomous authority ceiling.
2. `request_approval`: Commercially valid claim exceeding autonomous delegation limit or requiring named managerial approval.
3. `hold_invoice`: Payment paused until verification (e.g. unconfirmed bank destination change).
4. `reject_duplicate`: Exact commercial invoice already paid in prior settlement.
5. `open_exception`: Material variance outside reconciliation tolerance or contradictory signed records.

### Extraction & Citation Rules
- **Facts Extraction:** Accurately extracts `vendorName`, `invoiceNumber`, `amountMinor` (minor currency units integer), and `currency` (3-letter uppercase code).
- **Decisive Citations:** Finds the decisive paragraph and cites **exactly 3 bracketed references** (e.g. `["[R_D5ZJWFKBT5AXF6]", "[R_ET68WNQGXTMTG6]", "[R_IY47JFAMH4DSAD]"]`). Excludes cover-sheet references, archive examples, and training decoys.
- **Rationale:** Strict 60–1500 character justification explicitly citing the action name and at least two evidence references.
- **Action ID:** Unique, durable identifier derived from canonical content hash of at least 12 characters (e.g. `act_1367824dfce5d135`).
- **Canonical Decision Caching:** Cached by SHA-256 of recursively key-sorted canonical package JSON in `a2a_decision_cache` table. Re-evaluations across new batch/message/task IDs reuse decisions with zero model invocations.

---

## 4. Task Lifecycle, Idempotency & Concurrency

### Initial Batch Request (`application/vnd.ga5.invoice-claim-batch+json`)
- Deduplicated by `(principal, message.messageId)`.
- Semantic hash computes SHA-256 over key-sorted compact JSON of `message` only (`configuration` is excluded).
- Reordered JSON keys return the exact same Task.
- Changed `configuration` returns the exact same Task without conflict.
- Reusing `messageId` with altered message payload returns `409 Conflict` with `IDEMPOTENCY_CONFLICT`.
- Tasks initialize in `TASK_STATE_INPUT_REQUIRED` with a single proposal artifact. **No receipt artifact is generated during initial response.**

### Result Continuation (`application/vnd.ga5.invoice-action-results+json`)
- Validates `taskId`, `contextId`, `batchId`, `packageId`, and `actionId` against stored proposals.
- Rejects mismatches with `400 Bad Request`.
- Only `ACCEPTED` proposals generate execution entries with the exact grader-provided `receiptNonce`.
- `REJECTED` proposals are omitted from executions.
- Emits receipt artifact `application/vnd.ga5.invoice-action-receipts+json`.
- Atomically transitions task state to `TASK_STATE_COMPLETED`.

### Atomic Cancellation vs. Receipt Races
- A nonterminal task in `TASK_STATE_INPUT_REQUIRED` can be canceled via `POST /a2a/tasks/{id}:cancel`.
- State transitions use conditional atomic SQL updates:
  ```sql
  UPDATE a2a_tasks SET state = :new_state, ... WHERE task_id = :id AND bearer_token = :principal AND state = 'TASK_STATE_INPUT_REQUIRED'
  ```
- If cancellation and continuation arrive concurrently, exactly one operation receives `rowcount == 1` and returns `200 OK`. The losing operation receives `rowcount == 0` and returns `409 Conflict`.
- Terminal tasks are immutable.

### Strict User Isolation
- Every query is scoped by `WHERE bearer_token = :principal`.
- Task listing (`GET /a2a/tasks`) returns only the authenticated principal's tasks.
- Accessing or mutating another user's task returns `404 Not Found` without disclosing existence.

---

## 5. Local Setup & Testing

### Installation
```bash
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Running Tests
The test suite covers all 25 assignment requirements using pytest and anyio:
```bash
python -m pytest tests -v
```

### Starting the Server Locally
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify endpoints:
```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/.well-known/agent-card.json
```

---

## 6. Environment Configuration

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Port for Uvicorn server |
| `HOST` | `0.0.0.0` | Bind host address |
| `PUBLIC_BASE_URL` | `http://localhost:8000/a2a` | Submitted public base URL ending in `/a2a` |
| `DATABASE_URL` | `sqlite:///./a2a_invoice_agent.db` | SQLite or PostgreSQL connection string |
| `AUTH_BEARER_TOKEN` | *(empty)* | Optional fixed token or comma-separated tokens. If empty, any Bearer token acts as an isolated principal |
| `TEST_MODE` | `true` | When true, runs deterministic high-precision audit engine without external AI keys |
| `AI_PROVIDER` | `openai` | AI provider protocol (`openai`, `openrouter`, `aipipe`, `gemini`) |
| `AI_API_KEY` | *(empty)* | API key for hosted LLM calls |
| `AI_MODEL` | `gpt-4o-mini` | LLM model identifier |

---

## 7. Production Deployment (Docker & Render)

### Docker Deployment
```bash
docker build -t a2a-invoice-agent .
docker run -p 8000:8000 -e PUBLIC_BASE_URL="https://your-public-domain.com/a2a" a2a-invoice-agent
```

### Render Deployment
This repository contains a ready-to-deploy `render.yaml`:
1. Push this directory to GitHub.
2. In Render, select **New -> Blueprint** and connect the repository.
3. Configure `PUBLIC_BASE_URL` to `https://<service-name>.onrender.com/a2a`.
4. Render automatically runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT` and monitors `/healthz`.
