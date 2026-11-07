import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import time
from collections.abc import AsyncIterator
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from .models import Action, Authorization, Inspect, Receipt, State
from .security import tenant_for_token, verify_approval
from .session_manager import Session, SessionManager
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


def tenant(authorization: str = Header(default="")) -> str:
    return tenant_for_token(authorization)


def owned(sid: str, owner: str = Depends(tenant)) -> Session:
    session = manager.sessions.get(sid)
    if not session or session.tenant != owner:
        raise HTTPException(404, "Session not found")
    session.touched = time.monotonic()
    return session


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
    async with session.lock:
        return await capture(session)


@app.post("/sessions/{sid}/actions")
async def action(body: Action, session: Session = Depends(owned), idempotency_key: str = Header(min_length=1, max_length=128)) -> Receipt:
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with session.lock:
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
    async with session.lock:
        pending = session.pending.pop(body.action_id, None)
        if not pending or pending[1] < time.monotonic():
            raise HTTPException(409, "Approval expired, consumed, or unknown")
        result = await dispatch(session, pending[0], approved=True, action_id=body.action_id)
        for key, (fingerprint, receipt) in session.results.items():
            if receipt.action_id == body.action_id:
                session.results[key] = (fingerprint, result)
        return result


@app.post("/sessions/{sid}/inspect")
async def inspect(body: Inspect, session: Session = Depends(owned)) -> dict[str, object]:
    async with session.lock:
        try:
            return await inspect_node(session, body.scoped_ref, body.budget, body.depth)
        except ValueError as exc:
            raise HTTPException(409, "STALE_REFERENCE_ERROR") from exc


@app.post("/sessions/{sid}/extract")
async def extract_content(body: Inspect, session: Session = Depends(owned)) -> StreamingResponse:
    async with session.lock:
        try:
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
