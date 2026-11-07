"""Run an explicitly requested read-only web search through local Agentra."""
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError

config = dict(line.split("=", 1) for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines() if "=" in line)
token = json.loads(config["AGENTRA_TOKENS"])["local"]

def request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "Idempotency-Key": uuid.uuid4().hex}
    with urlopen(Request("http://127.0.0.1:8000" + path, data=data, headers=headers, method=method), timeout=45) as response:
        return json.loads(response.read() or b"null")

query = " ".join(sys.argv[1:]) or "Hyderabad gold rate today"
url = query if query.startswith("https://") else "https://www.bing.com/search?q=" + quote_plus(query)
sid = request("/sessions", "POST")["session_id"]
started = time.monotonic()
try:
    action = request(f"/sessions/{sid}/actions", "POST", {"kind": "NAVIGATE", "url": url, "timeout_ms": 30000})
    if action["status"] == "AUTHORIZATION_REQUIRED":
        action = request(f"/sessions/{sid}/authorize", "POST", {"action_id": action["action_id"], "auth_token": config["AGENTRA_APPROVER_TOKEN"]})
    print(json.dumps({"url": url, "status": action["status"], "detail": action["detail"], "seconds": round(time.monotonic()-started, 2)}))
    observation = request(f"/sessions/{sid}/read")
    print(json.dumps(observation, ensure_ascii=True))
finally:
    request(f"/sessions/{sid}", "DELETE")
