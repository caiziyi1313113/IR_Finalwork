from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings
from app.models.user import User
from app.services.search.ai_behavior_profile import ai_behavior_ready, get_cached_ai_profile
from app.services.search.intent import detect_query_intent
from app.services.search.text_utils import joined_text

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
PLAN_CACHE: dict[tuple[int, str, str], "QueryPersonalizationPlan"] = {}
MAX_SELECTED_TAGS = 4
MAX_CANDIDATE_TAGS = 24

TRAINING_TERMS = ("培养", "培养方案", "教学计划", "课程", "学分", "选课", "课表")
ADMISSION_TERMS = ("招生", "推免", "夏令营", "复试", "录取", "报名")
TEACHER_TERMS = (
    "老师",
    "教师",
    "导师",
    "研究方向",
    "实验室",
    "论文",
    "科研",
    "讲座",
    "学术讲座",
    "学术报告",
    "报告",
    "论坛",
    "研讨会",
    "沙龙",
)
NOTICE_TERMS = ("通知", "公告", "公示", "安排", "须知", "截止")
DOCUMENT_TERMS = ("下载", "附件", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx")
NEWS_TERMS = ("新闻", "报道", "要闻", "快讯", "动态")
LIFE_TERMS = ("美食", "食堂", "餐厅", "外卖", "奶茶", "咖啡", "宿舍", "快递", "天气", "地图", "打印")

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "training_plan": TRAINING_TERMS,
    "admission": ADMISSION_TERMS,
    "teacher_research": TEACHER_TERMS,
    "notice": NOTICE_TERMS,
    "document": DOCUMENT_TERMS,
    "news": NEWS_TERMS,
    "life": LIFE_TERMS,
}

INTENT_ALLOWED_TAG_TYPES: dict[str, set[str]] = {
    "training_plan": {"college", "major", "department", "training_plan", "document", "topic", "interest"},
    "admission": {"college", "major", "department", "admission", "notice", "document", "topic", "interest"},
    "teacher_research": {"college", "major", "department", "teacher_research", "topic", "interest"},
    "document": {"college", "major", "department", "document", "training_plan", "notice", "topic", "interest"},
    "notice": {"college", "major", "department", "notice", "topic", "interest"},
    "navigation": {"college", "department"},
    "news": {"news", "topic", "interest"},
    "life": set(),
    "general": set(),
}

PROFILE_HEAVY_INTENTS = {"training_plan", "admission", "teacher_research", "document", "notice"}

SYSTEM_PROMPT = """
你是高校搜索系统的查询个性化助手。你的任务不是总是拼接用户标签，而是先判断“当前查询是否适合引入画像标签”。

规则：
1. 只有当查询明显属于院系/专业相关的信息需求时，才可以加入学院、专业、培养方案、招生、导师、课程、附件文档等标签。
2. 对于学术讲座、学术报告、论坛、研讨会、科研活动等学术性查询，可以结合学院、专业和研究兴趣做适度扩展。
3. 对于美食、食堂、外卖、奶茶、咖啡、地图、天气、快递、宿舍、打印等生活化或泛查询，通常不要加入学院、专业、培养方案等学术标签。
4. 如果原始 query 已经足够具体，避免重复追加同义标签或冗余标签。
5. selected_tags 可以为空数组，这表示本次不应该做画像扩展。
6. expanded_query 必须保留原始 query；如果不需要扩展，就直接返回原始 query。
7. 只能从 candidate_tags 中选择 selected_tags，最多 4 个。
8. 只输出 JSON，不要输出解释性文字。
""".strip()


@dataclass(frozen=True)
class CandidateTagSpec:
    tag: str
    tag_type: str
    source: str


@dataclass
class QueryPersonalizationPlan:
    intent: str = "general"
    selected_tags: list[str] = field(default_factory=list)
    expanded_query: str = ""
    explanation: str = ""
    used_llm: bool = False
    apply_profile: bool = False


async def select_query_personalization(query: str, current_user: User | None) -> QueryPersonalizationPlan:
    normalized_query = query.strip()
    if current_user is None or not normalized_query:
        return QueryPersonalizationPlan(expanded_query=normalized_query)

    cached_profile = get_cached_ai_profile(current_user)
    candidate_specs = _build_candidate_tag_specs(current_user, cached_profile)
    if not candidate_specs:
        return QueryPersonalizationPlan(expanded_query=normalized_query)

    source_hash = str(current_user.ai_behavior_source_hash or "")
    cache_key = (current_user.id, source_hash, normalized_query)
    cached_plan = PLAN_CACHE.get(cache_key)
    if cached_plan is not None:
        return cached_plan

    fallback_plan = _fallback_plan(normalized_query, current_user, candidate_specs)
    plan = fallback_plan

    if ai_behavior_ready():
        try:
            llm_plan = await _call_query_intent_llm(
                query=normalized_query,
                current_user=current_user,
                cached_profile=cached_profile,
                candidate_specs=candidate_specs,
            )
            if (
                fallback_plan.apply_profile
                and fallback_plan.selected_tags
                and (not llm_plan.apply_profile or not llm_plan.selected_tags)
            ):
                plan = fallback_plan
            else:
                plan = llm_plan
        except Exception:
            plan = fallback_plan

    PLAN_CACHE[cache_key] = plan
    return plan


async def _call_query_intent_llm(
    query: str,
    current_user: User,
    cached_profile: dict[str, Any],
    candidate_specs: list[CandidateTagSpec],
) -> QueryPersonalizationPlan:
    settings = get_settings()
    detected_intent = _normalize_intent(detect_query_intent(query))
    candidate_tags = [spec.tag for spec in candidate_specs]

    payload = {
        "model": settings.zhipu_model,
        "stream": False,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "query": query,
                        "heuristic_intent": detected_intent,
                        "fixed_profile": {
                            "identity": current_user.identity,
                            "college": current_user.college,
                            "major": current_user.major,
                            "interest_tags": current_user.get_interest_tags(),
                        },
                        "candidate_tags": [
                            {"tag": spec.tag, "tag_type": spec.tag_type, "source": spec.source}
                            for spec in candidate_specs
                        ],
                        "behavior_tags": cached_profile.get("behavior_tags", []),
                        "tag_groups": cached_profile.get("tag_groups", {}),
                        "required_schema": {
                            "intent": "string",
                            "apply_profile": "boolean",
                            "selected_tags": ["string"],
                            "expanded_query": "string",
                            "explanation": "string",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    async with httpx.AsyncClient(timeout=min(settings.ai_behavior_timeout_seconds, 6.0)) as client:
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
        raise ValueError(f"invalid query personalization response: {response_data}") from exc

    text = (
        "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        if isinstance(content, list)
        else str(content or "")
    )
    data = _extract_json_payload(text)

    intent = _normalize_intent(str(data.get("intent", detected_intent) or detected_intent))
    apply_profile = _normalize_bool(data.get("apply_profile"), default=bool(data.get("selected_tags")))
    selected_tags = [tag for tag in _normalize_list(data.get("selected_tags"), MAX_SELECTED_TAGS) if tag in candidate_tags]
    selected_tags = _filter_selected_tags(intent, selected_tags, candidate_specs)

    if not apply_profile or not selected_tags:
        return QueryPersonalizationPlan(
            intent=intent,
            selected_tags=[],
            expanded_query=query.strip(),
            explanation=str(data.get("explanation", "") or "").strip() or "llm decided no profile expansion",
            used_llm=True,
            apply_profile=False,
        )

    expanded_query = _sanitize_expanded_query(query, str(data.get("expanded_query", "") or ""), selected_tags)
    return QueryPersonalizationPlan(
        intent=intent,
        selected_tags=selected_tags,
        expanded_query=expanded_query,
        explanation=str(data.get("explanation", "") or "").strip(),
        used_llm=True,
        apply_profile=True,
    )


def _fallback_plan(
    query: str,
    current_user: User,
    candidate_specs: list[CandidateTagSpec],
) -> QueryPersonalizationPlan:
    intent = _normalize_intent(detect_query_intent(query))
    allowed_types = INTENT_ALLOWED_TAG_TYPES.get(intent, set())
    if not allowed_types:
        return QueryPersonalizationPlan(
            intent=intent,
            selected_tags=[],
            expanded_query=query.strip(),
            explanation="heuristic fallback: no profile expansion for this intent",
            used_llm=False,
            apply_profile=False,
        )

    scored: list[tuple[float, CandidateTagSpec]] = []
    for spec in candidate_specs:
        score = _score_tag_for_intent(query, intent, spec, current_user)
        if score > 0:
            scored.append((score, spec))

    scored.sort(key=lambda item: (-item[0], item[1].tag))
    selected_tags = _dedupe(spec.tag for _score, spec in scored)[:MAX_SELECTED_TAGS]

    if not selected_tags:
        return QueryPersonalizationPlan(
            intent=intent,
            selected_tags=[],
            expanded_query=query.strip(),
            explanation="heuristic fallback: no suitable tags",
            used_llm=False,
            apply_profile=False,
        )

    return QueryPersonalizationPlan(
        intent=intent,
        selected_tags=selected_tags,
        expanded_query=_sanitize_expanded_query(query, "", selected_tags),
        explanation="heuristic fallback",
        used_llm=False,
        apply_profile=True,
    )


def _build_candidate_tag_specs(current_user: User, cached_profile: dict[str, Any]) -> list[CandidateTagSpec]:
    tag_group_index = _build_tag_group_index(cached_profile.get("tag_groups", {}))
    specs: list[CandidateTagSpec] = []

    def add(tag: str, tag_type: str, source: str) -> None:
        clean_tag = str(tag or "").strip()
        if not clean_tag:
            return
        if any(spec.tag == clean_tag for spec in specs):
            return
        specs.append(CandidateTagSpec(tag=clean_tag, tag_type=tag_type, source=source))

    add(current_user.college.strip(), "college", "fixed_profile")
    add(current_user.major.strip(), "major", "fixed_profile")

    for tag in current_user.get_interest_tags():
        add(tag, _infer_tag_type(tag, tag_group_index, default="interest"), "interest_tags")

    for tag in list(cached_profile.get("behavior_tags", [])):
        add(tag, _infer_tag_type(tag, tag_group_index, default="topic"), "behavior_tags")

    for tag in list(cached_profile.get("query_assist_terms", [])):
        add(tag, _infer_tag_type(tag, tag_group_index, default="topic"), "query_assist_terms")

    for tag in list(cached_profile.get("preferred_departments", [])):
        add(tag, "department", "preferred_departments")

    return specs[:MAX_CANDIDATE_TAGS]


def _build_tag_group_index(tag_groups: Any) -> dict[str, str]:
    if not isinstance(tag_groups, dict):
        return {}

    index: dict[str, str] = {}
    for group_name, values in tag_groups.items():
        if not isinstance(values, list):
            continue
        normalized_group = str(group_name or "").strip().lower()
        for value in values:
            clean_value = str(value or "").strip()
            if clean_value and clean_value not in index:
                index[clean_value] = normalized_group
    return index


def _infer_tag_type(tag: str, tag_group_index: dict[str, str], default: str) -> str:
    clean_tag = str(tag or "").strip()
    if not clean_tag:
        return default

    group_name = tag_group_index.get(clean_tag, "")
    if group_name == "intent_tags":
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(keyword in clean_tag for keyword in keywords):
                return intent
        return "topic"
    if group_name == "resource_tags":
        return "document"
    if group_name == "scenario_tags":
        return "topic"

    lowered = clean_tag.lower()
    if any(term in clean_tag for term in TRAINING_TERMS):
        return "training_plan"
    if any(term in clean_tag for term in ADMISSION_TERMS):
        return "admission"
    if any(term in clean_tag for term in TEACHER_TERMS):
        return "teacher_research"
    if any(term in clean_tag for term in NOTICE_TERMS):
        return "notice"
    if any(term in lowered for term in DOCUMENT_TERMS):
        return "document"
    if any(term in clean_tag for term in NEWS_TERMS):
        return "news"
    return default


def _filter_selected_tags(
    intent: str,
    selected_tags: list[str],
    candidate_specs: list[CandidateTagSpec],
) -> list[str]:
    allowed_types = INTENT_ALLOWED_TAG_TYPES.get(intent, set())
    if not allowed_types:
        return []

    spec_map = {spec.tag: spec for spec in candidate_specs}
    filtered: list[str] = []
    for tag in selected_tags:
        spec = spec_map.get(tag)
        if spec is None:
            continue
        if spec.tag_type in allowed_types:
            filtered.append(tag)
    return _dedupe(filtered)[:MAX_SELECTED_TAGS]


def _score_tag_for_intent(query: str, intent: str, spec: CandidateTagSpec, current_user: User) -> float:
    allowed_types = INTENT_ALLOWED_TAG_TYPES.get(intent, set())
    if spec.tag_type not in allowed_types:
        return 0.0

    score = 0.0
    clean_query = query.strip()

    if spec.tag in clean_query:
        score -= 0.8

    if intent in PROFILE_HEAVY_INTENTS and spec.tag_type in {"college", "major", "department"}:
        score += 2.0

    if spec.source == "interest_tags":
        score += 0.8
    elif spec.source == "behavior_tags":
        score += 0.6
    elif spec.source == "query_assist_terms":
        score += 0.4

    if spec.tag_type == intent:
        score += 2.4
    elif intent == "document" and spec.tag_type in {"training_plan", "notice"}:
        score += 1.2

    for keyword in INTENT_KEYWORDS.get(intent, ()):
        if keyword and keyword in spec.tag:
            score += 1.4

    if current_user.college.strip() and spec.tag == current_user.college.strip() and intent == "navigation":
        score += 0.6
    if current_user.major.strip() and spec.tag == current_user.major.strip() and intent == "training_plan":
        score += 0.8

    return max(score, 0.0)


def _sanitize_expanded_query(query: str, llm_query: str, selected_tags: list[str]) -> str:
    base_query = query.strip()
    expanded = llm_query.strip() or base_query

    parts: list[str] = [expanded]
    if base_query and base_query not in expanded:
        parts.insert(0, base_query)
    parts.extend(selected_tags)

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        clean_part = str(part or "").strip()
        if not clean_part or clean_part in seen:
            continue
        seen.add(clean_part)
        deduped.append(clean_part)
    return joined_text(deduped[:6])


def _normalize_intent(intent: str) -> str:
    clean_intent = str(intent or "").strip().lower()
    if clean_intent in INTENT_ALLOWED_TAG_TYPES:
        return clean_intent
    if clean_intent == "teacher":
        return "teacher_research"
    return "general"


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
        raise ValueError("query personalization payload is not a JSON object")
    return data


def _normalize_list(value: Any, limit: int) -> list[str]:
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
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "是"}:
            return True
        if normalized in {"false", "0", "no", "n", "否"}:
            return False
    return default


def _dedupe(values) -> list[str]:
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)
    return items
