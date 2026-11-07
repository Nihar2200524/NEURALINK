import pytest
from agentra.session_manager import SessionManager
from agentra.state_engine import capture
from agentra.action_dispatcher import dispatch
from agentra.models import Action, Postcondition


@pytest.fixture
async def session():
    manager = SessionManager()
    await manager.start()
    session = await manager.create("test")
    try:
        yield session
    finally:
        await manager.close()


async def test_stale_and_approval(session):
    page = session.pages["tab_0"]
    await page.set_content('<label>Name<input></label><button onclick="document.querySelector(\'output\').textContent=\'Done\'">Save</button><output></output>')
    state = await capture(session)
    ref = next(node.ref for node in state.nodes if node.name == "Save")
    action = Action(kind="CLICK", scoped_ref=ref, postcondition=Postcondition(kind="text", selector="output", value="Done"))
    assert (await dispatch(session, action)).status == "AUTHORIZATION_REQUIRED"
    assert await page.locator("output").inner_text() == ""
    assert (await dispatch(session, action, approved=True)).status == "VERIFIED"
    assert (await dispatch(session, action, approved=True)).status == "STALE_REFERENCE_ERROR"


async def test_mutation_rejected(session):
    page = session.pages["tab_0"]
    await page.set_content('<label>Name<input></label>')
    state = await capture(session)
    await page.locator("input").evaluate("e => e.setAttribute('disabled', '')")
    result = await dispatch(session, Action(kind="TYPE", scoped_ref=state.nodes[0].ref, text="test"), approved=True)
    assert result.status == "STALE_REFERENCE_ERROR"


async def test_tabs_and_frames(session):
    await session.pages["tab_0"].set_content('<iframe srcdoc="<button>Inside</button>"></iframe>')
    second = await session.context.new_page()
    await second.set_content('<button>Second</button>')
    topology = await session.topology()
    assert len(topology) == 3
    state = await capture(session)
    assert any("::tab_1::" in node.ref for node in state.nodes)
    assert any(node.name == "Inside" for node in state.nodes)
    assert state.tokens <= 2500


async def test_delayed_hydration(session):
    page = session.pages["tab_0"]
    await page.set_content('<button disabled>Load</button><script>setTimeout(() => document.querySelector("button").disabled=false, 50)</script>')
    await page.wait_for_function('!document.querySelector("button").disabled')
    state = await capture(session)
    assert any(node.name == "Load" for node in state.nodes)
