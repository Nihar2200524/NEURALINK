"""Run from repository root: python -m scripts.benchmark."""
import asyncio
import json
import time
import psutil
from agentra.session_manager import SessionManager
from agentra.state_engine import capture, token_count
from agentra.action_dispatcher import dispatch
from agentra.models import Action, Postcondition


async def main():
    manager = SessionManager()
    await manager.start()
    rows = []
    try:
        for _ in range(3):
            session = await manager.create("benchmark")
            page = session.pages["tab_0"]
            await page.set_content('<main><h1>Benchmark</h1><button onclick="document.querySelector(\'output\').textContent=\'Done\'">Save</button><output></output>' + ''.join(f'<button>Item {i}</button>' for i in range(100)) + '</main>')
            started = time.perf_counter()
            state = await capture(session)
            snapshot_seconds = time.perf_counter() - started
            ref = next(n.ref for n in state.nodes if n.name == 'Save')
            action_started = time.perf_counter()
            result = await dispatch(session, Action(kind='CLICK', scoped_ref=ref, postcondition=Postcondition(kind='text', selector='output', value='Done')), approved=True)
            action_seconds = time.perf_counter() - action_started
            process = psutil.Process()
            processes = [process] + process.children(recursive=True)
            rows.append({"sessions": len(manager.sessions), "snapshot_seconds": snapshot_seconds, "action_seconds": action_seconds, "action_status": result.status, "html_tokens": token_count(await page.content()), "snapshot_tokens": state.tokens, "rss_bytes": sum(p.memory_info().rss for p in processes if p.is_running()), "cpu_seconds": sum(sum(p.cpu_times()[:2]) for p in processes if p.is_running())})
        started = time.perf_counter()
        concurrent = await asyncio.gather(*(capture(s) for s in manager.sessions.values()))
        rows.append({"concurrent_sessions": len(concurrent), "concurrent_capture_seconds": time.perf_counter() - started})
        print(json.dumps(rows, indent=2))
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
