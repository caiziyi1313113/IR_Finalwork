import re
from collections.abc import Iterable

from pypinyin import Style, lazy_pinyin

PINYIN_TOKEN_RE = re.compile(r"[a-z0-9]+")

# 索引数据增强模块
def enrich_record_for_index(record: dict) -> dict:
    """
    主函数：为文档生成搜索增强字段
    
    输入文档会新增以下字段：
    - suggest_text: 中文关键词列表
    - suggest_pinyin: 拼音搜索词
    - suggest_initials: 拼音首字母搜索词
    """
    normalized = dict(record)
    # 收集用于搜索建议的中文关键词，并生成拼音和首字母版本
    chinese_terms = collect_suggest_terms(normalized)
    pinyin_terms, initial_terms = build_pinyin_terms(chinese_terms)

    normalized["suggest_text"] = chinese_terms
    normalized["suggest_pinyin"] = pinyin_terms
    normalized["suggest_initials"] = initial_terms

    # Keep the original completion field so older code paths and debugging in Kibana
    # still have a simple inspectable input list.
    existing_suggest = normalized.get("suggest", {})
    existing_inputs = existing_suggest.get("input", []) if isinstance(existing_suggest, dict) else []
    normalized["suggest"] = {
        "input": dedupe_preserve_order([*chinese_terms, *existing_inputs]),
    }
    return normalized


def collect_suggest_terms(record: dict) -> list[str]:
    """
    从文档中提取可用于搜索建议的词汇
    
    来源：标题、站点名、部门、锚文本(注意没有正文)
    """
    values: list[str] = []
    # 标题
    values.extend(ensure_list(record.get("title")))
    # 站点名
    values.extend(ensure_list(record.get("site_name")))
    # 部门
    values.extend(ensure_list(record.get("departments")))
    # 锚文本
    anchor_texts = record.get("anchor_texts", "")
    if isinstance(anchor_texts, str):
        values.extend([item.strip() for item in anchor_texts.split() if item.strip()])

    return dedupe_preserve_order(clean_text(item) for item in values if clean_text(item))


def build_pinyin_terms(chinese_terms: Iterable[str]) -> tuple[list[str], list[str]]:
    """
    为中文词汇生成拼音搜索词
    
    Returns:
        (拼音搜索词列表, 首字母搜索词列表)
    
    Examples:
        "南开大学" → ("nan kai da xue", "nankaidaxue")
        "南开大学" → ("nkdx", "nkdaxue")
    """
    pinyin_terms: list[str] = []
    initial_terms: list[str] = []

    for term in chinese_terms:
        syllables = lazy_pinyin(term, style=Style.NORMAL, errors="default", strict=False)
        initials = lazy_pinyin(term, style=Style.FIRST_LETTER, errors="default", strict=False)

        pinyin_tokens = [normalize_ascii(token) for token in syllables if normalize_ascii(token)]
        initial_tokens = [normalize_ascii(token) for token in initials if normalize_ascii(token)]

        if pinyin_tokens:
            pinyin_terms.append(" ".join(pinyin_tokens))
            pinyin_terms.append("".join(pinyin_tokens))
        if initial_tokens:
            initial_terms.append("".join(initial_tokens))

    return dedupe_preserve_order(pinyin_terms), dedupe_preserve_order(initial_terms)


def ensure_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_ascii(value: str) -> str:
    """
    标准化 ASCII 字符串用于搜索
    - 转小写
    - 只保留字母和数字
    """
    lowered = value.strip().lower()
    tokens = PINYIN_TOKEN_RE.findall(lowered)
    return "".join(tokens)


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered

