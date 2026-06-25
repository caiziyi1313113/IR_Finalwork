from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.elastic import get_es_client
from app.models.click_log import ClickLog
from app.models.query_log import QueryLog
from app.models.user import User
from app.schemas.search import (
    ClickRequest,
    ClickResponse,
    CorrectionHint,
    RecommendationItem,
    RecommendationList,
    SearchHit,
    SearchResponse,
    SearchStrategyResult,
    SuggestionResponse,
)
from app.services.search.ai_behavior_profile import (
    get_cached_ai_profile,
    get_behavior_tags,
)
from app.services.search.personalization import (
    PersonalizationContext,
    build_personalization_context,
    compute_profile_vector_score,
)
from app.services.search.query_personalization import (
    QueryPersonalizationPlan,
    select_query_personalization,
)
from app.services.search.semantic_service import (
    build_document_semantic_text,
    build_user_profile_text,
    get_semantic_service,
    normalize_score_list,
)
from app.services.search.suggestion import fetch_query_correction, fetch_suggestions
from app.services.search.text_utils import contains_cjk, joined_text
from app.services.search.user_profile import build_user_behavior_profile

DOCUMENT_KINDS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx"}
PHRASE_WILDCARD_MODES = {"phrase", "wildcard"}
DEFAULT_RECALL_K = 10
DEFAULT_CANDIDATE_K = 20
DEFAULT_RESULT_K = 10


@dataclass
class SearchExecution:
    total: int
    took_ms: int
    features: list["RankFeatures"]


@dataclass
class RankFeatures:
    rank_index: int
    doc_id: str
    title: str
    url: str
    snippet: str
    site_name: str
    doc_kind: str
    departments: list[str]
    publish_time: str | None
    file_extension: str | None
    pagerank: float
    snapshot_url: str
    raw_es_score: float
    bm25_component: float
    vector_component: float
    hybrid_component: float
    rerank_component: float
    similarity_component: float
    pagerank_component: float
    profile_component: float
    profile_match_component: float
    semantic_text: str
    doc_vector: list[float]
    source_group: str = "base"


class SearchService:
    def __init__(self, db: Session):
        self.db = db
        self.settings: Settings = get_settings()
        self.es = get_es_client()
        self.semantic_service = get_semantic_service()

    async def search(
        self,
        query: str,
        mode: str,
        page: int,
        size: int,
        phrase_slop: int,
        current_user: User | None,
    ) -> SearchResponse:
        started_at = perf_counter()
        corrected_query = await self._maybe_correct_query(query)
        effective_query = corrected_query or query

        behavior_profile = await build_user_behavior_profile(
            user_id=current_user.id if current_user else None,
            db=self.db,
        )
        profile_vector = await self._build_profile_vector(current_user)
        personalization_context = build_personalization_context(
            current_user,
            profile_vector,
            behavior_profile.weighted_queries,
        )

        plan_task: asyncio.Task[QueryPersonalizationPlan] | None = None
        if current_user and mode not in PHRASE_WILDCARD_MODES:
            plan_task = asyncio.create_task(select_query_personalization(effective_query, current_user))

        if mode in PHRASE_WILDCARD_MODES:
            base_execution = await self._run_lexical_search(
                effective_query,
                mode,
                phrase_slop,
                top_k=DEFAULT_RESULT_K,
                apply_reranker=False,
            )
        elif self.settings.semantic_enabled:
            base_execution = await self._run_hybrid_search(
                effective_query,
                mode,
                phrase_slop,
                lexical_top_k=min(self.settings.hybrid_lexical_top_k, DEFAULT_RECALL_K),
                vector_top_k=min(self.settings.hybrid_vector_top_k, DEFAULT_RECALL_K),
                vector_num_candidates=min(self.settings.hybrid_vector_num_candidates, 50),
                max_candidates=min(self.settings.hybrid_max_candidates, DEFAULT_CANDIDATE_K),
                final_top_k=DEFAULT_RESULT_K,
            )
        else:
            base_execution = await self._run_lexical_search(
                effective_query,
                mode,
                phrase_slop,
                top_k=DEFAULT_RESULT_K,
                apply_reranker=self.settings.reranker_enabled,
            )

        base_features = self._attach_pagerank_and_profile(base_execution.features, personalization_context)
        personalized_features = base_features
        personalization_enabled = False

        if plan_task is not None:
            plan = await plan_task
            if plan.selected_tags and plan.expanded_query.strip():
                personalized_features = await self._build_personalized_feature_pool(
                    query=effective_query,
                    mode=mode,
                    phrase_slop=phrase_slop,
                    base_features=base_features,
                    personalization_context=personalization_context,
                    plan=plan,
                )
                personalization_enabled = True

        strategies = self._build_strategy_results(
            base_features=base_features,
            personalized_features=personalized_features,
            page=page,
            size=size,
            personalization_enabled=personalization_enabled,
        )

        self._log_query(
            current_user=current_user,
            query_text=query,
            corrected_query=corrected_query,
            mode=mode,
            result_count=len(personalized_features),
        )

        return SearchResponse(
            query=query,
            corrected_query=corrected_query,
            total=len(personalized_features),
            page=page,
            size=size,
            took_ms=int((perf_counter() - started_at) * 1000),
            active_strategy="personalized",
            personalization_enabled=personalization_enabled,
            strategies=strategies,
        )

    async def suggest(self, prefix: str, current_user: User | None) -> SuggestionResponse:
        correction = await fetch_query_correction(prefix=prefix)
        suggestions = await fetch_suggestions(prefix=prefix, db=self.db, current_user=current_user)
        return SuggestionResponse(
            prefix=prefix,
            correction=CorrectionHint(**correction.__dict__) if correction else None,
            suggestions=list(dict.fromkeys(suggestions))[:10],
        )

    async def recommend(self, current_user: User) -> RecommendationList:
        fixed_tags = self._build_fixed_recommendation_tags(current_user)
        dynamic_tags = self._build_dynamic_recommendation_tags(current_user)
        mixed_groups, used_dynamic_tags = self._build_mixed_recommendation_groups(
            fixed_tags=fixed_tags,
            dynamic_tags=dynamic_tags,
            limit=4,
        )
        remaining_dynamic_tags = [tag for tag in dynamic_tags if tag not in set(used_dynamic_tags)]
        dynamic_groups = self._build_dynamic_recommendation_groups(
            dynamic_tags=remaining_dynamic_tags,
            limit=4,
        )
        query_groups = [*mixed_groups, *dynamic_groups]
        items = await self._collect_group_recommendations(query_groups)

        if not items:
            if mixed_groups:
                fallback_query = joined_text(mixed_groups[0])
            elif dynamic_groups:
                fallback_query = joined_text(dynamic_groups[0])
            else:
                fallback_query = joined_text(fixed_tags) or "南开大学 通知公告 培养方案 招生信息"
            fallback_execution = await self._run_lexical_search(
                fallback_query,
                mode="normal",
                phrase_slop=0,
                top_k=3,
                apply_reranker=False,
            )
            fallback_ranked = sorted(
                fallback_execution.features,
                key=lambda item: (-item.similarity_component, item.rank_index),
            )
            if fallback_ranked:
                first_item = fallback_ranked[0]
                items = [
                    RecommendationItem(
                        doc_id=first_item.doc_id,
                        title=first_item.title,
                        url=first_item.url,
                        reason=f"BM25 推荐查询：{fallback_query}",
                    )
                ]

        return RecommendationList(
            profile_tags=self._dedupe_recommendation_terms([tag for group in query_groups for tag in group]),
            items=items,
        )

    def get_recent_queries(self, user_id: int, limit: int) -> list[str]:
        fetch_limit = min(max(limit * 8, 100), 500)
        rows = self.db.scalars(
            select(QueryLog.query_text)
            .where(QueryLog.user_id == user_id)
            .order_by(desc(QueryLog.created_at))
            .limit(fetch_limit)
        ).all()
        unique_queries: list[str] = []
        seen: set[str] = set()
        for query_text in rows:
            text = str(query_text or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique_queries.append(text)
            if len(unique_queries) >= limit:
                break
        return unique_queries

    def record_click(self, payload: ClickRequest, current_user: User | None) -> ClickResponse:
        click = ClickLog(
            user_id=current_user.id if current_user else None,
            doc_id=payload.doc_id,
            query_text=payload.query_text,
        )
        self.db.add(click)
        self.db.commit()
        return ClickResponse(success=True)

    async def _run_lexical_search(
        self,
        query: str,
        mode: str,
        phrase_slop: int,
        top_k: int,
        apply_reranker: bool = False,
    ) -> SearchExecution:
        response = await self.es.search(
            index=self.settings.es_index,
            query=self._build_es_query(query, mode, phrase_slop),
            size=top_k,
            highlight={"fields": {"content": {}, "title": {}}},
        )

        raw_hits = response.get("hits", {}).get("hits", [])
        raw_scores = [float(hit.get("_score", 0.0) or 0.0) for hit in raw_hits]
        bm25_components = _normalize_by_max(raw_scores)

        features: list[RankFeatures] = []
        for index, hit in enumerate(raw_hits):
            source = hit.get("_source", {})
            features.append(
                RankFeatures(
                    rank_index=index,
                    doc_id=hit["_id"],
                    title=str(source.get("title", "") or "未命名文档"),
                    url=str(source.get("url", "#") or "#"),
                    snippet=self._build_snippet(hit),
                    site_name=str(source.get("site_name", "") or "鏈煡绔欑偣"),
                    doc_kind=str(source.get("doc_kind", "") or "html"),
                    departments=list(source.get("departments", [])),
                    publish_time=source.get("publish_time"),
                    file_extension=source.get("file_extension"),
                    pagerank=float(source.get("pagerank", 0.0) or 0.0),
                    snapshot_url=f"/api/snapshot/{hit['_id']}",
                    raw_es_score=float(hit.get("_score", 0.0) or 0.0),
                    bm25_component=bm25_components[index],
                    vector_component=0.0,
                    hybrid_component=bm25_components[index],
                    rerank_component=0.0,
                    similarity_component=bm25_components[index],
                    pagerank_component=0.0,
                    profile_component=0.0,
                    profile_match_component=0.0,
                    semantic_text=build_document_semantic_text(source, self.settings.semantic_text_max_chars),
                    doc_vector=list(source.get(self.settings.vector_field_name, []) or []),
                )
            )

        if apply_reranker:
            features = await self._apply_reranker(query, features, final_top_k=min(top_k, DEFAULT_RESULT_K))

        return SearchExecution(
            total=int(response.get("hits", {}).get("total", {}).get("value", len(features))),
            took_ms=int(response.get("took", 0)),
            features=self._reindex_features(features),
        )

    async def _run_hybrid_search(
        self,
        query: str,
        mode: str,
        phrase_slop: int,
        lexical_top_k: int,
        vector_top_k: int,
        vector_num_candidates: int,
        max_candidates: int,
        final_top_k: int,
    ) -> SearchExecution:
        try:
            query_vector = await asyncio.to_thread(self.semantic_service.encode_query, query)
            if not query_vector:
                return await self._run_lexical_search(
                    query,
                    mode,
                    phrase_slop,
                    top_k=final_top_k,
                    apply_reranker=self.settings.reranker_enabled,
                )

            lexical_response = await self.es.search(
                index=self.settings.es_index,
                query=self._build_es_query(query, mode, phrase_slop),
                size=lexical_top_k,
                highlight={"fields": {"content": {}, "title": {}}},
            )
            vector_response = await self.es.search(
                index=self.settings.es_index,
                knn=self._build_knn_request(
                    query_vector=query_vector,
                    mode=mode,
                    vector_top_k=vector_top_k,
                    vector_num_candidates=vector_num_candidates,
                ),
                size=vector_top_k,
            )
        except Exception as exc:  # pragma: no cover
            print(f"Hybrid search fallback to lexical search: {exc}")
            return await self._run_lexical_search(
                query,
                mode,
                phrase_slop,
                top_k=final_top_k,
                apply_reranker=self.settings.reranker_enabled,
            )

        lexical_hits = lexical_response.get("hits", {}).get("hits", [])
        vector_hits = vector_response.get("hits", {}).get("hits", [])
        candidate_map: dict[str, dict[str, Any]] = {}

        lexical_scores = [float(hit.get("_score", 0.0) or 0.0) for hit in lexical_hits]
        lexical_components = _normalize_by_max(lexical_scores)

        for rank, hit in enumerate(lexical_hits, start=1):
            doc_id = hit["_id"]
            candidate_map[doc_id] = {
                "source": hit.get("_source", {}),
                "snippet": self._build_snippet(hit),
                "lexical_rank": rank,
                "vector_rank": None,
                "raw_es_score": float(hit.get("_score", 0.0) or 0.0),
                "bm25_component": lexical_components[rank - 1],
            }

        for rank, hit in enumerate(vector_hits, start=1):
            doc_id = hit["_id"]
            state = candidate_map.setdefault(
                doc_id,
                {
                    "source": hit.get("_source", {}),
                    "snippet": self._build_snippet(hit),
                    "lexical_rank": None,
                    "vector_rank": None,
                    "raw_es_score": 0.0,
                    "bm25_component": 0.0,
                },
            )
            state["vector_rank"] = rank
            if not state.get("snippet"):
                state["snippet"] = self._build_snippet(hit)

        ordered_candidates = list(candidate_map.items())
        vector_scores: list[float] = []
        for _doc_id, state in ordered_candidates:
            doc_vector = state["source"].get(self.settings.vector_field_name) or []
            vector_scores.append(self.semantic_service.cosine_similarity(query_vector, doc_vector))
        vector_components = [_cosine_to_unit(score) for score in vector_scores]

        rrf_scores: list[float] = []
        for _doc_id, state in ordered_candidates:
            score = 0.0
            if state["lexical_rank"] is not None:
                score += self.settings.hybrid_rrf_lexical_weight / (
                    self.settings.hybrid_rrf_k + state["lexical_rank"]
                )
            if state["vector_rank"] is not None:
                score += self.settings.hybrid_rrf_vector_weight / (
                    self.settings.hybrid_rrf_k + state["vector_rank"]
                )
            rrf_scores.append(score)
        hybrid_components = normalize_score_list(rrf_scores)

        scored_features: list[RankFeatures] = []
        for index, ((doc_id, state), vector_component, hybrid_component) in enumerate(
            zip(ordered_candidates, vector_components, hybrid_components, strict=False)
        ):
            source = state["source"]
            scored_features.append(
                RankFeatures(
                    rank_index=index,
                    doc_id=doc_id,
                    title=str(source.get("title", "") or "未命名文档"),
                    url=str(source.get("url", "#") or "#"),
                    snippet=state["snippet"],
                    site_name=str(source.get("site_name", "") or "鏈煡绔欑偣"),
                    doc_kind=str(source.get("doc_kind", "") or "html"),
                    departments=list(source.get("departments", [])),
                    publish_time=source.get("publish_time"),
                    file_extension=source.get("file_extension"),
                    pagerank=float(source.get("pagerank", 0.0) or 0.0),
                    snapshot_url=f"/api/snapshot/{doc_id}",
                    raw_es_score=state["raw_es_score"],
                    bm25_component=state["bm25_component"],
                    vector_component=vector_component,
                    hybrid_component=hybrid_component,
                    rerank_component=0.0,
                    similarity_component=hybrid_component,
                    pagerank_component=0.0,
                    profile_component=0.0,
                    profile_match_component=0.0,
                    semantic_text=build_document_semantic_text(source, self.settings.semantic_text_max_chars),
                    doc_vector=list(source.get(self.settings.vector_field_name, []) or []),
                )
            )

        scored_features.sort(
            key=lambda item: (-item.hybrid_component, -item.bm25_component, -item.vector_component, item.rank_index)
        )
        scored_features = scored_features[:max_candidates]
        reranked = await self._apply_reranker(query, scored_features, final_top_k=final_top_k)

        total = max(
            int(lexical_response.get("hits", {}).get("total", {}).get("value", len(reranked))),
            len(reranked),
        )
        took_ms = int(lexical_response.get("took", 0)) + int(vector_response.get("took", 0))
        return SearchExecution(
            total=total,
            took_ms=took_ms,
            features=self._reindex_features(reranked),
        )

    async def _apply_reranker(
        self,
        query: str,
        features: list[RankFeatures],
        final_top_k: int,
    ) -> list[RankFeatures]:
        if not features:
            return []

        if not self.settings.reranker_enabled:
            return self._reindex_features(features[:final_top_k])

        documents = [feature.semantic_text[: self.settings.reranker_text_max_chars] for feature in features]
        try:
            rerank_scores = await asyncio.to_thread(self.semantic_service.rerank, query, documents)
        except Exception as exc:  # pragma: no cover
            print(f"Reranker fallback to first-stage similarity: {exc}")
            return self._reindex_features(features[:final_top_k])

        if not rerank_scores:
            return self._reindex_features(features[:final_top_k])

        reranked: list[RankFeatures] = []
        for feature, rerank_score in zip(features, rerank_scores, strict=False):
            reranked.append(
                replace(
                    feature,
                    rerank_component=float(rerank_score),
                    similarity_component=float(rerank_score),
                )
            )

        reranked.sort(
            key=lambda item: (-item.rerank_component, -item.hybrid_component, -item.bm25_component, item.rank_index)
        )
        return self._reindex_features(reranked[:final_top_k])

    def _attach_pagerank_and_profile(
        self,
        features: list[RankFeatures],
        personalization_context: PersonalizationContext,
    ) -> list[RankFeatures]:
        if not features:
            return []

        max_pagerank = max(feature.pagerank for feature in features) or 0.0
        raw_profile_scores: list[float] = []
        for feature in features:
            if personalization_context.profile_vector and feature.doc_vector:
                raw_profile_scores.append(
                    self.semantic_service.cosine_similarity(personalization_context.profile_vector, feature.doc_vector)
                )
            else:
                raw_profile_scores.append(0.0)

        attached: list[RankFeatures] = []
        for feature, raw_profile_score in zip(features, raw_profile_scores, strict=False):
            pagerank_component = 0.0
            if max_pagerank > 0:
                pagerank_component = math.log1p(feature.pagerank) / math.log1p(max_pagerank)

            personalization = compute_profile_vector_score(
                personalization_context,
                feature.doc_vector,
                raw_profile_score,
                title=feature.title,
                site_name=feature.site_name,
                departments=feature.departments,
                snippet=feature.snippet,
                semantic_text=feature.semantic_text,
            )

            attached.append(
                replace(
                    feature,
                    pagerank_component=pagerank_component,
                    profile_component=personalization.personal_score,
                    profile_match_component=personalization.profile_match_score,
                )
            )
        return attached

    async def _build_personalized_feature_pool(
        self,
        query: str,
        mode: str,
        phrase_slop: int,
        base_features: list[RankFeatures],
        personalization_context: PersonalizationContext,
        plan: QueryPersonalizationPlan,
    ) -> list[RankFeatures]:
        if mode in PHRASE_WILDCARD_MODES or not plan.selected_tags:
            return base_features

        if self.settings.semantic_enabled:
            personalized_execution = await self._run_hybrid_search(
                plan.expanded_query or query,
                mode,
                phrase_slop,
                lexical_top_k=min(self.settings.personalized_lexical_top_k, DEFAULT_RECALL_K),
                vector_top_k=min(self.settings.personalized_vector_top_k, DEFAULT_RECALL_K),
                vector_num_candidates=min(self.settings.personalized_vector_num_candidates, 50),
                max_candidates=min(self.settings.personalized_max_candidates, DEFAULT_CANDIDATE_K),
                final_top_k=DEFAULT_RESULT_K,
            )
        else:
            personalized_execution = await self._run_lexical_search(
                plan.expanded_query or query,
                mode,
                phrase_slop,
                top_k=DEFAULT_RESULT_K,
                apply_reranker=self.settings.reranker_enabled,
            )

        personalized_features = self._attach_pagerank_and_profile(
            personalized_execution.features,
            personalization_context,
        )
        personalized_features = self._apply_selected_tag_scores(personalized_features, plan.selected_tags)
        return self._merge_personalized_with_base(personalized_features, base_features)

    def _apply_selected_tag_scores(
        self,
        features: list[RankFeatures],
        selected_tags: list[str],
    ) -> list[RankFeatures]:
        if not selected_tags:
            return features

        updated: list[RankFeatures] = []
        for feature in features:
            tag_score = self._selected_tag_match_score(selected_tags, feature)
            updated.append(
                replace(
                    feature,
                    profile_component=max(feature.profile_component, tag_score),
                    profile_match_component=max(feature.profile_match_component, tag_score),
                    source_group="personalized",
                )
            )
        return updated

    def _selected_tag_match_score(self, selected_tags: list[str], feature: RankFeatures) -> float:
        haystack_primary = " ".join([feature.title, feature.site_name, *feature.departments])
        haystack_full = " ".join([haystack_primary, feature.snippet, feature.semantic_text])

        total = 0.0
        matched = 0.0
        for tag in selected_tags:
            clean_tag = tag.strip()
            if not clean_tag:
                continue
            total += 1.0
            if clean_tag in haystack_primary:
                matched += 1.0
            elif clean_tag in haystack_full:
                matched += 0.7
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, matched / total))

    def _merge_personalized_with_base(
        self,
        personalized_features: list[RankFeatures],
        base_features: list[RankFeatures],
    ) -> list[RankFeatures]:
        personalized_sorted = sorted(
            personalized_features,
            key=lambda item: (-item.pagerank_component, -item.similarity_component, item.rank_index),
        )
        base_sorted = sorted(
            base_features,
            key=lambda item: (-item.pagerank_component, -item.similarity_component, item.rank_index),
        )

        merged: list[RankFeatures] = []
        seen: set[str] = set()
        for feature in personalized_sorted:
            if feature.doc_id in seen:
                continue
            merged.append(replace(feature, source_group="personalized"))
            seen.add(feature.doc_id)

        for feature in base_sorted:
            if feature.doc_id in seen:
                continue
            merged.append(replace(feature, source_group="base"))
            seen.add(feature.doc_id)

        return self._reindex_features(merged)

    def _build_strategy_results(
        self,
        base_features: list[RankFeatures],
        personalized_features: list[RankFeatures],
        page: int,
        size: int,
        personalization_enabled: bool,
    ) -> list[SearchStrategyResult]:
        _ = base_features
        personalized_description = (
            "先由大模型根据当前查询意图，从用户画像标签中选择本次适合加入查询的标签，完成个性化召回 10 条；"
            "再与普通召回 10 条去重合并，个性化结果放前面，组内按 PageRank 排序，最终返回最多 20 条结果。"
            if personalization_enabled
            else "当前未生成有效的个性化查询扩展，因此该视图退化为普通搜索精排结果。"
        )

        offset = (page - 1) * size
        limit = offset + size

        return [
            SearchStrategyResult(
                key="personalized",
                label="个性引入",
                description=personalized_description,
                hits=self._materialize_hits(personalized_features[offset:limit], "personalized", personalization_enabled),
            ),
        ]

    def _materialize_hits(
        self,
        ranked_features: list[RankFeatures],
        strategy: str,
        personalization_enabled: bool,
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for item in ranked_features:
            if strategy == "bm25":
                strategy_score = item.similarity_component
            elif strategy == "bm25_pagerank":
                strategy_score = item.pagerank_component
            else:
                strategy_score = self._personalized_strategy_score(item, personalization_enabled)

            hits.append(
                SearchHit(
                    doc_id=item.doc_id,
                    title=item.title,
                    url=item.url,
                    snippet=item.snippet,
                    site_name=item.site_name,
                    doc_kind=item.doc_kind,
                    departments=item.departments,
                    publish_time=item.publish_time,
                    file_extension=item.file_extension,
                    score=round(strategy_score, 4),
                    raw_es_score=round(item.raw_es_score, 4),
                    bm25_component=round(item.bm25_component, 4),
                    vector_component=round(item.vector_component, 4),
                    hybrid_component=round(item.hybrid_component, 4),
                    rerank_component=round(item.rerank_component, 4),
                    similarity_component=round(item.similarity_component, 4),
                    pagerank=item.pagerank,
                    pagerank_component=round(item.pagerank_component, 4),
                    profile_component=round(item.profile_component, 4),
                    profile_match_component=round(item.profile_match_component, 4),
                    source_group=item.source_group,
                    snapshot_url=item.snapshot_url,
                )
            )
        return hits

    async def _build_profile_vector(self, current_user: User | None) -> list[float]:
        if current_user is None or not self.settings.semantic_enabled:
            return []

        profile_text = build_user_profile_text(current_user)
        if not profile_text:
            return []

        try:
            return await asyncio.to_thread(self.semantic_service.encode_query, profile_text)
        except Exception as exc:  # pragma: no cover
            print(f"Profile embedding disabled at runtime: {exc}")
            return []

    def _build_fixed_recommendation_tags(self, current_user: User) -> list[str]:
        return self._dedupe_recommendation_terms(
            [
                current_user.college.strip(),
                current_user.major.strip(),
            ]
        )

    def _build_dynamic_recommendation_tags(self, current_user: User) -> list[str]:
        cached_profile = get_cached_ai_profile(current_user)
        parts: list[str] = []
        parts.extend(get_behavior_tags(current_user))
        parts.extend(list(cached_profile.get("behavior_tags", [])))
        if not parts:
            parts.extend(current_user.get_interest_tags())
        return self._dedupe_recommendation_terms(parts)

    def _sample_dynamic_recommendation_tags(self, dynamic_tags: list[str], limit: int) -> list[str]:
        clean_tags = self._dedupe_recommendation_terms(dynamic_tags)
        if not clean_tags:
            return []
        if len(clean_tags) <= limit:
            return random.sample(clean_tags, len(clean_tags))
        return random.sample(clean_tags, limit)

    def _build_mixed_recommendation_groups(
        self,
        fixed_tags: list[str],
        dynamic_tags: list[str],
        limit: int,
    ) -> tuple[list[list[str]], list[str]]:
        clean_fixed_tags = self._dedupe_recommendation_terms(fixed_tags)
        clean_dynamic_tags = self._dedupe_recommendation_terms(dynamic_tags)
        if not clean_fixed_tags or not clean_dynamic_tags or limit <= 0:
            return [], []

        sampled_dynamic_tags = self._sample_dynamic_recommendation_tags(clean_dynamic_tags, limit=limit)
        groups: list[list[str]] = []
        for tag in sampled_dynamic_tags:
            fixed_tag = random.choice(clean_fixed_tags)
            groups.append(self._dedupe_recommendation_terms([fixed_tag, tag])[:2])
        return groups, sampled_dynamic_tags

    def _build_dynamic_recommendation_groups(
        self,
        dynamic_tags: list[str],
        limit: int,
    ) -> list[list[str]]:
        sampled_dynamic_tags = self._sample_dynamic_recommendation_tags(dynamic_tags, limit=limit)
        return [[tag] for tag in sampled_dynamic_tags]

    async def _collect_group_recommendations(
        self,
        query_groups: list[list[str]],
    ) -> list[RecommendationItem]:
        query_texts = [joined_text(group) for group in query_groups if group]
        if not query_texts:
            return []

        executions = await asyncio.gather(
            *[
                self._run_lexical_search(
                    query_text,
                    mode="normal",
                    phrase_slop=0,
                    top_k=5,
                    apply_reranker=False,
                )
                for query_text in query_texts
            ]
        )

        seen_doc_ids: set[str] = set()
        items: list[RecommendationItem] = []
        for query_group, query_text, execution in zip(query_groups, query_texts, executions):
            ranked = sorted(
                execution.features,
                key=lambda item: (-item.similarity_component, item.rank_index),
            )
            selected = next((item for item in ranked if item.doc_id not in seen_doc_ids), None)
            if selected is None:
                continue

            seen_doc_ids.add(selected.doc_id)
            items.append(
                RecommendationItem(
                    doc_id=selected.doc_id,
                    title=selected.title,
                    url=selected.url,
                    reason=self._build_recommendation_reason(query_group, query_text),
                )
            )
        return items

    def _build_recommendation_reason(self, query_group: list[str], query_text: str) -> str:
        if len(query_group) >= 2:
            return f"固定+动态 BM25 组合：{' / '.join(query_group)}"
        if len(query_group) == 1:
            return f"动态标签 BM25 推荐：{query_group[0]}"
        return f"BM25 推荐查询：{query_text}"

    def _dedupe_recommendation_terms(self, parts: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for part in parts:
            clean_part = str(part or "").strip()
            if not clean_part or clean_part in seen:
                continue
            seen.add(clean_part)
            deduped.append(clean_part)
        return deduped

    async def _maybe_correct_query(self, query: str) -> str | None:
        correction = await fetch_query_correction(prefix=query)
        return correction.corrected_text if correction else None

    def _build_es_query(self, query: str, mode: str, phrase_slop: int) -> dict[str, Any]:
        if mode == "document":
            return {
                "bool": {
                    "must": [self._normal_query(query)],
                    "filter": [{"terms": {"doc_kind": list(DOCUMENT_KINDS)}}],
                }
            }

        if mode == "phrase":
            return self._wrap_non_document_query(
                {
                    "bool": {
                        "should": [
                            {"match_phrase": {"title": {"query": query, "slop": phrase_slop}}},
                            {"match_phrase": {"content": {"query": query, "slop": phrase_slop}}},
                            {"match_phrase": {"anchor_texts": {"query": query, "slop": phrase_slop}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        if mode == "wildcard":
            wildcard = query.replace("？", "?")
            return self._wrap_non_document_query(
                {
                    "bool": {
                        "should": [
                            {"wildcard": {"title_wc": {"value": wildcard}}},
                            {"wildcard": {"anchor_wc": {"value": wildcard}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        return self._wrap_non_document_query(self._normal_query(query))

    def _wrap_non_document_query(self, query: dict[str, Any]) -> dict[str, Any]:
        return {
            "bool": {
                "must": [query],
                "must_not": [{"terms": {"doc_kind": list(DOCUMENT_KINDS)}}],
            }
        }

    def _normal_query(self, query: str) -> dict[str, Any]:
        return {
            "multi_match": {
                "query": query,
                "type": "best_fields",
                "fields": ["title^4", "anchor_texts^2.5", "content", "site_name^1.2"],
            }
        }

    def _build_knn_request(
        self,
        query_vector: list[float],
        mode: str,
        vector_top_k: int,
        vector_num_candidates: int,
    ) -> dict[str, Any]:
        knn: dict[str, Any] = {
            "field": self.settings.vector_field_name,
            "query_vector": query_vector,
            "k": vector_top_k,
            "num_candidates": vector_num_candidates,
        }
        if mode == "document":
            knn["filter"] = {"terms": {"doc_kind": list(DOCUMENT_KINDS)}}
        else:
            knn["filter"] = {
                "bool": {
                    "must_not": [{"terms": {"doc_kind": list(DOCUMENT_KINDS)}}],
                }
            }
        return knn

    def _base_strategy_description(self, mode: str) -> str:
        if mode in PHRASE_WILDCARD_MODES:
            return "短语查询和通配查询只使用倒排索引召回，不引入向量召回和 reranker。"
        return "普通搜索先做 BM25 召回 10 条和 HNSW 向量召回 10 条，去重后取前 10 条。"

    def _personalized_strategy_score(self, item: RankFeatures, personalization_enabled: bool) -> float:
        if not personalization_enabled:
            return item.pagerank_component
        if item.source_group == "personalized":
            return 1.0 + item.pagerank_component
        return item.pagerank_component

    def _build_snippet(self, hit: dict) -> str:
        highlights = hit.get("highlight", {})
        if "content" in highlights:
            return highlights["content"][0]
        if "title" in highlights:
            return highlights["title"][0]

        source = hit.get("_source", {})
        content = str(source.get("content", "") or "")
        return content[:180] + ("..." if len(content) > 180 else "")

    def _reindex_features(self, features: list[RankFeatures]) -> list[RankFeatures]:
        return [replace(feature, rank_index=index) for index, feature in enumerate(features)]

    def _log_query(
        self,
        current_user: User | None,
        query_text: str,
        corrected_query: str | None,
        mode: str,
        result_count: int,
    ) -> None:
        self.db.add(
            QueryLog(
                user_id=current_user.id if current_user else None,
                query_text=query_text,
                corrected_query=corrected_query,
                mode=mode,
                result_count=result_count,
            )
        )
        self.db.commit()


def _normalize_by_max(values: list[float]) -> list[float]:
    if not values:
        return []
    high = max(values)
    if math.isclose(high, 0.0):
        return [0.0 for _ in values]
    return [value / high for value in values]


def _cosine_to_unit(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, (value + 1.0) / 2.0))

