from fastapi.testclient import TestClient
from agentra.server import app, owned


def test_request_body_limit():
    client = TestClient(app)
    response = client.post('/sessions', content=b'x' * 262145)
    assert response.status_code == 413


def test_validation_does_not_echo_secrets(monkeypatch):
    monkeypatch.setenv('AGENTRA_TOKENS', '{"a":"' + 'a' * 40 + '"}')
    client = TestClient(app)
    app.dependency_overrides[owned] = lambda: object()
    try:
        response = client.post('/sessions/unknown/authorize', json={'action_id': 'id', 'auth_token': {'secret': 'DO_NOT_ECHO'}})
        assert response.status_code == 422
        assert 'DO_NOT_ECHO' not in response.text
    finally:
        app.dependency_overrides.clear()
