"""Real Ollama + Docker browser + UI integration check. Credentials stay local."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    root=Path(__file__).resolve().parents[1]
    config=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
    token=json.loads(config['AGENTRA_TOKENS'])['local']
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        page=await browser.new_page(viewport={'width':1440,'height':1100})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:8000/')
        await page.get_by_role('button',name='Connect',exact=True).click()
        await page.get_by_label('API token',exact=True).fill(token)
        await page.get_by_role('button',name='Connect live view').click()
        await page.get_by_label('Your task',exact=True).fill('Open https://example.com and tell me what this domain is for. Cite one exact quote from that page. Do not search; the source URL is provided.')
        await page.get_by_label('Approver credential',exact=True).fill(config['AGENTRA_APPROVER_TOKEN'])
        async with page.expect_response(lambda r:r.url.endswith('/tasks') and r.request.method=='POST') as response:
            await page.get_by_role('button',name='Authorize & run',exact=True).click()
        data=await(await response.value).json()
        task_id=data['id']
        headers={'Authorization':'Bearer '+token}
        last=''
        try:
            for _ in range(360):
                result=await page.request.get('http://127.0.0.1:8000/tasks/'+task_id,headers=headers)
                job=await result.json()
                events=job.get('events',[])
                detail=events[-1]['detail'] if events else job['status']
                if detail!=last:
                    print(detail,flush=True)
                    last=detail
                if job['status'] not in {'QUEUED','RUNNING'}:
                    break
                await asyncio.sleep(1)
            else:
                raise AssertionError('Task did not finish in six minutes')
            print(json.dumps({'status':job['status'],'answer':job['answer'],'evidence':job['evidence']}),flush=True)
            assert job['status']=='ANSWER_READY',job['status']
            await page.get_by_text('ANSWER READY',exact=True).wait_for(timeout=10000)
            await page.wait_for_function("document.getElementById('frame').naturalWidth>0")
            await page.screenshot(path=str(root/'presentation-preview.png'),full_page=True)
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors,errors
            print('PASS: real Qwen chose navigation, Agentra read the page, source quote validated, UI displayed answer and live frame.',flush=True)
        finally:
            await page.request.delete('http://127.0.0.1:8000/tasks/'+task_id,headers=headers)
            if job.get('session_id'):
                await page.request.delete('http://127.0.0.1:8000/sessions/'+job['session_id'],headers=headers)
            await browser.close()

if __name__=='__main__': asyncio.run(main())
