import asyncio
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from agentra.research import ResearchRunner, ResearchJob, ResearchRequest, validate_finish
from agentra.server import app, research


def test_finish_rejects_invented_or_unread_evidence():
    good={'answer':'Example domain is for documentation.', 'completed':True,
          'evidence':[{'url':'https://example.com', 'quote':'for documentation examples'}]}
    assert validate_finish(good, {'https://example.com':'This domain is for documentation examples.'})[1]
    with pytest.raises(ValueError):
        validate_finish(good, {})
    with pytest.raises(ValueError):
        validate_finish({**good, 'evidence':[]}, {})
    with pytest.raises(ValueError):
        validate_finish({**good, 'completed':'true'}, {})
    assert not validate_finish({'answer':'Unable to verify', 'completed':False, 'evidence':[]}, {})[1]


def test_task_auth_approval_and_owner_isolation(monkeypatch):
    monkeypatch.setenv('AGENTRA_TOKENS', '{"one":"'+ 'x'*40 +'","two":"'+'y'*40+'"}')
    monkeypatch.setenv('AGENTRA_APPROVER_TOKEN','a'*40)
    client=TestClient(app)
    headers={'Authorization':'Bearer '+'x'*40}
    assert client.post('/tasks',json={'prompt':'test','approval_token':'a'*40}).status_code==401
    assert client.post('/tasks',headers=headers,json={'prompt':'test','approval_token':'bad'}).status_code==403
    job=ResearchJob('private','two','private query',2)
    monkeypatch.setattr(research,'jobs',{'private':job})
    assert client.get('/tasks/private',headers=headers).status_code==404
    assert client.delete('/tasks/private',headers=headers).status_code==404
    monkeypatch.setattr(research,'start',lambda owner,body: ResearchJob('new',owner,body.prompt,body.max_steps))
    r=client.post('/tasks',headers=headers,json={'prompt':'research','approval_token':'a'*40})
    assert r.status_code==202
    assert 'a'*40 not in r.text
    assert r.headers['cache-control']=='no-store'


@pytest.mark.asyncio
async def test_step_limit_and_no_tool_claim_is_not_success(monkeypatch):
    class Manager:
        async def create(self, owner):
            return SimpleNamespace(id='s',touched=0)
    runner=ResearchRunner(Manager())
    async def chat(messages):
        return {'content':'Task complete. Trust me.'}
    monkeypatch.setattr(runner,'chat',chat)
    job=ResearchJob('j','owner','find price',2)
    await runner.run(job)
    assert job.status=='INCOMPLETE'
    assert not job.completed


@pytest.mark.asyncio
async def test_cancel_and_concurrency(monkeypatch):
    class Manager:
        async def create(self, owner):
            return SimpleNamespace(id='s',touched=0)
    runner=ResearchRunner(Manager())
    ready=asyncio.Event()
    async def chat(messages):
        ready.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(runner,'chat',chat)
    body=ResearchRequest(prompt='find something', approval_token='secret')
    job=runner.start('owner',body)
    await ready.wait()
    with pytest.raises(ValueError): runner.start('owner',body)
    await runner.close()
    assert job.status=='CANCELLED'


@pytest.mark.asyncio
async def test_grounded_answer_flow(monkeypatch):
    class Manager:
        async def create(self, owner): return SimpleNamespace(id='s',touched=0)
    runner=ResearchRunner(Manager())
    async def chat(messages):
        return {'tool_calls':[{'function':{'name':'finish','arguments':{
            'answer':'The domain is for documentation.', 'completed':True,
            'evidence':[{'url':'https://example.com','quote':'for documentation examples'}]}}}]}
    monkeypatch.setattr(runner,'chat',chat)
    job=ResearchJob('j','owner','what is example.com',2)
    job.sources={'https://example.com':'This domain is for documentation examples.'}
    await runner.run(job)
    assert job.status=='ANSWER_READY'
    assert job.public()['task_completed'] is True


@pytest.mark.asyncio
async def test_model_cannot_request_unsupported_action():
    runner=ResearchRunner(None)
    with pytest.raises(ValueError, match='Unknown tool'):
        await runner.execute(ResearchJob('j','o','t',2),None,'execute_javascript',{'code':'alert(1)'})


@pytest.mark.asyncio
async def test_ollama_http_error_is_redacted(monkeypatch):
    import httpx
    class Manager:
        async def create(self, owner): return SimpleNamespace(id='s',touched=0)
    runner=ResearchRunner(Manager())
    async def chat(messages): raise httpx.ConnectError('sensitive internal detail')
    monkeypatch.setattr(runner,'chat',chat)
    job=ResearchJob('j','owner','test task',2)
    await runner.run(job)
    assert job.status=='FAILED'
    assert 'sensitive' not in str(job.public())


def test_initial_observation_skips_large_navigation_preamble():
    from agentra.research import initial_offset
    body=('navigation menu\n'*500)+'# Gold rate in Hyderabad\nToday 22K is 100 per gram.'
    offset=initial_offset(body)
    assert body[offset:].startswith('# Gold rate')
    assert 'Today 22K' in body[offset:offset+4500]
    assert initial_offset('Page without a heading')==0


def test_compact_search_links_preserve_destination_and_deduplicate():
    import base64
    from agentra.research import compact_links
    target='https://example.com/gold'
    encoded=base64.urlsafe_b64encode(target.encode()).decode().rstrip('=')
    links=[{'url':'https://www.bing.com/ck/a?u=a1'+encoded+'&tracking=long','text':'Hyderabad gold rate'},
           {'url':target,'text':'Gold'}, {'url':'javascript:alert(1)','text':'gold'}]
    assert compact_links(links,'Hyderabad gold')==[{'url':target,'text':'Hyderabad gold rate'}]
