from __future__ import annotations

from app.services.search.text_utils import joined_text, normalize_text

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "notice": ("通知", "公告", "公示", "截止", "安排", "须知"),
    "training_plan": ("培养方案", "课程", "学分", "教学计划", "选课", "课表"),
    "teacher_research": (
        "导师",
        "教师",
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
    ),
    "admission": ("招生", "推免", "夏令营", "复试", "录取", "报名"),
    "document": ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "下载", "附件"),
    "news": ("新闻", "报道", "要闻", "动态", "快讯"),
    "navigation": ("学院", "大学", "研究院", "研究生院", "教务处", "图书馆"),
}

INTENT_DOCUMENT_HINTS: dict[str, dict[str, tuple[str, ...]]] = {
    "notice": {
        "content_type": ("通知公告", "通知", "公告"),
        "title": ("通知", "公告", "公示", "安排", "报名", "截止"),
        "site_name": ("教务处", "研究生院", "招生", "学院"),
        "doc_kind": ("html", "pdf"),
    },
    "training_plan": {
        "content_type": ("培养方案", "教学计划", "课程信息"),
        "title": ("培养方案", "课程", "学分", "教学计划", "选课"),
        "site_name": ("教务处", "学院"),
        "doc_kind": ("pdf", "doc", "docx", "html"),
    },
    "teacher_research": {
        "content_type": ("教师主页", "科研", "实验室", "学术讲座", "讲座活动", "学术活动"),
        "title": ("教师", "导师", "研究方向", "实验室", "论文", "讲座", "报告", "论坛", "研讨会"),
        "site_name": ("学院", "实验室", "新闻网"),
        "doc_kind": ("html", "pdf"),
    },
    "admission": {
        "content_type": ("通知公告", "招生信息"),
        "title": ("招生", "推免", "夏令营", "复试", "录取"),
        "site_name": ("本科招生网", "研究生招生网", "研究生院"),
        "doc_kind": ("html", "pdf", "doc", "docx"),
    },
    "document": {
        "content_type": ("附件文档", "培养方案", "通知公告"),
        "title": ("下载", "附件", "pdf", "doc", "docx", "xls", "xlsx"),
        "site_name": tuple(),
        "doc_kind": ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx"),
    },
    "news": {
        "content_type": ("新闻动态", "新闻"),
        "title": ("新闻", "报道", "要闻", "快讯"),
        "site_name": ("新闻网", "南开大学"),
        "doc_kind": ("html",),
    },
}


def detect_query_intent(query: str) -> str:
    normalized = normalize_text(query)
    if not normalized:
        return "general"

    scores = {
        intent: sum(1 for keyword in keywords if keyword and keyword in normalized)
        for intent, keywords in INTENT_KEYWORDS.items()
    }

    if scores["document"] > 0:
        return "document"

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if ranked and ranked[0][1] > 0:
        return ranked[0][0]

    if len(query.strip()) <= 8 and any(suffix in query for suffix in INTENT_KEYWORDS["navigation"]):
        return "navigation"
    return "general"


def score_document_for_intent(source: dict, intent: str) -> float:
    if intent == "general":
        return 0.0

    if intent == "navigation":
        return _navigation_score(source)

    hints = INTENT_DOCUMENT_HINTS.get(intent)
    if not hints:
        return 0.0

    title = normalize_text(source.get("title", ""))
    anchor_texts = normalize_text(source.get("anchor_texts", ""))
    site_name = normalize_text(source.get("site_name", ""))
    content_type = normalize_text(source.get("content_type", ""))
    doc_kind = normalize_text(source.get("doc_kind", ""))

    title_score = _ratio_hit(joined_text([title, anchor_texts]), hints.get("title", ()))
    content_type_score = _ratio_hit(content_type, hints.get("content_type", ()))
    site_score = _ratio_hit(site_name, hints.get("site_name", ()))
    doc_kind_score = 1.0 if doc_kind and doc_kind in {item.lower() for item in hints.get("doc_kind", ())} else 0.0

    score = 0.45 * title_score + 0.25 * content_type_score + 0.2 * site_score + 0.1 * doc_kind_score
    return min(score, 1.0)


def _navigation_score(source: dict) -> float:
    title = normalize_text(source.get("title", ""))
    site_name = normalize_text(source.get("site_name", ""))
    url = normalize_text(source.get("url", ""))
    doc_kind = normalize_text(source.get("doc_kind", ""))
    departments = " ".join(source.get("departments", []) or [])
    department_text = normalize_text(departments)

    score = 0.0
    if doc_kind == "html":
        score += 0.2
    if len(title) <= 28:
        score += 0.2
    if site_name:
        score += 0.25
    if department_text and department_text in title:
        score += 0.2
    if url.endswith(".htm") or url.endswith(".html") or url.endswith("/"):
        score += 0.15
    return min(score, 1.0)


def _ratio_hit(text: str, keywords: tuple[str, ...]) -> float:
    if not keywords:
        return 0.0
    matched = sum(1 for keyword in keywords if keyword and normalize_text(keyword) in text)
    return matched / len(keywords)
