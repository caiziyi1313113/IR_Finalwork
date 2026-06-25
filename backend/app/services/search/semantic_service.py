from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import Settings, get_settings
from app.models.user import User

try:
    from sentence_transformers import CrossEncoder, SentenceTransformer
except ImportError:  # pragma: no cover
    CrossEncoder = None
    SentenceTransformer = None


def build_document_semantic_text(source: dict, max_chars: int | None = None) -> str:
    parts: list[str] = []

    title = str(source.get("title", "") or "").strip()
    if title:
        parts.append(f"title: {title}")

    site_name = str(source.get("site_name", "") or "").strip()
    if site_name:
        parts.append(f"site: {site_name}")

    departments = [str(item).strip() for item in source.get("departments", []) or [] if str(item).strip()]
    if departments:
        parts.append(f"departments: {' '.join(departments)}")

    content_type = str(source.get("content_type", "") or "").strip()
    if content_type:
        parts.append(f"content_type: {content_type}")

    anchor_texts = str(source.get("anchor_texts", "") or "").strip()
    if anchor_texts:
        parts.append(f"anchors: {anchor_texts[:400]}")

    content = str(source.get("content", "") or "").strip()
    if max_chars:
        content = content[:max_chars]
    if content:
        parts.append(f"content: {content}")

    if not parts:
        parts.append("empty document")
    return "\n".join(parts)


def build_user_profile_text(user: User | None) -> str:
    if user is None:
        return ""

    parts: list[str] = []
    if user.college.strip():
        parts.append(f"college: {user.college.strip()}")
    if user.major.strip():
        parts.append(f"major: {user.major.strip()}")
    tags = user.get_interest_tags()
    if tags:
        parts.append(f"interest_tags: {' '.join(tags)}")
    return "; ".join(parts)


def normalize_score_list(values: list[float], default: float = 0.0) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if math.isclose(low, high):
        return [default if math.isclose(high, 0.0) else 1.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def sigmoid_score(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


class SemanticService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._embedding_model = None
        self._reranker_model = None

    def preload_indexing_models(self) -> None:
        try:
            self._ensure_embedding_model()
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(self._build_model_error_message("embedding", exc)) from exc

    def _ensure_embedding_model(self):
        if SentenceTransformer is None:
            raise RuntimeError(
                "sentence-transformers is not installed. Run `docker compose build api` first."
            )
        if self._embedding_model is None:
            model_source = self._resolve_model_source(
                local_path=self.settings.embedding_model_path_obj,
                remote_name=self.settings.embedding_model_name,
                model_kind="embedding",
            )
            self._embedding_model = SentenceTransformer(
                model_source,
                device=self.settings.embedding_device,
                cache_folder=self.settings.semantic_cache_dir,
                local_files_only=self._use_local_only(self.settings.embedding_model_path_obj),
            )
        return self._embedding_model

    def _ensure_reranker_model(self):
        if not self.settings.reranker_enabled:
            return None
        if CrossEncoder is None:
            raise RuntimeError(
                "sentence-transformers is not installed. Run `docker compose build api` first."
            )
        if self._reranker_model is None:
            local_path = self.settings.reranker_model_path_obj
            if not local_path.exists():
                raise RuntimeError(
                    f"reranker model directory not found: `{local_path}`. "
                    "Place the downloaded reranker model there or set `RERANKER_ENABLED=false`."
                )
            self._reranker_model = CrossEncoder(
                str(local_path),
                device=self.settings.embedding_device,
                local_files_only=True,
            )
        return self._reranker_model

    def _resolve_model_source(self, local_path: Path, remote_name: str, model_kind: str) -> str:
        if local_path.exists():
            return str(local_path)
        if self.settings.semantic_allow_remote_download:
            return remote_name
        raise RuntimeError(
            f"{model_kind} model not found. Local path `{local_path}` does not exist "
            "and remote download is disabled."
        )

    def _use_local_only(self, local_path: Path) -> bool:
        return local_path.exists() or not self.settings.semantic_allow_remote_download

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            model = self._ensure_embedding_model()
            vectors = model.encode(
                texts,
                batch_size=self.settings.embedding_batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            return [vector.astype(np.float32).tolist() for vector in vectors]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(self._build_model_error_message("embedding", exc)) from exc

    def encode_query(self, text: str) -> list[float]:
        normalized_text = text.strip()
        if not normalized_text:
            return []
        try:
            model = self._ensure_embedding_model()
            query_text = f"{self.settings.embedding_query_instruction}{normalized_text}"
            vector = model.encode(
                [query_text],
                batch_size=1,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )[0]
            return vector.astype(np.float32).tolist()
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(self._build_model_error_message("embedding", exc)) from exc

    def cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        left_array = np.asarray(left, dtype=np.float32)
        right_array = np.asarray(right, dtype=np.float32)
        return float(np.dot(left_array, right_array))

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents or not self.settings.reranker_enabled:
            return []
        try:
            model = self._ensure_reranker_model()
            pairs = [(query, document) for document in documents]
            raw_scores = model.predict(
                pairs,
                batch_size=self.settings.reranker_batch_size,
                show_progress_bar=False,
            )
            return [sigmoid_score(float(score)) for score in raw_scores]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(self._build_model_error_message("reranker", exc)) from exc

    def _build_model_error_message(self, model_kind: str, exc: Exception) -> str:
        local_path = (
            self.settings.embedding_model_path_obj
            if model_kind == "embedding"
            else self.settings.reranker_model_path_obj
        )
        remote_name = (
            self.settings.embedding_model_name
            if model_kind == "embedding"
            else self.settings.reranker_model_name
        )
        recovery_hint = (
            "To continue without semantic indexing, set `SEMANTIC_ENABLED=false` in `.env` and recreate the api container."
            if model_kind == "embedding"
            else "To continue without reranking, set `RERANKER_ENABLED=false` in `.env` and recreate the api container."
        )
        return (
            f"Failed to load {model_kind} model. "
            f"Local path: `{local_path}`. "
            f"Remote name: `{remote_name}`. "
            f"Cache dir: `{self.settings.semantic_cache_dir}`. "
            f"Original error: {exc}. "
            f"{recovery_hint}"
        )


@lru_cache
def get_semantic_service() -> SemanticService:
    return SemanticService(get_settings())
