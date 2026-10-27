from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(None, max_length=2000)
    format: Literal["json", "markdown"] = "json"
    max_content_length: int = Field(12000, ge=100, le=100000)
    include_links: bool = True
    include_metadata: bool = True


class FetchRequest(Options):
    url: str = Field(min_length=1, max_length=4096)
    render: Literal["http", "auto", "browser"] = "http"


class ExtractRequest(Options):
    html: str = Field(min_length=1, max_length=2_000_000)
    url: str | None = Field(None, max_length=4096)


class BatchRequest(Options):
    urls: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(min_length=1, max_length=20)
    render: Literal["http", "auto", "browser"] = "http"
