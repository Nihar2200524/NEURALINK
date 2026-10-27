from pydantic import BaseModel, Field


class Link(BaseModel):
    text: str
    url: str


class ContentBlock(BaseModel):
    id: str
    tag: str
    text: str
    heading: str = ""
    score: float = 0
    relevance_score: float = 0
    links: list[Link] = Field(default_factory=list)
    position: int = 0


class Page(BaseModel):
    title: str = ""
    description: str = ""
    canonical_url: str | None = None
    language: str | None = None


class Section(BaseModel):
    heading: str
    text: str
    relevance_score: float


class Content(BaseModel):
    main_text: str
    sections: list[Section]


class Optimization(BaseModel):
    raw_bytes: int
    raw_text_characters: int
    returned_characters: int
    reduction_percent: float
    estimated_raw_tokens: int
    estimated_clean_tokens: int
    estimated_returned_tokens: int
    estimated_tokens_saved: int
    token_reduction_percent: float


class BridgeResponse(BaseModel):
    request: dict
    page: Page
    content: Content
    links: list[Link]
    metadata: dict | None
    optimization: Optimization
    actions: list[dict] = Field(default_factory=list)
