import pytest
from agentra.config import BrowserSettings


def test_headed_environment(monkeypatch):
    monkeypatch.setenv("AGENTRA_HEADED", "true")
    monkeypatch.setenv("AGENTRA_SLOW_MO_MS", "300")
    settings = BrowserSettings.from_env()
    assert settings.headed
    assert settings.slow_mo_ms == 300


@pytest.mark.parametrize("key,value", [("AGENTRA_HEADED", "maybe"), ("AGENTRA_SLOW_MO_MS", "-1"), ("AGENTRA_SLOW_MO_MS", "2001")])
def test_invalid_settings(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        BrowserSettings.from_env()
