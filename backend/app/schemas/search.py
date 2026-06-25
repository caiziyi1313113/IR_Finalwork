from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    doc_id: str
    title: str
    url: str
    snippet: str
    site_name: str
    doc_kind: str
    departments: list[str] = Field(default_factory=list)
    publish_time: str | None = None
    file_extension: str | None = None
    score: float
    raw_es_score: float
    bm25_component: float
    vector_component: float = 0.0
    hybrid_component: float = 0.0
    rerank_component: float = 0.0
    similarity_component: float = 0.0
    pagerank: float
    pagerank_component: float
    profile_component: float = 0.0
    profile_match_component: float = 0.0
    source_group: str = "base"
    snapshot_url: str


class SearchStrategyResult(BaseModel):
    key: str
    label: str
    description: str
    hits: list[SearchHit]


class SearchResponse(BaseModel):
    query: str
    corrected_query: str | None = None
    total: int
    page: int
    size: int
    took_ms: int
    active_strategy: str = "personalized"
    personalization_enabled: bool = False
    strategies: list[SearchStrategyResult]


class CorrectionHint(BaseModel):
    corrected_text: str
    wrong_start: int
    wrong_end: int
    message: str


class SuggestionResponse(BaseModel):
    prefix: str
    correction: CorrectionHint | None = None
    suggestions: list[str]


class ClickRequest(BaseModel):
    doc_id: str
    query_text: str | None = None


class ClickResponse(BaseModel):
    success: bool = True


class RecommendationItem(BaseModel):
    doc_id: str
    title: str
    url: str
    reason: str = Field(description="推荐理由")


class RecommendationList(BaseModel):
    profile_tags: list[str] = Field(default_factory=list)
    items: list[RecommendationItem]
