from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    project_name: str = Field(default="NK XiaoLingTong", alias="PROJECT_NAME")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    search_request_timeout_ms: int = Field(default=0, alias="SEARCH_REQUEST_TIMEOUT_MS")

    es_url: str = Field(default="http://localhost:9200", alias="ES_URL")
    es_index: str = Field(default="nku_pages", alias="ES_INDEX")
    es_request_timeout_seconds: float = Field(default=0.0, alias="ES_REQUEST_TIMEOUT_SECONDS")
    tika_url: str = Field(default="http://localhost:9998", alias="TIKA_URL")

    sqlite_url: str = Field(default="sqlite:////data/app.db", alias="SQLITE_URL")
    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=1440, alias="JWT_EXPIRE_MINUTES")

    semantic_enabled: bool = Field(default=True, alias="SEMANTIC_ENABLED")
    embedding_model_name: str = Field(default="BAAI/bge-small-zh-v1.5", alias="EMBEDDING_MODEL_NAME")
    embedding_model_path: str = Field(default="/data/models/bge-small-zh-v1.5", alias="EMBEDDING_MODEL_PATH")
    embedding_dim: int = Field(default=512, alias="EMBEDDING_DIM")
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")
    embedding_query_instruction: str = Field(
        default="Represent this sentence for retrieving relevant campus documents: ",
        alias="EMBEDDING_QUERY_INSTRUCTION",
    )
    semantic_text_max_chars: int = Field(default=3000, alias="SEMANTIC_TEXT_MAX_CHARS")
    vector_field_name: str = Field(default="content_vector", alias="VECTOR_FIELD_NAME")
    semantic_cache_dir: str = Field(default="/data/hf-cache", alias="SEMANTIC_CACHE_DIR")
    semantic_allow_remote_download: bool = Field(default=True, alias="SEMANTIC_ALLOW_REMOTE_DOWNLOAD")

    hybrid_lexical_top_k: int = Field(default=100, alias="HYBRID_LEXICAL_TOP_K")
    hybrid_vector_top_k: int = Field(default=100, alias="HYBRID_VECTOR_TOP_K")
    hybrid_vector_num_candidates: int = Field(default=300, alias="HYBRID_VECTOR_NUM_CANDIDATES")
    hybrid_rrf_k: int = Field(default=60, alias="HYBRID_RRF_K")
    hybrid_rrf_lexical_weight: float = Field(default=1.0, alias="HYBRID_RRF_LEXICAL_WEIGHT")
    hybrid_rrf_vector_weight: float = Field(default=1.0, alias="HYBRID_RRF_VECTOR_WEIGHT")
    hybrid_max_candidates: int = Field(default=150, alias="HYBRID_MAX_CANDIDATES")
    personalized_lexical_top_k: int = Field(default=30, alias="PERSONALIZED_LEXICAL_TOP_K")
    personalized_vector_top_k: int = Field(default=20, alias="PERSONALIZED_VECTOR_TOP_K")
    personalized_vector_num_candidates: int = Field(default=80, alias="PERSONALIZED_VECTOR_NUM_CANDIDATES")
    personalized_max_candidates: int = Field(default=120, alias="PERSONALIZED_MAX_CANDIDATES")

    reranker_enabled: bool = Field(default=False, alias="RERANKER_ENABLED")
    reranker_model_name: str = Field(default="BAAI/bge-reranker-v2-m3", alias="RERANKER_MODEL_NAME")
    reranker_model_path: str = Field(default="/data/models/bge-reranker-v2-m3", alias="RERANKER_MODEL_PATH")
    reranker_batch_size: int = Field(default=8, alias="RERANKER_BATCH_SIZE")
    reranker_top_k: int = Field(default=80, alias="RERANKER_TOP_K")
    reranker_timeout_seconds: float = Field(default=4.0, alias="RERANKER_TIMEOUT_SECONDS")
    reranker_text_max_chars: int = Field(default=1200, alias="RERANKER_TEXT_MAX_CHARS")

    ai_behavior_enabled: bool = Field(default=False, alias="AI_BEHAVIOR_ENABLED")
    zhipu_api_key: str = Field(default="", alias="ZHIPU_API_KEY")
    zhipu_api_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        alias="ZHIPU_API_URL",
    )
    zhipu_model: str = Field(default="glm-4-flash-250414", alias="ZHIPU_MODEL")
    ai_behavior_timeout_seconds: float = Field(default=20.0, alias="AI_BEHAVIOR_TIMEOUT_SECONDS")
    ai_behavior_min_refresh_seconds: int = Field(default=30, alias="AI_BEHAVIOR_MIN_REFRESH_SECONDS")
    ai_behavior_query_batch_size: int = Field(default=5, alias="AI_BEHAVIOR_QUERY_BATCH_SIZE")
    ai_behavior_max_queries: int = Field(default=20, alias="AI_BEHAVIOR_MAX_QUERIES")
    ai_behavior_max_clicks: int = Field(default=15, alias="AI_BEHAVIOR_MAX_CLICKS")

    @property
    def embedding_model_path_obj(self) -> Path:
        return Path(self.embedding_model_path)

    @property
    def reranker_model_path_obj(self) -> Path:
        return Path(self.reranker_model_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
