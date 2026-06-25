from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    # Explicit profile fields.
    identity: Mapped[str] = mapped_column(String(30), default="本科生")
    college: Mapped[str] = mapped_column(String(100), default="")
    major: Mapped[str] = mapped_column(String(100), default="")
    interest_tags: Mapped[str] = mapped_column(Text, default="[]")

    # Legacy field kept for backward compatibility.
    search_need: Mapped[str] = mapped_column(Text, default="")
    search_need_text: Mapped[str] = mapped_column(Text, default="")

    # Cached AI behavior profile.
    ai_behavior_profile: Mapped[str] = mapped_column(Text, default="{}")
    ai_behavior_summary: Mapped[str] = mapped_column(Text, default="")
    ai_behavior_source_hash: Mapped[str] = mapped_column(String(64), default="")
    ai_behavior_status: Mapped[str] = mapped_column(String(20), default="idle")
    ai_behavior_error: Mapped[str] = mapped_column(Text, default="")
    ai_behavior_query_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_behavior_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def get_interest_tags(self) -> list[str]:
        try:
            value = json.loads(self.interest_tags or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []

        tags: list[str] = []
        for item in value:
            normalized = str(item).strip()
            if normalized and normalized not in tags:
                tags.append(normalized)
        return tags

    def set_interest_tags(self, values: list[str] | None) -> None:
        tags: list[str] = []
        for item in values or []:
            normalized = str(item).strip()
            if normalized and normalized not in tags:
                tags.append(normalized)
        self.interest_tags = json.dumps(tags, ensure_ascii=False)

    def get_ai_behavior_profile(self) -> dict[str, Any]:
        try:
            value = json.loads(self.ai_behavior_profile or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def set_ai_behavior_profile(self, payload: dict[str, Any] | None) -> None:
        self.ai_behavior_profile = json.dumps(payload or {}, ensure_ascii=False)

    @property
    def profile_completed(self) -> bool:
        return bool(
            self.college.strip()
            or self.major.strip()
            or self.search_need_text.strip()
            or self.get_interest_tags()
        )
