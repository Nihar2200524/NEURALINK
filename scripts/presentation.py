"""Open an authenticated presentation window without displaying credentials."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    root = Path(__file__).resolve().parents[1]
    config = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines() if '=' in line)
    token = json.loads(config['AGENTRA_TOKENS'])['local']
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto('http://127.0.0.1:8000/')
        await page.get_by_role('button', name='Connect', exact=True).click()
        await page.get_by_label('API token', exact=True).fill(token)
        await page.get_by_role('button', name='Connect live view').click()
        print('Presentation connected. Close the browser window to exit.')
        try:
            await page.wait_for_event('close', timeout=0)
        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
