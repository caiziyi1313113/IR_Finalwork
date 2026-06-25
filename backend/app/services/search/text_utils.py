from __future__ import annotations

import re

ASCII_PREFIX_RE = re.compile(r"^[a-zA-Z0-9\s']+$")
TEXT_SPLIT_RE = re.compile(r"[\s,，。；;、|/()（）【】\[\]<>《》]+")


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def looks_like_pinyin(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and bool(ASCII_PREFIX_RE.fullmatch(stripped))


def normalize_pinyin_query(text: str) -> tuple[str, str]:
    spaced = re.sub(r"\s+", " ", text.strip().lower())
    compact = re.sub(r"[^a-z0-9]", "", spaced)
    return spaced, compact


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def split_profile_terms(text: str, min_length: int = 2) -> list[str]:
    terms: list[str] = []
    for part in TEXT_SPLIT_RE.split(text or ""):
        normalized = part.strip()
        if len(normalized) >= min_length and normalized not in terms:
            terms.append(normalized)
    return terms


def joined_text(parts: list[str] | tuple[str, ...]) -> str:
    return " ".join(item for item in parts if item).strip()
