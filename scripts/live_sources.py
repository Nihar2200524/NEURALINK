"""Live acceptance checks using the same runtime as the API."""
import asyncio
import json
import sys
from agentra.session_manager import SessionManager
from agentra.action_dispatcher import dispatch
from agentra.models import Action
from agentra.page_reader import read_page


async def main():
    manager = SessionManager()
    await manager.start()
    try:
        for url in sys.argv[1:]:
            session = await manager.create('live-acceptance')
            try:
                receipt = await dispatch(session, Action(kind='NAVIGATE', url=url, timeout_ms=30000), approved=True)
                print(json.dumps({'requested_url':url,'navigation_status':receipt.status}), flush=True)
                result = await read_page(session.pages['tab_0'])
                result.pop('links', None)
                result['content'] = '\n'.join(line for line in result['content'].splitlines() if any(word in line.lower() for word in ('hyderabad', 'karat', 'carat', 'november', 'nov ', 'gram', '14,', '13,')))[:12000]
                print(json.dumps(result, ensure_ascii=True), flush=True)
            except Exception as exc:
                print(json.dumps({'error_type':type(exc).__name__}), flush=True)
            finally:
                await manager.delete(session)
    finally:
        await manager.close()


if __name__ == '__main__':
    asyncio.run(main())
