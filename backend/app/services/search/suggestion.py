from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.elastic import get_es_client
from app.models.click_log import ClickLog
from app.models.query_log import QueryLog
from app.models.user import User
from app.services.search.ai_behavior_profile import get_behavior_tags
from app.services.search.text_utils import contains_cjk, looks_like_pinyin, normalize_pinyin_query, split_profile_terms

SUGGEST_TEXT_FIELDS = ["suggest_text", "suggest_text._2gram", "suggest_text._3gram"]
SUGGEST_PINYIN_FIELDS = ["suggest_pinyin", "suggest_pinyin._2gram", "suggest_pinyin._3gram"]
SUGGEST_INITIAL_FIELDS = ["suggest_initials", "suggest_initials._2gram", "suggest_initials._3gram"]
SEARCH_SUGGEST_FETCH_SIZE = 20
SEARCH_SUGGEST_RETURN_SIZE = 8
PROFILE_FILTER_STRICT_MIN = 4
LEXICON_SUFFIXES = [
    "学院",
    "大学",
    "研究院",
    "研究生院",
    "本科招生网",
    "研究生招生网",
    "招生网",
    "新闻网",
    "官网",
]
LEXICON_PREFIXES = ["南开大学", "南开"]
RAW_FILE_RE = re.compile(r"^[a-f0-9-]{24,}\.(pdf|doc|docx|xls|xlsx|ppt|pptx)$", re.IGNORECASE)
metadata_lexicon_cache: list[str] | None = None


@dataclass
class CorrectionHintData:
    corrected_text: str
    wrong_start: int
    wrong_end: int
    message: str


async def fetch_query_correction(prefix: str) -> CorrectionHintData | None:
    if not prefix or not contains_cjk(prefix):
        return None

    settings = get_settings()
    es = get_es_client()
    prefix_candidates = await _search_prefix_candidates(prefix=prefix, es=es, index_name=settings.es_index)
    metadata_candidates = await _metadata_lexicon_candidates(es=es, index_name=settings.es_index)

    if _has_valid_prefix_match(prefix, prefix_candidates) or _has_valid_prefix_match(prefix, metadata_candidates):
        return None

    response = await es.search(
        index=settings.es_index,
        size=0,
        suggest={
            "phrase-correction": {
                "text": prefix,
                "phrase": {
                    "field": "title.shingle",
                    "size": 1,
                    "direct_generator": [{"field": "title.shingle", "suggest_mode": "always"}],
                },
            }
        },
    )

    phrase_entries = response.get("suggest", {}).get("phrase-correction", [])
    for entry in phrase_entries:
        for option in entry.get("options", []):
            corrected_text = option.get("text", "").strip()
            if corrected_text and corrected_text != prefix and not _is_completion_like(prefix, corrected_text):
                return _build_correction_hint(prefix=prefix, corrected_text=corrected_text)

    completion_response = await es.search(
        index=settings.es_index,
        size=0,
        suggest={
            "completion-correction": {
                "prefix": prefix,
                "completion": {
                    "field": "suggest",
                    "size": 8,
                    "skip_duplicates": True,
                    "fuzzy": {"fuzziness": 1},
                },
            }
        },
    )
    completion_entries = completion_response.get("suggest", {}).get("completion-correction", [])
    completion_candidates: list[str] = []
    for entry in completion_entries:
        for option in entry.get("options", []):
            candidate = option.get("text", "").strip()
            if candidate:
                completion_candidates.append(candidate)

    completion_correction = _guess_correction_from_candidates(
        prefix=prefix,
        candidates=list(dict.fromkeys(completion_candidates)),
    )
    if completion_correction:
        return _build_correction_hint(prefix=prefix, corrected_text=completion_correction)

    metadata_correction = _guess_correction_from_candidates(prefix=prefix, candidates=metadata_candidates)
    if metadata_correction:
        return _build_correction_hint(prefix=prefix, corrected_text=metadata_correction)

    fallback_correction = _guess_correction_from_candidates(prefix=prefix, candidates=prefix_candidates)
    if fallback_correction:
        return _build_correction_hint(prefix=prefix, corrected_text=fallback_correction)
    return None


async def fetch_suggestions(prefix: str, db: Session, current_user: User | None) -> list[str]:
    settings = get_settings()
    es = get_es_client()

    if not prefix.strip():
        return []

    candidates: list[tuple[str, str, float, int]] = []
    order = 0

    for rank, query_text in enumerate(_recent_query_candidates(prefix=prefix, db=db, current_user=current_user)):
        candidates.append((query_text, "history", 125.0 - rank * 2.0, order))
        order += 1

    for rank, title in enumerate(
        await _recent_click_title_candidates(prefix=prefix, db=db, current_user=current_user)
    ):
        candidates.append((title, "click", 108.0 - rank * 2.0, order))
        order += 1

    for rank, title in enumerate(
        await _search_prefix_candidates(
            prefix=prefix,
            es=es,
            index_name=settings.es_index,
            current_user=current_user,
        )
    ):
        candidates.append((title, "search", 84.0 - rank, order))
        order += 1

    if not candidates:
        return []

    scored: dict[str, tuple[float, int]] = {}
    profile_terms = _profile_terms(current_user)
    for text, _source, base_score, source_order in candidates:
        clean_text = text.strip()
        if not clean_text or not _is_human_readable_suggestion(clean_text):
            continue

        score = (
            base_score
            + _prefix_bonus(clean_text, prefix)
            + _profile_bonus(clean_text, profile_terms)
            + _intent_bonus(clean_text, prefix)
        )
        existing = scored.get(clean_text)
        if existing is None or score > existing[0]:
            scored[clean_text] = (score, source_order)

    ranked = sorted(scored.items(), key=lambda item: (-item[1][0], item[1][1]))
    return [text for text, _ in ranked[:10]]


def _recent_query_candidates(prefix: str, db: Session, current_user: User | None) -> list[str]:
    if current_user is None:
        return []

    stmt = select(QueryLog.query_text).where(QueryLog.user_id == current_user.id)
    if prefix:
        stmt = stmt.where(QueryLog.query_text.like(f"%{prefix}%"))
    stmt = stmt.order_by(desc(QueryLog.created_at)).limit(10)
    rows = db.scalars(stmt).all()
    return list(dict.fromkeys(item for item in rows if item))


async def _recent_click_title_candidates(prefix: str, db: Session, current_user: User | None) -> list[str]:
    if current_user is None:
        return []

    settings = get_settings()
    es = get_es_client()

    doc_ids = db.scalars(
        select(ClickLog.doc_id)
        .where(ClickLog.user_id == current_user.id)
        .order_by(desc(ClickLog.clicked_at))
        .limit(8)
    ).all()
    if not doc_ids:
        return []

    response = await es.mget(index=settings.es_index, ids=list(dict.fromkeys(doc_ids)))
    titles: list[str] = []
    for doc in response.get("docs", []):
        source = doc.get("_source", {})
        title = (source.get("title") or source.get("site_name") or "").strip()
        if title and _text_matches_prefix(title, prefix) and _is_human_readable_suggestion(title):
            titles.append(title)
    return list(dict.fromkeys(titles))


async def _search_prefix_candidates(prefix: str, es, index_name: str, current_user: User | None = None) -> list[str]:
    if not prefix:
        return []

    should_queries: list[dict] = []
    if contains_cjk(prefix):
        should_queries.append(
            {
                "multi_match": {
                    "query": prefix,
                    "type": "bool_prefix",
                    "fields": SUGGEST_TEXT_FIELDS,
                }
            }
        )

    if looks_like_pinyin(prefix):
        spaced, compact = normalize_pinyin_query(prefix)
        if spaced:
            should_queries.append(
                {
                    "multi_match": {
                        "query": spaced,
                        "type": "bool_prefix",
                        "fields": SUGGEST_PINYIN_FIELDS,
                    }
                }
            )
        if compact:
            should_queries.append(
                {
                    "multi_match": {
                        "query": compact,
                        "type": "bool_prefix",
                        "fields": SUGGEST_PINYIN_FIELDS + SUGGEST_INITIAL_FIELDS,
                    }
                }
            )

    if not should_queries:
        should_queries.append(
            {
                "multi_match": {
                    "query": prefix,
                    "type": "bool_prefix",
                    "fields": SUGGEST_TEXT_FIELDS,
                }
            }
        )

    response = await es.search(
        index=index_name,
        size=SEARCH_SUGGEST_FETCH_SIZE,
        _source=["title", "site_name", "departments"],
        query={"bool": {"should": should_queries, "minimum_should_match": 1}},
    )

    profile_terms = _profile_term_weights(current_user)
    matched: list[tuple[str, float, float]] = []
    unmatched: list[tuple[str, float, float]] = []

    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        title = (source.get("title") or source.get("site_name") or "").strip()
        if not title or not _is_human_readable_suggestion(title):
            continue

        site_name = str(source.get("site_name", "") or "").strip()
        departments = [str(item).strip() for item in source.get("departments", []) if str(item).strip()]
        raw_score = float(hit.get("_score", 0.0) or 0.0)
        profile_score = _search_profile_match_score(title, site_name, departments, profile_terms)
        bucket = matched if profile_score > 0 else unmatched
        bucket.append((title, profile_score, raw_score))

    matched.sort(key=lambda item: (-item[1], -item[2], item[0]))
    unmatched.sort(key=lambda item: (-item[2], item[0]))

    if not profile_terms or len(matched) < PROFILE_FILTER_STRICT_MIN:
        ordered_titles = [title for title, _profile_score, _raw_score in matched + unmatched]
    else:
        ordered_titles = [title for title, _profile_score, _raw_score in matched]

    return list(dict.fromkeys(ordered_titles))[:SEARCH_SUGGEST_RETURN_SIZE]


def _profile_terms(current_user: User | None) -> list[str]:
    if current_user is None:
        return []

    terms: list[str] = []
    if current_user.college:
        terms.append(current_user.college.strip())
    if current_user.major:
        terms.append(current_user.major.strip())

    terms.extend(current_user.get_interest_tags())
    terms.extend(get_behavior_tags(current_user)[:8])

    if current_user.search_need_text:
        terms.extend(split_profile_terms(current_user.search_need_text))

    return list(dict.fromkeys(item for item in terms if item))


def _profile_term_weights(current_user: User | None) -> list[tuple[str, float]]:
    if current_user is None:
        return []

    weighted_terms: list[tuple[str, float]] = []
    if current_user.college.strip():
        weighted_terms.append((current_user.college.strip(), 1.4))
    if current_user.major.strip():
        weighted_terms.append((current_user.major.strip(), 1.4))

    for tag in current_user.get_interest_tags()[:6]:
        weighted_terms.append((tag, 1.0))
    for tag in get_behavior_tags(current_user)[:10]:
        weighted_terms.append((tag, 1.1))
    for term in split_profile_terms(current_user.search_need_text)[:8]:
        weighted_terms.append((term, 0.7))

    normalized: dict[str, float] = {}
    for term, weight in weighted_terms:
        clean_term = str(term or "").strip()
        if not clean_term:
            continue
        normalized[clean_term] = max(weight, normalized.get(clean_term, 0.0))
    return list(normalized.items())


def _search_profile_match_score(
    title: str,
    site_name: str,
    departments: list[str],
    profile_terms: list[tuple[str, float]],
) -> float:
    if not profile_terms:
        return 0.0

    department_text = " ".join(item for item in departments if item)
    haystack_primary = " ".join([title, department_text, site_name])
    haystack_secondary = " ".join([department_text, site_name])

    score = 0.0
    for term, weight in profile_terms:
        if term and term in title:
            score += 1.4 * weight
        elif term and term in haystack_secondary:
            score += 1.0 * weight
    return score


def _prefix_bonus(text: str, prefix: str) -> float:
    if not prefix:
        return 0.0
    if text.startswith(prefix):
        return 18.0
    if prefix in text:
        return 9.0
    lowered_text = text.lower()
    lowered_prefix = prefix.lower()
    if lowered_text.startswith(lowered_prefix):
        return 14.0
    if lowered_prefix in lowered_text:
        return 7.0
    return 0.0


def _profile_bonus(text: str, profile_terms: list[str]) -> float:
    if not profile_terms:
        return 0.0

    score = 0.0
    for term in profile_terms:
        if term and term in text:
            score += 11.0
    return score


def _intent_bonus(text: str, prefix: str) -> float:
    if prefix in {"培养", "培养计划", "培养方案"} and "培养方案" in text:
        return 18.0
    if prefix in {"招生", "推免", "夏令营"} and any(term in text for term in ("招生", "推免", "夏令营")):
        return 16.0
    return 0.0


def _text_matches_prefix(text: str, prefix: str) -> bool:
    if not prefix:
        return True
    if contains_cjk(prefix):
        return prefix in text
    lowered_text = text.lower()
    lowered_prefix = prefix.lower()
    return lowered_prefix in lowered_text


def _is_human_readable_suggestion(text: str) -> bool:
    compact = text.strip()
    if not compact:
        return False
    if RAW_FILE_RE.fullmatch(compact):
        return False
    if len(compact) > 90:
        return False
    return True


def _build_correction_hint(prefix: str, corrected_text: str) -> CorrectionHintData:
    matcher = SequenceMatcher(a=prefix, b=corrected_text)
    wrong_start = 0
    wrong_end = 0
    has_change = False

    for tag, start_a, end_a, _, _ in matcher.get_opcodes():
        if tag == "equal":
            continue
        has_change = True
        if wrong_end == 0 and wrong_start == 0:
            wrong_start = start_a
            wrong_end = end_a
        else:
            wrong_start = min(wrong_start, start_a)
            wrong_end = max(wrong_end, end_a)

    if not has_change:
        return CorrectionHintData(
            corrected_text=corrected_text,
            wrong_start=0,
            wrong_end=min(len(prefix), 1),
            message=f"你是否想输入“{corrected_text}”？",
        )

    if wrong_start >= len(prefix):
        wrong_start = max(0, len(prefix) - 1)
    if wrong_end <= wrong_start:
        wrong_end = min(len(prefix), wrong_start + 1)

    return CorrectionHintData(
        corrected_text=corrected_text,
        wrong_start=wrong_start,
        wrong_end=wrong_end,
        message=f"你是否想输入“{corrected_text}”？",
    )


def _guess_correction_from_candidates(prefix: str, candidates: list[str]) -> str | None:
    if not prefix:
        return None

    best_text = ""
    best_score = 0.0
    prefix_length = len(prefix)
    candidate_lengths = [prefix_length]

    for candidate in candidates:
        compact = re.sub(r"\s+", "", candidate)
        if len(compact) < max(candidate_lengths):
            continue

        windows = {compact}
        for window_length in candidate_lengths:
            if window_length <= 0 or window_length > len(compact):
                continue
            for start in range(0, len(compact) - window_length + 1):
                windows.add(compact[start : start + window_length])

        for window in windows:
            if window == prefix:
                continue
            if _is_completion_like(prefix, window):
                continue
            if not _is_plausible_correction(prefix, window):
                continue
            score = SequenceMatcher(a=prefix, b=window).ratio()
            if score > best_score:
                best_score = score
                best_text = window

    if best_score >= 0.72:
        return best_text
    return None


def _is_completion_like(prefix: str, candidate: str) -> bool:
    compact_prefix = re.sub(r"\s+", "", prefix)
    compact_candidate = re.sub(r"\s+", "", candidate)
    if not compact_prefix or not compact_candidate:
        return False
    if compact_candidate == compact_prefix:
        return False
    return compact_prefix in compact_candidate or compact_candidate in compact_prefix


def _is_plausible_correction(prefix: str, candidate: str) -> bool:
    compact_prefix = re.sub(r"\s+", "", prefix)
    compact_candidate = re.sub(r"\s+", "", candidate)
    if len(compact_prefix) != len(compact_candidate):
        return False

    diff_count = sum(1 for left, right in zip(compact_prefix, compact_candidate) if left != right)
    return diff_count == 1


def _has_valid_prefix_match(prefix: str, candidates: list[str]) -> bool:
    compact_prefix = re.sub(r"\s+", "", prefix)
    if not compact_prefix:
        return False

    for candidate in candidates:
        compact_candidate = re.sub(r"\s+", "", candidate)
        if not compact_candidate:
            continue
        if compact_candidate == compact_prefix:
            return True
        if compact_candidate.startswith(compact_prefix):
            return True
    return False


async def _metadata_lexicon_candidates(es, index_name: str) -> list[str]:
    global metadata_lexicon_cache

    if metadata_lexicon_cache is not None:
        return metadata_lexicon_cache

    response = await es.search(
        index=index_name,
        size=0,
        aggs={
            "department_terms": {"terms": {"field": "departments", "size": 200}},
            "site_terms": {"terms": {"field": "site_name", "size": 200}},
        },
    )

    values: list[str] = []
    for agg_name in ("department_terms", "site_terms"):
        for bucket in response.get("aggregations", {}).get(agg_name, {}).get("buckets", []):
            key = str(bucket.get("key", "")).strip()
            if not key:
                continue
            values.append(key)
            values.extend(_expand_lexicon_variants(key))

    metadata_lexicon_cache = list(dict.fromkeys(item for item in values if item))
    return metadata_lexicon_cache


def _expand_lexicon_variants(text: str) -> list[str]:
    variants = {text.strip()}
    queue = [text.strip()]

    while queue:
        current = queue.pop()
        for prefix in LEXICON_PREFIXES:
            if current.startswith(prefix) and len(current) > len(prefix) + 1:
                candidate = current[len(prefix) :].strip()
                if candidate and candidate not in variants:
                    variants.add(candidate)
                    queue.append(candidate)

        for suffix in LEXICON_SUFFIXES:
            if current.endswith(suffix) and len(current) > len(suffix) + 1:
                candidate = current[: -len(suffix)].strip()
                if candidate and candidate not in variants:
                    variants.add(candidate)
                    queue.append(candidate)

    return list(variants)
