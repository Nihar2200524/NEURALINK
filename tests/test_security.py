import socket
import pytest
from fastapi import HTTPException
from agentra.security import validate_url, tenant_for_token, verify_approval
from agentra.models import Action


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost", "http://127.0.0.1", "http://169.254.169.254", "http://10.0.0.1", "http://[::1]", "http://[::ffff:127.0.0.1]", "https://user:pass@example.com"])
async def test_ssrf(url):
    with pytest.raises(ValueError):
        await validate_url(url)


def test_auth(monkeypatch):
    monkeypatch.setenv("AGENTRA_TOKENS", '{"tenant-a":"' + 'a' * 40 + '"}')
    assert tenant_for_token("Bearer " + "a" * 40) == "tenant-a"
    with pytest.raises(HTTPException):
        tenant_for_token("Bearer wrong")
    assert not verify_approval("wrong")


def test_click_requires_evidence():
    with pytest.raises(ValueError):
        Action(kind="CLICK", scoped_ref="snap_1::tab_0::frame_0::@e0")
