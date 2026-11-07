from fastapi.testclient import TestClient
from agentra.server import app


def test_missing_auth():
    client = TestClient(app)
    assert client.get('/sessions/unknown/state').status_code == 401


def test_unknown_session_hidden(monkeypatch):
    monkeypatch.setenv('AGENTRA_TOKENS', '{"tenant":"' + 'x' * 40 + '"}')
    client = TestClient(app)
    response = client.get('/sessions/unknown/state', headers={'Authorization': 'Bearer ' + 'x' * 40})
    assert response.status_code == 404
