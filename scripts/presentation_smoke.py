"""Exercise the deployed viewer against a real browser session."""
import asyncio
import json
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

root = Path(__file__).resolve().parents[1]
config = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines() if '=' in line)
token = json.loads(config['AGENTRA_TOKENS'])['local']
def request(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request('http://127.0.0.1:8000'+path, data=data, method=method,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Idempotency-Key':'viewer-smoke'})
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read()
        return json.loads(raw) if raw else None

async def main():
    sid = request('/sessions', {}, 'POST')['session_id']
    try:
        receipt = request('/sessions/'+sid+'/actions', {'kind':'NAVIGATE','url':'https://example.com'})
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto('http://127.0.0.1:8000/')
            await page.get_by_role('button', name='Connect', exact=True).click()
            await page.get_by_label('API token', exact=True).fill(token)
            await page.get_by_role('button', name='Connect live view').click()
            await page.get_by_text('Approval needed', exact=True).wait_for()
            result=await asyncio.to_thread(request, '/sessions/'+sid+'/authorize', {'action_id':receipt['action_id'],'auth_token':config['AGENTRA_APPROVER_TOKEN']})
            assert result['status']=='VERIFIED'
            await page.get_by_text('Action verified', exact=True).wait_for()
            await page.wait_for_function("document.querySelector('#frame').naturalWidth > 0")
            await page.screenshot(path=str(root/'presentation-preview.png'), full_page=True)
            await page.get_by_role('button', name='Pause view').click()
            await page.get_by_text('View paused', exact=True).wait_for()
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.get_by_role('button', name='Disconnect', exact=True).click()
            assert await page.locator('#frame').is_hidden()
            assert not errors, errors
            await browser.close()
            print('PASS: actual approval and verified receipts, live screenshot, pause, disconnect, mobile layout, no JS errors.')
    finally:
        request('/sessions/'+sid, method='DELETE')

if __name__=='__main__':
    asyncio.run(main())
