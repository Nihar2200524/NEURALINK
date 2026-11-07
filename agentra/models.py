from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Postcondition(Model):
    kind: Literal["url", "visible", "hidden", "text", "expanded"]
    selector: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=4000)


class Action(Model):
    kind: Literal["NAVIGATE", "CLICK", "TYPE", "SELECT_OPTION", "CHECK"]
    scoped_ref: str | None = None
    tab_id: str = "tab_0"
    url: str | None = Field(default=None, max_length=8192)
    text: str = Field(default="", max_length=100000)
    value: str = Field(default="", max_length=10000)
    press_enter: bool = False
    postcondition: Postcondition | None = None
    timeout_ms: int = Field(default=10000, ge=100, le=30000)

    @model_validator(mode="after")
    def validate_target(self) -> "Action":
        if self.kind == "NAVIGATE" and not self.url:
            raise ValueError("NAVIGATE requires url")
        if self.kind != "NAVIGATE" and not self.scoped_ref:
            raise ValueError("Element action requires scoped_ref")
        if (self.kind == "CLICK" or self.press_enter) and not self.postcondition:
            raise ValueError("CLICK and press_enter require an observable postcondition")
        return self


class Node(Model):
    ref: str
    role: str
    name: str


class State(Model):
    snapshot_version: str
    readiness: Literal["READY", "PARTIAL", "TIMEOUT"] = "PARTIAL"
    trust: Literal["untrusted_web_payload"] = "untrusted_web_payload"
    content: str = ""
    nodes: list[Node] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)
    truncated: bool = False
    tokens: int = 0


class Receipt(Model):
    status: Literal["VERIFIED", "AUTHORIZATION_REQUIRED", "STALE_REFERENCE_ERROR", "FAILED", "TIMEOUT"]
    action_id: str
    detail: str
    state: State | None = None


class Authorization(Model):
    action_id: str
    auth_token: str


class Inspect(Model):
    scoped_ref: str
    budget: int = Field(default=2500, ge=100, le=10000)
    depth: int = Field(default=5, ge=1, le=30)
    format: Literal["markdown", "json"] = "markdown"
