import asyncio
import os
import time
import pytest
from agentra.models import Action
from agentra.action_dispatcher import dispatch
from agentra.session_manager import SessionManager, SessionUnavailable
from agentra.state_engine import capture, resolve


@pytest.fixture
async def manager():
    instance = SessionManager()
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()


async def test_worker_loss_is_isolated_and_recoverable(manager):
    first = await manager.create("a")
    second = await manager.create("b")
    assert first.browser is not second.browser
    await first.pages["tab_0"].set_content('<label>Name<input></label>')
    state = await capture(first)
    ref = state.nodes[0].ref
    action = Action(kind="TYPE", scoped_ref=ref, text="never replay")
    receipt = await dispatch(first, action)
    first.results["key"] = ("fingerprint", receipt)
    await first.browser.close()
    assert first.lifecycle == "CRASHED"
    assert second.lifecycle == "ACTIVE"
    assert second.browser.is_connected()
    assert not first.pending
    assert first.results["key"][1].status == "FAILED"
    with pytest.raises(SessionUnavailable):
        async with first.operation():
            pytest.fail("crashed session accepted operation")
    await manager.recover(first)
    assert first.lifecycle == "ACTIVE"
    assert first.generation == 2
    assert first.pages["tab_0"].url == "about:blank"
    assert first.version > int(state.snapshot_version.split('_')[1])
    with pytest.raises(ValueError, match="STALE_REFERENCE_ERROR"):
        await resolve(first, ref)
    await manager.recover(first)
    assert first.generation == 2


async def test_delete_closes_worker_and_disk(manager):
    session = await manager.create("a")
    path = session.directory.name
    await manager.delete(session)
    assert not os.path.exists(path)
    assert not session.browser.is_connected()
    assert session.id not in manager.sessions
    await manager.delete(session)
    with pytest.raises(SessionUnavailable):
        await manager.recover(session)
    with pytest.raises(SessionUnavailable):
        async with session.operation():
            pytest.fail("closed session accepted queued operation")


async def test_idle_cleanup_rechecks_activity(manager):
    session = await manager.create("a")
    session.touched = time.monotonic() - 1000
    async with session.operation():
        cleanup = asyncio.create_task(manager.delete(session, idle_seconds=900))
        await asyncio.sleep(0)
    await cleanup
    assert session.lifecycle == "ACTIVE"
    session.touched = time.monotonic() - 1000
    await manager.delete(session, idle_seconds=900)
    assert session.lifecycle == "CLOSED"


async def test_old_worker_event_does_not_poison_recovery(manager):
    session = await manager.create("a")
    previous = session.browser
    await previous.close()
    await manager.recover(session)
    session.mark_crashed(previous, "LATE_EVENT")
    assert session.lifecycle == "ACTIVE"
