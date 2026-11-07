import httpx
import pytest
from agentra.server import app
import agentra.server as server
from agentra.session_manager import SessionManager
from agentra.state_engine import capture


async def test_recovery_ownership_and_idempotency(monkeypatch):
    manager = SessionManager()
    await manager.start()
    monkeypatch.setattr(server, "manager", manager)
    monkeypatch.setenv("AGENTRA_TOKENS", '{"a":"' + "a" * 40 + '","b":"' + "b" * 40 + '"}')
    monkeypatch.setenv("AGENTRA_APPROVER_TOKEN", "c" * 40)
    headers = {"Authorization": "Bearer " + "a" * 40}
    try:
        session = await manager.create("a")
        await session.pages["tab_0"].set_content('<label>Name<input></label>')
        state = await capture(session)
        action = {"kind": "TYPE", "scoped_ref": state.nodes[0].ref, "text": "secret text"}
        base = f"/sessions/{session.id}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            denied = await client.post(base + "/recover", headers={"Authorization": "Bearer " + "b" * 40})
            assert denied.status_code == 404
            queued = await client.post(base + "/actions", headers={**headers, "Idempotency-Key": "original"}, json=action)
            assert queued.json()["status"] == "AUTHORIZATION_REQUIRED"
            await session.browser.close()
            unavailable = await client.get(base + "/state", headers=headers)
            assert unavailable.status_code == 409
            assert unavailable.json()["lifecycle"] == "CRASHED"
            recovered = await client.post(base + "/recover", headers=headers)
            assert recovered.status_code == 200
            assert recovered.json()["generation"] == 2
            replay = await client.post(base + "/actions", headers={**headers, "Idempotency-Key": "original"}, json=action)
            assert replay.json()["status"] == "FAILED"
            approval = await client.post(base + "/authorize", headers=headers, json={"action_id": queued.json()["action_id"], "auth_token": "c" * 40})
            assert approval.status_code == 409
            assert session.pages["tab_0"].url == "about:blank"
            assert (await client.get(base + "/state", headers=headers)).status_code == 200
    finally:
        await manager.close()
