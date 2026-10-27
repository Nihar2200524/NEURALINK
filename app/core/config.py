from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRIDGE_", env_file=".env", extra="ignore")
    timeout: float = Field(15, gt=0)
    max_response_bytes: int = Field(2_000_000, gt=0)
    max_request_bytes: int = Field(3_000_000, gt=0)
    max_redirects: int = Field(5, ge=0, le=10)
    concurrency: int = Field(8, ge=1, le=64)
    cache_ttl: int = Field(300, ge=0)
    cache_entries: int = Field(128, ge=1)
    respect_robots: bool = True
    browser_enabled: bool = False
    user_agent: str = "AIWebBridge/0.1"
