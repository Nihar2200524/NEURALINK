"""Run from repository root: python -m scripts.benchmark."""
import asyncio
import json
import time
import psutil
from agentra.session_manager import SessionManager
from agentra.state_engine import capture, token_count


async def main():
    manager = SessionManager()
    await manager.start()
    rows = []
    try:
        for _ in range(3):
            session = await manager.create("benchmark")
            page = session.pages["tab_0"]
            await page.set_content('<main><h1>Benchmark</h1>' + ''.join(f'<button>Item {i}</button>' for i in range(100)) + '</main>')
            started = time.perf_counter()
            state = await capture(session)
            process = psutil.Process()
            processes = [process] + process.children(recursive=True)
            rows.append({"sessions": len(manager.sessions), "snapshot_seconds": time.perf_counter() - started, "html_tokens": token_count(await page.content()), "snapshot_tokens": state.tokens, "rss_bytes": sum(p.memory_info().rss for p in processes if p.is_running()), "cpu_seconds": sum(sum(p.cpu_times()[:2]) for p in processes if p.is_running())})
        print(json.dumps(rows, indent=2))
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
