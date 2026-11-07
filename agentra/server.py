import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import time
from collections.abc import AsyncIterator
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from playwright.async_api import Error as BrowserError
from fastapi.exceptions import RequestValidationError
from .models import Action, Authorization, Inspect, Receipt, State, ReadinessRequest
from .http_limits import BodyLimit
from .readiness import readiness
from .security import tenant_for_token, verify_approval
from .session_manager import Session, SessionManager, SessionUnavailable
from .state_engine import capture, extract, inspect_node
from .action_dispatcher import dispatch

manager = SessionManager()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await manager.start()
    reaper = asyncio.create_task(manager.reap())
    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
        await manager.close()


app = FastAPI(title="Agentra", version="0.1.0", lifespan=lifespan)
app.add_middleware(BodyLimit)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic errors can echo submitted credentials/text; expose locations only.
    return JSONResponse(status_code=422, content={"detail": [{"loc": list(error["loc"]), "type": error["type"]} for error in exc.errors()]})


@app.exception_handler(TimeoutError)
async def operation_timeout(request: Request, exc: TimeoutError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": "OPERATION_TIMEOUT", "retry_safe": False})


@app.get("/health")
async def health() -> dict[str, str]:
    if not manager.playwright or manager.closing:
        raise HTTPException(503, "Service unavailable")
    return {"status": "ready"}


@app.exception_handler(BrowserError)
async def browser_error(request: Request, exc: BrowserError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "BROWSER_OPERATION_FAILED", "retry_safe": False, "guidance": "Inspect session status; do not replay uncertain actions"})


@app.exception_handler(SessionUnavailable)
async def unavailable(request: Request, exc: SessionUnavailable) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "SESSION_UNAVAILABLE", "lifecycle": str(exc), "recovery": "POST /sessions/{sid}/recover creates a blank worker; actions are never replayed"})


def tenant(authorization: str = Header(default="")) -> str:
    return tenant_for_token(authorization)


def owned(sid: str, owner: str = Depends(tenant)) -> Session:
    session = manager.sessions.get(sid)
    if not session or session.tenant != owner:
        raise HTTPException(404, "Session not found")
    session.touched = time.monotonic()
    return session


@app.get("/sessions/{sid}/status")
async def status(session: Session = Depends(owned)) -> dict[str, object]:
    async with session.lock:
        return {"session_id": session.id, "lifecycle": session.lifecycle, "generation": session.generation, "failure": session.failure, "tabs": list(session.pages)}


@app.post("/sessions/{sid}/recover")
async def recover(session: Session = Depends(owned)) -> dict[str, object]:
    await manager.recover(session)
    return {"session_id": session.id, "lifecycle": session.lifecycle, "generation": session.generation, "detail": "Worker available; no actions replayed"}


@app.post("/sessions", status_code=201)
async def create(owner: str = Depends(tenant)) -> dict[str, str]:
    try:
        return {"session_id": (await manager.create(owner)).id}
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.delete("/sessions/{sid}", status_code=204)
async def delete(session: Session = Depends(owned)) -> None:
    await manager.delete(session)


@app.get("/sessions/{sid}/state")
async def state(session: Session = Depends(owned)) -> State:
    async with session.operation():
        async with asyncio.timeout(10):
            return await capture(session)


@app.post("/sessions/{sid}/actions")
async def action(body: Action, session: Session = Depends(owned), idempotency_key: str = Header(min_length=1, max_length=128)) -> Receipt:
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with session.operation():
        previous = session.results.get(idempotency_key)
        if previous:
            if previous[0] != fingerprint:
                raise HTTPException(409, "Idempotency key reused with different action")
            return previous[1]
        if len(session.results) >= 1000:
            raise HTTPException(429, "Session action limit reached")
        result = await dispatch(session, body)
        session.results[idempotency_key] = (fingerprint, result)
        return result


@app.post("/sessions/{sid}/authorize")
async def authorize(body: Authorization, session: Session = Depends(owned)) -> Receipt:
    if not verify_approval(body.auth_token):
        raise HTTPException(403, "Invalid approver credential")
    async with session.operation():
        pending = session.pending.pop(body.action_id, None)
        if not pending or pending[1] < time.monotonic():
            raise HTTPException(409, "Approval expired, consumed, or unknown")
        # Reserve a terminal receipt before any side effect. Cancellation or a
        # disconnected caller must never make a retry execute the action again.
        for key, (fingerprint, receipt) in session.results.items():
            if receipt.action_id == body.action_id:
                session.results[key] = (fingerprint, Receipt(status="FAILED", action_id=body.action_id, detail="Execution started; outcome unknown until final receipt; do not replay"))
        result = await dispatch(session, pending[0], approved=True, action_id=body.action_id)
        for key, (fingerprint, receipt) in session.results.items():
            if receipt.action_id == body.action_id:
                session.results[key] = (fingerprint, result)
        return result


@app.post("/sessions/{sid}/review")
async def review(body: Authorization, session: Session = Depends(owned)) -> dict[str, object]:
    if not verify_approval(body.auth_token):
        raise HTTPException(403, "Invalid approver credential")
    async with session.operation():
        pending = session.pending.get(body.action_id)
        if not pending or pending[1] < time.monotonic():
            raise HTTPException(409, "Approval expired, consumed, or unknown")
        return {"action_id": body.action_id, "action": pending[0].model_dump(), "expires_in_seconds": max(0, int(pending[1] - time.monotonic()))}


@app.post("/sessions/{sid}/inspect")
async def inspect(body: Inspect, session: Session = Depends(owned)) -> dict[str, object]:
    async with session.operation():
        try:
            async with asyncio.timeout(10):
                return await inspect_node(session, body.scoped_ref, body.budget, body.depth)
        except ValueError as exc:
            raise HTTPException(409, "STALE_REFERENCE_ERROR") from exc


@app.post("/sessions/{sid}/readiness")
async def task_readiness(body: ReadinessRequest, session: Session = Depends(owned)) -> dict[str, str]:
    async with session.operation():
        try:
            result = await readiness(session, body.scoped_ref, body.timeout_ms)
            return {"readiness": result, "scoped_ref": body.scoped_ref}
        except ValueError as exc:
            raise HTTPException(409, "STALE_REFERENCE_ERROR") from exc


@app.post("/sessions/{sid}/extract")
async def extract_content(body: Inspect, session: Session = Depends(owned)) -> StreamingResponse:
    async with session.operation():
        try:
            async with asyncio.timeout(10):
                content = await extract(session, body.scoped_ref, body.format)
        except ValueError as exc:
            raise HTTPException(409, "STALE_REFERENCE_ERROR") from exc
    async def chunks() -> AsyncIterator[str]:
        for offset in range(0, len(content), 8192):
            yield content[offset:offset + 8192]
    return StreamingResponse(chunks(), media_type="application/json" if body.format == "json" else "text/plain", headers={"X-Agentra-Trust": "untrusted_web_payload"})


@app.get("/metrics")
async def metrics(owner: str = Depends(tenant)) -> Response:
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})
