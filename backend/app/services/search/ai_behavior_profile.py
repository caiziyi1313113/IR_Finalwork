from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import desc, func, select

from app.core.config import Settings, get_settings
from app.core.elastic import get_es_client
from app.db.database import SessionLocal
from app.models.click_log import ClickLog
from app.models.query_log import QueryLog
from app.models.user import User
from app.services.search.text_utils import joined_text, split_profile_terms

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
USER_LOCKS: dict[int, asyncio.Lock] = {}

TAG_GROUP_LIMITS = {
    "topic_tags": 8,
    "intent_tags": 8,
    "resource_tags": 6,
    "scenario_tags": 6,
    "custom_tags": 4,
}
AI_LIST_LIMITS = {
    "behavior_tags": 16,
    "query_assist_terms": 14,
    "query_assist_queries": 8,
    "recommendation_queries": 8,
    "preferred_departments": 8,
    "preferred_sites": 8,
}
TAG_CATALOG = {
    "topic_tags": [
        "通知公告",
        "新闻资讯",
        "培养方案",
        "课程信息",
        "教学计划",
        "教师主页",
        "导师信息",
        "科研项目",
        "实验室",
        "招生信息",
        "夏令营推免",
        "复试录取",
        "学术讲座",
        "活动资讯",
        "奖助学金",
        "竞赛创新",
        "毕业论文",
        "规章制度",
        "办事流程",
    ],
    "intent_tags": [
        "找通知",
        "找培养方案",
        "找课程安排",
        "找教师信息",
        "找导师方向",
        "找招生政策",
        "找夏令营推免",
        "找科研机会",
        "找讲座活动",
        "找下载附件",
    ],
    "resource_tags": [
        "网页内容",
        "PDF文档",
        "DOCX文档",
        "XLSX表格",
        "附件下载",
        "网页快照",
    ],
    "scenario_tags": [
        "本科教学",
        "研究生培养",
        "招生升学",
        "科研训练",
        "校园活动",
        "行政办事",
        "跨学院导航",
        "就业实习",
    ],
}

SYSTEM_PROMPT = """
你是南开大学校园搜索系统的用户行为画像标签助手。
你的任务是根据用户固定画像、历史查询、历史点击，对用户的“动态标签”进行增删改，并输出严格 JSON。

规则：
1. 只输出 JSON，不要输出解释、Markdown 或额外文字。
2. 固定画像中的学院和专业不要当作动态标签修改，它们单独保留。
3. 优先从给定标签库中选择标签；只有确实不够表达时，才允许少量 custom_tags。
4. 输出的标签必须短、稳定、可用于查询建议和推荐。
5. query_assist_queries 和 recommendation_queries 必须是适合校园搜索的简短查询。
""".strip()


def ai_behavior_ready(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return cfg.ai_behavior_enabled and bool(cfg.zhipu_api_key.strip())


def get_cached_ai_profile(user: User | None) -> dict[str, Any]:
    if user is None:
        return {}
    return normalize_ai_profile(user.get_ai_behavior_profile(), user)


def has_cached_ai_profile(user: User | None) -> bool:
    return bool(get_cached_ai_profile(user).get("behavior_tags"))


def get_behavior_tags(user: User | None) -> list[str]:
    return list(get_cached_ai_profile(user).get("behavior_tags", []))


def get_query_assist_terms(user: User | None) -> list[str]:
    return list(get_cached_ai_profile(user).get("query_assist_terms", []))


def get_query_assist_queries(user: User | None) -> list[str]:
    return list(get_cached_ai_profile(user).get("query_assist_queries", []))


def get_recommendation_queries(user: User | None) -> list[str]:
    return list(get_cached_ai_profile(user).get("recommendation_queries", []))


async def refresh_ai_behavior_profile(user_id: int, reason: str = "search", force: bool = False) -> None:
    settings = get_settings()
    if user_id <= 0 or not ai_behavior_ready(settings):
        return

    lock = USER_LOCKS.setdefault(user_id, asyncio.Lock())
    async with lock:
        db = SessionLocal()
        try:
            user = db.get(User, user_id)
            if user is None:
                return

            query_count = _get_user_query_count(db, user.id)
            if _should_skip_refresh(user=user, query_count=query_count, settings=settings, reason=reason, force=force):
                return

            snapshot = await _build_user_snapshot(user=user, settings=settings, db=db, query_count=query_count)
            source_hash = hashlib.sha256(
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()

            if not force and source_hash == (user.ai_behavior_source_hash or ""):
                user.ai_behavior_query_count = query_count
                user.ai_behavior_status = "ready"
                user.ai_behavior_error = ""
                db.add(user)
                db.commit()
                return

            user.ai_behavior_status = "running"
            user.ai_behavior_error = ""
            db.add(user)
            db.commit()

            raw_profile = await _call_zhipu_profile_api(snapshot=snapshot, settings=settings)
            normalized_profile = normalize_ai_profile(raw_profile, user)

            user.set_ai_behavior_profile(normalized_profile)
            user.ai_behavior_summary = normalized_profile.get("profile_summary", "")
            user.ai_behavior_source_hash = source_hash
            user.ai_behavior_status = "ready"
            user.ai_behavior_error = ""
            user.ai_behavior_query_count = query_count
            user.ai_behavior_updated_at = datetime.now(timezone.utc)
            db.add(user)
            db.commit()
        except Exception as exc:  # pragma: no cover - depends on runtime/network
            user = db.get(User, user_id)
            if user is not None:
                user.ai_behavior_status = "error"
                user.ai_behavior_error = str(exc)[:500]
                user.ai_behavior_updated_at = datetime.now(timezone.utc)
                db.add(user)
                db.commit()
        finally:
            db.close()


def normalize_ai_profile(payload: dict[str, Any] | None, user: User | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    previous_profile = user.get_ai_behavior_profile() if user else {}
    previous_tags = _normalize_string_list(previous_profile.get("behavior_tags"), AI_LIST_LIMITS["behavior_tags"])

    fixed_tags = {
        "identity": user.identity.strip() if user else "",
        "college": user.college.strip() if user else "",
        "major": user.major.strip() if user else "",
    }

    raw_tag_groups = data.get("tag_groups")
    tag_groups_input = raw_tag_groups if isinstance(raw_tag_groups, dict) else {}
    normalized_groups: dict[str, list[str]] = {}
    for group_name, limit in TAG_GROUP_LIMITS.items():
        normalized_groups[group_name] = _normalize_tag_group(
            values=tag_groups_input.get(group_name),
            group_name=group_name,
            limit=limit,
        )

    behavior_tags = _dedupe(
        [
            *_normalize_string_list(data.get("behavior_tags"), AI_LIST_LIMITS["behavior_tags"]),
            *normalized_groups["topic_tags"],
            *normalized_groups["intent_tags"],
            *normalized_groups["resource_tags"],
            *normalized_groups["scenario_tags"],
            *normalized_groups["custom_tags"],
        ]
    )[: AI_LIST_LIMITS["behavior_tags"]]

    if not behavior_tags:
        behavior_tags = _build_fallback_behavior_tags(user)

    preferred_departments = _normalize_string_list(
        data.get("preferred_departments"),
        AI_LIST_LIMITS["preferred_departments"],
    )
    if not preferred_departments and fixed_tags["college"]:
        preferred_departments = [fixed_tags["college"]]

    preferred_sites = _normalize_string_list(
        data.get("preferred_sites"),
        AI_LIST_LIMITS["preferred_sites"],
    )

    query_assist_terms = _dedupe(
        [
            *_normalize_string_list(data.get("query_assist_terms"), AI_LIST_LIMITS["query_assist_terms"]),
            *behavior_tags,
            fixed_tags["college"],
            fixed_tags["major"],
            *preferred_departments[:2],
        ]
    )[: AI_LIST_LIMITS["query_assist_terms"]]

    query_assist_queries = _normalize_string_list(
        data.get("query_assist_queries"),
        AI_LIST_LIMITS["query_assist_queries"],
    )
    if not query_assist_queries:
        query_assist_queries = _compose_query_assist_queries(query_assist_terms, user, AI_LIST_LIMITS["query_assist_queries"])

    recommendation_queries = _normalize_string_list(
        data.get("recommendation_queries"),
        AI_LIST_LIMITS["recommendation_queries"],
    )
    if not recommendation_queries:
        recommendation_queries = _compose_recommendation_queries(
            query_assist_terms,
            user,
            AI_LIST_LIMITS["recommendation_queries"],
        )

    tag_changes = {
        "added": [tag for tag in behavior_tags if tag not in previous_tags],
        "removed": [tag for tag in previous_tags if tag not in behavior_tags],
        "retained": [tag for tag in behavior_tags if tag in previous_tags],
    }

    summary = str(data.get("profile_summary", "") or "").strip()
    if not summary:
        summary = _build_profile_summary(fixed_tags=fixed_tags, behavior_tags=behavior_tags)

    return {
        "profile_summary": summary[:300],
        "fixed_tags": fixed_tags,
        "tag_groups": normalized_groups,
        "behavior_tags": behavior_tags,
        "tag_changes": tag_changes,
        "query_assist_terms": query_assist_terms,
        "query_assist_queries": query_assist_queries,
        "recommendation_queries": recommendation_queries,
        "preferred_departments": preferred_departments,
        "preferred_sites": preferred_sites,
    }


async def _build_user_snapshot(
    user: User,
    settings: Settings,
    db,
    query_count: int,
) -> dict[str, Any]:
    query_rows = db.execute(
        select(
            QueryLog.query_text,
            QueryLog.corrected_query,
            QueryLog.mode,
            QueryLog.result_count,
            QueryLog.created_at,
        )
        .where(QueryLog.user_id == user.id)
        .order_by(desc(QueryLog.created_at))
        .limit(settings.ai_behavior_max_queries)
    ).all()

    click_rows = db.execute(
        select(
            ClickLog.doc_id,
            ClickLog.query_text,
            ClickLog.clicked_at,
        )
        .where(ClickLog.user_id == user.id)
        .order_by(desc(ClickLog.clicked_at))
        .limit(settings.ai_behavior_max_clicks)
    ).all()

    clicked_docs = await _load_clicked_doc_summaries([row.doc_id for row in click_rows], settings)
    click_items: list[dict[str, Any]] = []
    for row in click_rows:
        doc_summary = clicked_docs.get(row.doc_id, {})
        click_items.append(
            {
                "doc_id": row.doc_id,
                "query_text": (row.query_text or "").strip(),
                "clicked_at": _to_isoformat(row.clicked_at),
                "title": doc_summary.get("title", ""),
                "site_name": doc_summary.get("site_name", ""),
                "departments": doc_summary.get("departments", []),
                "doc_kind": doc_summary.get("doc_kind", ""),
            }
        )

    query_items = [
        {
            "query_text": (row.query_text or "").strip(),
            "corrected_query": (row.corrected_query or "").strip(),
            "mode": row.mode,
            "result_count": int(row.result_count or 0),
            "created_at": _to_isoformat(row.created_at),
        }
        for row in query_rows
        if (row.query_text or "").strip()
    ]

    existing_profile = get_cached_ai_profile(user)
    return {
        "reason": "refresh_user_behavior_profile",
        "query_count": query_count,
        "last_refresh_query_count": int(user.ai_behavior_query_count or 0),
        "fixed_profile": {
            "identity": user.identity,
            "college": user.college,
            "major": user.major,
        },
        "registered_interest_tags": user.get_interest_tags(),
        "search_need_text": user.search_need_text,
        "tag_catalog": TAG_CATALOG,
        "existing_dynamic_tags": existing_profile.get("behavior_tags", []),
        "existing_tag_groups": existing_profile.get("tag_groups", {}),
        "queries": query_items,
        "clicks": click_items,
    }


async def _load_clicked_doc_summaries(doc_ids: list[str], settings: Settings) -> dict[str, dict[str, Any]]:
    unique_ids = _dedupe([doc_id.strip() for doc_id in doc_ids if doc_id and doc_id.strip()])
    if not unique_ids:
        return {}

    es = get_es_client()
    response = await es.mget(index=settings.es_index, ids=unique_ids)
    summaries: dict[str, dict[str, Any]] = {}
    for doc in response.get("docs", []):
        source = doc.get("_source", {})
        summaries[doc.get("_id", "")] = {
            "title": str(source.get("title", "") or "").strip(),
            "site_name": str(source.get("site_name", "") or "").strip(),
            "departments": [str(item).strip() for item in source.get("departments", []) if str(item).strip()],
            "doc_kind": str(source.get("doc_kind", "") or "").strip(),
        }
    return summaries


async def _call_zhipu_profile_api(snapshot: dict[str, Any], settings: Settings) -> dict[str, Any]:
    payload = {
        "model": settings.zhipu_model,
        "stream": False,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "请根据标签库和用户行为，输出最新的动态标签画像。你可以删除无效旧标签，保留有效标签，新增必要标签。",
                        "required_schema": {
                            "profile_summary": "string",
                            "tag_groups": {
                                "topic_tags": ["string"],
                                "intent_tags": ["string"],
                                "resource_tags": ["string"],
                                "scenario_tags": ["string"],
                                "custom_tags": ["string"],
                            },
                            "behavior_tags": ["string"],
                            "query_assist_terms": ["string"],
                            "query_assist_queries": ["string"],
                            "recommendation_queries": ["string"],
                            "preferred_departments": ["string"],
                            "preferred_sites": ["string"],
                        },
                        "user_snapshot": snapshot,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    async with httpx.AsyncClient(timeout=settings.ai_behavior_timeout_seconds) as client:
        response = await client.post(
            settings.zhipu_api_url,
            headers={
                "Authorization": f"Bearer {settings.zhipu_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        response_data = response.json()

    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"invalid Zhipu response: {response_data}") from exc

    if isinstance(content, list):
        text = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
    else:
        text = str(content or "")

    return _extract_json_payload(text)


def _extract_json_payload(text: str) -> dict[str, Any]:
    candidate = text.strip()
    match = JSON_BLOCK_RE.search(candidate)
    if match:
        candidate = match.group(1).strip()
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]

    data = json.loads(candidate)
    if not isinstance(data, dict):
        raise ValueError("AI profile payload is not a JSON object")
    return data


def _should_skip_refresh(
    user: User,
    query_count: int,
    settings: Settings,
    reason: str,
    force: bool,
) -> bool:
    if force:
        return False

    if user.ai_behavior_status == "running":
        return True

    has_profile = bool(user.get_ai_behavior_profile())
    if not has_profile and reason == "login":
        return False

    if reason != "search":
        return True

    last_query_count = int(user.ai_behavior_query_count or 0)
    return query_count - last_query_count < settings.ai_behavior_query_batch_size


def _get_user_query_count(db, user_id: int) -> int:
    value = db.scalar(select(func.count(QueryLog.id)).where(QueryLog.user_id == user_id))
    return int(value or 0)


def _normalize_tag_group(values: Any, group_name: str, limit: int) -> list[str]:
    items = _normalize_string_list(values, limit * 2)
    if group_name == "custom_tags":
        return items[:limit]

    catalog = set(TAG_CATALOG.get(group_name, []))
    filtered = [item for item in items if item in catalog]
    return filtered[:limit]


def _normalize_string_list(value: Any, limit: int) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[,\n;；、]+", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    items: list[str] = []
    for item in raw_items:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if text and text not in items:
            items.append(text[:80])
        if len(items) >= limit:
            break
    return items


def _build_fallback_behavior_tags(user: User | None) -> list[str]:
    if user is None:
        return []
    return _dedupe(
        [
            *user.get_interest_tags(),
            *split_profile_terms(user.search_need_text),
        ]
    )[: AI_LIST_LIMITS["behavior_tags"]]


def _build_profile_summary(fixed_tags: dict[str, str], behavior_tags: list[str]) -> str:
    left = " / ".join(item for item in [fixed_tags.get("college", ""), fixed_tags.get("major", "")] if item)
    right = "、".join(behavior_tags[:4])
    if left and right:
        return f"{left}，当前偏好：{right}"
    if left:
        return left
    return right


def _compose_query_assist_queries(terms: list[str], user: User | None, limit: int) -> list[str]:
    candidates: list[str] = []
    college = user.college.strip() if user else ""
    major = user.major.strip() if user else ""

    for term in terms:
        if college and term != college:
            candidates.append(_combine_terms(college, term))
        if major and term != major:
            candidates.append(_combine_terms(major, term))
        candidates.append(term)

    return _dedupe(item for item in candidates if item)[:limit]


def _compose_recommendation_queries(terms: list[str], user: User | None, limit: int) -> list[str]:
    explicit_terms = _explicit_profile_terms(user)
    candidates: list[str] = []

    if len(explicit_terms) >= 2:
        candidates.append(_combine_terms(explicit_terms[0], explicit_terms[1]))
    if terms:
        candidates.append(_combine_terms(terms[0], terms[1] if len(terms) > 1 else ""))

    for term in terms[:limit]:
        if explicit_terms:
            candidates.append(_combine_terms(explicit_terms[0], term))
        else:
            candidates.append(term)

    return _dedupe(item for item in candidates if item)[:limit]


def _explicit_profile_terms(user: User | None) -> list[str]:
    if user is None:
        return []
    return _dedupe(
        [
            user.college.strip(),
            user.major.strip(),
            *user.get_interest_tags(),
            *split_profile_terms(user.search_need_text),
        ]
    )


def _to_isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _dedupe(values) -> list[str]:
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _combine_terms(left: str, right: str) -> str:
    left_text = left.strip()
    right_text = right.strip()
    if not left_text:
        return right_text
    if not right_text:
        return left_text
    if left_text in right_text or right_text in left_text:
        return left_text if len(left_text) >= len(right_text) else right_text
    if re.search(r"[\u4e00-\u9fff]", left_text + right_text):
        return f"{left_text}{right_text}"
    return joined_text([left_text, right_text])
