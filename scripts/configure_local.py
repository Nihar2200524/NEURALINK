"""Create local Docker credentials once, without printing secrets."""
import json
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / ".env"
if path.exists():
    print("Existing .env preserved.")
else:
    with path.open("x", encoding="utf-8") as stream:
        stream.write("AGENTRA_TOKENS=" + json.dumps({"local": secrets.token_urlsafe(32)}) + "\n")
        stream.write("AGENTRA_APPROVER_TOKEN=" + secrets.token_urlsafe(32) + "\n")
    print("Created local credentials in ignored .env; no secrets printed.")
