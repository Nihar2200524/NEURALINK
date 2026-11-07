import asyncio
import json
import pytest
from agentra.action_dispatcher import dispatch
from agentra.config import BrowserSettings
from agentra.models import Action, Postcondition
from agentra.session_manager import SessionManager
from agentra.state_engine import capture, extract, token_count
from agentra.readiness import readiness


@pytest.fixture
async def manager():
    manager = SessionManager(BrowserSettings())
    await manager.start()
    try:
        yield manager
    finally:
        await manager.close()


async def test_preexisting_postcondition_does_not_claim_success(manager):
    session = await manager.create('test')
    page = session.pages['tab_0']
    await page.set_content('<button onclick="this.textContent=\'Clicked\'">Save</button><output>Done</output>')
    state = await capture(session)
    ref = next(n.ref for n in state.nodes if n.role == 'button')
    receipt = await dispatch(session, Action(kind='CLICK', scoped_ref=ref, postcondition=Postcondition(kind='text', selector='output', value='Done')), approved=True)
    assert receipt.status == 'FAILED'
    assert 'ALREADY_SATISFIED' in receipt.detail
    assert await page.locator('button').inner_text() == 'Save'


async def test_markdown_structure_and_field_privacy(manager):
    session = await manager.create('test')
    await session.pages['tab_0'].set_content('<main><h1>Report</h1><p>Revenue summary</p><table><tr><th>Name</th><th>Total</th></tr><tr><td>Ada</td><td>42</td></tr></table><input type="password" value="never-export"><canvas></canvas></main>')
    state = await capture(session)
    assert 'Report' in state.content
    assert state.handoff_reasons
    assert token_count(state.model_dump_json()) <= 2500
    ref = next(n.ref for n in state.nodes if n.role == 'document')
    result = await extract(session, ref, 'markdown')
    assert '# Report' in result
    assert '| Name | Total |' in result
    assert '| Ada | 42 |' in result
    assert 'never-export' not in result
    assert json.loads(await extract(session, ref, 'json'))['trust'] == 'untrusted_web_payload'


async def test_memory_budget_stops_worker(manager, monkeypatch):
    session = await manager.create('test')
    assert manager.memory_bytes(session) > 0
    monkeypatch.setattr(manager, 'memory_bytes', lambda session: 2 * 1024**3)
    async with asyncio.timeout(5):
        while session.lifecycle == 'ACTIVE':
            await asyncio.sleep(.05)
        while session.browser.is_connected():
            await asyncio.sleep(.05)
    assert session.failure == 'MEMORY_LIMIT'


async def test_cancellation_releases_queue_slot(manager):
    session = await manager.create('test')
    async def queued():
        async with session.operation():
            pass
    await session.lock.acquire()
    task = asyncio.create_task(queued())
    await asyncio.sleep(0)
    assert session.waiting == 1
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    session.lock.release()
    assert session.waiting == 0


async def test_readiness_and_shadow_freshness(manager):
    session = await manager.create('test')
    page = session.pages['tab_0']
    await page.set_content('<button disabled>Waiting</button><div id="host"></div>')
    await page.locator('#host').evaluate("e => e.attachShadow({mode:'open'}).innerHTML='<button>Shadow</button>'")
    state = await capture(session)
    waiting = next(n.ref for n in state.nodes if n.name == 'Waiting')
    shadow = next(n.ref for n in state.nodes if n.name == 'Shadow')
    assert await readiness(session, waiting, 100) == 'PARTIAL'
    assert await readiness(session, shadow, 500) == 'READY'
    await page.locator('#host').evaluate("e => e.shadowRoot.querySelector('button').textContent='Changed'")
    receipt = await dispatch(session, Action(kind='CLICK', scoped_ref=shadow, postcondition=Postcondition(kind='text', selector='#host button', value='Result')), approved=True)
    assert receipt.status == 'STALE_REFERENCE_ERROR'
