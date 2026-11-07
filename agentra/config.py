"""Server-controlled browser display settings."""
import os
from pydantic import BaseModel, ConfigDict, Field


class BrowserSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    headed: bool = False
    slow_mo_ms: int = Field(default=0, ge=0, le=2000)

    @classmethod
    def from_env(cls) -> "BrowserSettings":
        value = os.getenv("AGENTRA_HEADED", "false").strip().lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError("AGENTRA_HEADED must be true, false, 1 or 0")
        return cls(headed=value in {"true", "1"}, slow_mo_ms=int(os.getenv("AGENTRA_SLOW_MO_MS", "0")))
