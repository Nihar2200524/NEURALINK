"""Verify the running local Docker API without exposing credentials."""
import json
from pathlib import Path
import urllib.request

config = dict(line.split("=", 1) for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines() if "=" in line)
token = json.loads(config["AGENTRA_TOKENS"])["local"]

def request(path, method="GET", body=None):
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "Idempotency-Key": "container-smoke"}
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000" + path, data=data, headers=headers, method=method), timeout=45) as response:
        raw = response.read()
        return json.loads(raw) if raw else None

assert request("/health")["status"] == "ready"
sid = request("/sessions", "POST")["session_id"]
try:
    action = request(f"/sessions/{sid}/actions", "POST", {"kind": "NAVIGATE", "url": "https://example.com", "timeout_ms": 30000})
    assert action["status"] == "AUTHORIZATION_REQUIRED"
    receipt = request(f"/sessions/{sid}/authorize", "POST", {"action_id": action["action_id"], "auth_token": config["AGENTRA_APPROVER_TOKEN"]})
    assert receipt["status"] == "VERIFIED", receipt["detail"]
    state = request(f"/sessions/{sid}/state")
    assert state["nodes"]
    print("PASS: health, session creation, authorization gate, HTTPS navigation, semantic snapshot.")
finally:
    request(f"/sessions/{sid}", "DELETE")
    print("Smoke session cleaned up.")
