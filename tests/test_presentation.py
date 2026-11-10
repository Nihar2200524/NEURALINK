from types import SimpleNamespace
from fastapi.testclient import TestClient
from agentra.server import app, manager


def test_presentation_private_and_tenant_scoped(monkeypatch):
    monkeypatch.setenv('AGENTRA_TOKENS', '{"demo":"' + 'x' * 40 + '"}')
    monkeypatch.setattr(manager, 'sessions', {
        'other': SimpleNamespace(tenant='private'),
        'demo': SimpleNamespace(tenant='demo', id='demo', lifecycle='ACTIVE',
                                lock=SimpleNamespace(locked=lambda: False), results={}, pages={})})
    client = TestClient(app)
    assert client.get('/').status_code == 200
    assert client.get('/presentation').status_code == 401
    assert client.get('/sessions/demo/preview').status_code == 401
    response = client.get('/presentation', headers={'Authorization': 'Bearer ' + 'x' * 40})
    assert response.headers['cache-control'] == 'no-store'
    assert [s['id'] for s in response.json()['sessions']] == ['demo']
    assert 'private' not in response.text
