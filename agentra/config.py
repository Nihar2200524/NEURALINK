"""Server-controlled browser display settings."""
import os
from pydantic import BaseModel, ConfigDict, Field


class BrowserSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    headed: bool = False
    slow_mo_ms: int = Field(default=0, ge=0, le=2000)
    max_sessions: int = Field(default=8, ge=1, le=100)
    session_memory_mb: int = Field(default=1024, ge=128, le=16384)
    max_tabs: int = Field(default=12, ge=1, le=100)

    @classmethod
    def from_env(cls) -> "BrowserSettings":
        value = os.getenv("AGENTRA_HEADED", "false").strip().lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError("AGENTRA_HEADED must be true, false, 1 or 0")
        return cls(headed=value in {"true", "1"}, slow_mo_ms=int(os.getenv("AGENTRA_SLOW_MO_MS", "0")),
                   max_sessions=int(os.getenv("AGENTRA_MAX_SESSIONS", "8")),
                   session_memory_mb=int(os.getenv("AGENTRA_SESSION_MEMORY_MB", "1024")),
                   max_tabs=int(os.getenv("AGENTRA_MAX_TABS", "12")))
