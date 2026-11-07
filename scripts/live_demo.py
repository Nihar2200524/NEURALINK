"""Visible, offline demonstration: python -m scripts.live_demo."""
import asyncio
from agentra.config import BrowserSettings
from agentra.session_manager import SessionManager
from agentra.state_engine import capture
from agentra.action_dispatcher import dispatch
from agentra.models import Action, Postcondition

HTML = """<!doctype html><html><head><title>Agentra live demonstration</title>
<style>body{font:22px system-ui;max-width:700px;margin:70px auto;background:#101827;color:#eee}
input,button{font:inherit;padding:12px;margin:12px 0;display:block}output{color:#6ee7b7}</style>
</head><body><h1>Watch Agentra work</h1><p>This demonstration runs offline on a synthetic page.</p>
<label>Your message<input id="message"></label><button id="save">Save message</button>
<output id="receipt" aria-live="polite"></output><script>
document.querySelector('#save').onclick=()=>{document.querySelector('#receipt').textContent=
'Saved: '+document.querySelector('#message').value;};</script></body></html>"""


async def main() -> None:
    manager = SessionManager(BrowserSettings(headed=True, slow_mo_ms=400))
    await manager.start()
    try:
        session = await manager.create("offline-demo")
        await session.pages["tab_0"].set_content(HTML)
        await session.pages["tab_0"].bring_to_front()
        print("Live Chromium window opened. Watch the message field and Save button.", flush=True)
        await asyncio.sleep(2)
        state = await capture(session)
        ref = next(node.ref for node in state.nodes if node.role == "textbox")
        typed = await dispatch(session, Action(kind="TYPE", scoped_ref=ref, text="Hello from Agentra!"), approved=True)
        if typed.status != "VERIFIED":
            raise RuntimeError(typed.detail)
        await asyncio.sleep(2)
        state = await capture(session)
        ref = next(node.ref for node in state.nodes if node.role == "button")
        clicked = await dispatch(session, Action(kind="CLICK", scoped_ref=ref, postcondition=Postcondition(kind="text", selector="#receipt", value="Saved: Hello from Agentra!")), approved=True)
        if clicked.status != "VERIFIED":
            raise RuntimeError(clicked.detail)
        print("VERIFIED: text filled, button clicked, confirmation checked. Closing in 15 seconds.", flush=True)
        await asyncio.sleep(15)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
