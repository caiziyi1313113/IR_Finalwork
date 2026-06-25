from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.user import User
from app.services.search.text_utils import normalize_text, split_profile_terms

COLLEGE_SUFFIXES = (
    "学院",
    "研究院",
    "研究生院",
    "本科招生网",
    "研究生招生网",
    "招生网",
    "教务处",
    "新闻网",
    "南开大学",
)
MAJOR_SUFFIXES = (
    "科学与技术",
    "科学",
    "技术",
    "工程",
    "专业",
    "方向",
)
TERM_SPLIT_RE = re.compile(r"[、,，/|与和\s]+")


@dataclass
class PersonalizationContext:
    profile_vector: list[float] = field(default_factory=list)
    college_terms: list[str] = field(default_factory=list)
    major_terms: list[str] = field(default_factory=list)
    interest_terms: list[str] = field(default_factory=list)
    history_terms: dict[str, float] = field(default_factory=dict)

    def enabled(self) -> bool:
        return bool(
            self.profile_vector
            or self.college_terms
            or self.major_terms
            or self.interest_terms
            or self.history_terms
        )


@dataclass
class PersonalizationScores:
    profile_match_score: float = 0.0
    personal_score: float = 0.0


def cosine_to_unit(score: float) -> float:
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def build_personalization_context(
    user: User | None,
    profile_vector: list[float],
    history_terms: dict[str, float] | None = None,
) -> PersonalizationContext:
    if user is None:
        return PersonalizationContext()

    interest_terms = list(user.get_interest_tags())
    if user.search_need_text.strip():
        interest_terms.extend(split_profile_terms(user.search_need_text))

    return PersonalizationContext(
        profile_vector=list(profile_vector),
        college_terms=_expand_college_terms(user.college),
        major_terms=_expand_major_terms(user.major),
        interest_terms=_dedupe(item.strip() for item in interest_terms if item.strip()),
        history_terms=_normalize_history_terms(history_terms or {}),
    )


def compute_profile_vector_score(
    context: PersonalizationContext,
    doc_vector: list[float],
    cosine_score: float,
    *,
    title: str = "",
    site_name: str = "",
    departments: list[str] | None = None,
    content_type: str = "",
    snippet: str = "",
    semantic_text: str = "",
) -> PersonalizationScores:
    if not context.enabled():
        return PersonalizationScores()

    departments = departments or []
    primary_text = normalize_text(" ".join([title, site_name, content_type, *departments]))
    full_text = normalize_text(" ".join([title, site_name, content_type, *departments, snippet, semantic_text]))

    vector_score = 0.0
    if context.profile_vector and doc_vector:
        vector_score = cosine_to_unit(cosine_score)

    college_score = _term_match_score(context.college_terms, primary_text, full_text)
    major_score = _term_match_score(context.major_terms, primary_text, full_text)
    interest_score = _term_match_score(context.interest_terms, primary_text, full_text)
    explicit_score = 0.45 * college_score + 0.35 * major_score + 0.20 * interest_score
    history_score = _history_match_score(context.history_terms, primary_text, full_text)

    weighted_sum = 0.0
    total_weight = 0.0

    if context.college_terms or context.major_terms or context.interest_terms:
        weighted_sum += 0.7 * explicit_score
        total_weight += 0.7
    if context.history_terms:
        weighted_sum += 0.2 * history_score
        total_weight += 0.2
    if context.profile_vector and doc_vector:
        weighted_sum += 0.1 * vector_score
        total_weight += 0.1

    if total_weight <= 0:
        personal_score = vector_score
    else:
        personal_score = weighted_sum / total_weight

    personal_score = max(0.0, min(1.0, personal_score))
    return PersonalizationScores(
        profile_match_score=personal_score,
        personal_score=personal_score,
    )


def _expand_college_terms(college: str) -> list[str]:
    normalized = college.strip()
    if not normalized:
        return []

    terms = [normalized]
    if normalized.startswith("南开大学") and len(normalized) > 4:
        terms.append(normalized.removeprefix("南开大学"))

    for suffix in COLLEGE_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
            terms.append(normalized[: -len(suffix)])

    for part in TERM_SPLIT_RE.split(normalized):
        if len(part) >= 2:
            terms.append(part)

    return _dedupe(term for term in terms if len(term.strip()) >= 2)


def _expand_major_terms(major: str) -> list[str]:
    normalized = major.strip()
    if not normalized:
        return []

    terms = [normalized]
    terms.extend(split_profile_terms(normalized))

    for suffix in MAJOR_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
            terms.append(normalized[: -len(suffix)])

    for part in TERM_SPLIT_RE.split(normalized):
        cleaned = part.strip()
        if len(cleaned) >= 2:
            terms.append(cleaned)
            for suffix in MAJOR_SUFFIXES:
                if cleaned.endswith(suffix) and len(cleaned) > len(suffix) + 1:
                    terms.append(cleaned[: -len(suffix)])

    return _dedupe(term for term in terms if len(term.strip()) >= 2)


def _normalize_history_terms(history_terms: dict[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for term, weight in history_terms.items():
        clean_term = str(term).strip()
        if len(clean_term) < 2:
            continue
        normalized[clean_term] = max(normalized.get(clean_term, 0.0), float(weight))
    return normalized


def _term_match_score(terms: list[str], primary_text: str, full_text: str) -> float:
    if not terms:
        return 0.0

    total = 0.0
    matched = 0.0
    for term in terms:
        normalized = normalize_text(term)
        if len(normalized) < 2:
            continue
        total += 1.0
        if normalized in primary_text:
            matched += 1.0
        elif normalized in full_text:
            matched += 0.75

    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, matched / total))


def _history_match_score(history_terms: dict[str, float], primary_text: str, full_text: str) -> float:
    if not history_terms:
        return 0.0

    total_weight = 0.0
    matched_weight = 0.0

    for term, weight in history_terms.items():
        normalized = normalize_text(term)
        if len(normalized) < 2:
            continue
        positive_weight = max(float(weight), 0.0)
        total_weight += positive_weight
        if normalized in primary_text:
            matched_weight += positive_weight
        elif normalized in full_text:
            matched_weight += positive_weight * 0.7

    if total_weight <= 0:
        return 0.0
    return max(0.0, min(1.0, matched_weight / total_weight))


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
