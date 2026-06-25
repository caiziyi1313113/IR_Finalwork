from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.query_log import QueryLog
from app.services.search.text_utils import split_profile_terms

QUERY_HISTORY_LIMIT = 30


@dataclass
class BehaviorProfile:
    recent_queries: list[str] = field(default_factory=list)
    weighted_queries: dict[str, float] = field(default_factory=dict)

    def has_signal(self) -> bool:
        return bool(self.recent_queries or self.weighted_queries)


async def build_user_behavior_profile(user_id: int | None, db: Session) -> BehaviorProfile:
    if user_id is None:
        return BehaviorProfile()

    rows = db.execute(
        select(QueryLog.query_text, QueryLog.created_at)
        .where(QueryLog.user_id == user_id)
        .order_by(desc(QueryLog.created_at))
        .limit(QUERY_HISTORY_LIMIT)
    ).all()

    recent_queries: list[str] = []
    weighted_queries: dict[str, float] = {}
    max_weight = 0.0

    for query_text, created_at in rows:
        normalized_query = (query_text or "").strip()
        if not normalized_query:
            continue

        if normalized_query not in recent_queries:
            recent_queries.append(normalized_query)

        weight = _event_weight(created_at)
        weight = max(weight, 0.05)
        weighted_queries[normalized_query] = weighted_queries.get(normalized_query, 0.0) + weight
        max_weight = max(max_weight, weighted_queries[normalized_query])

        for term in split_profile_terms(normalized_query):
            weighted_queries[term] = weighted_queries.get(term, 0.0) + weight * 0.6
            max_weight = max(max_weight, weighted_queries[term])

    if max_weight > 0:
        weighted_queries = {
            key: round(value / max_weight, 6)
            for key, value in weighted_queries.items()
            if key
        }

    return BehaviorProfile(
        recent_queries=recent_queries[:10],
        weighted_queries=weighted_queries,
    )


def _event_weight(event_time: datetime | None) -> float:
    if event_time is None:
        return 1.0

    now = datetime.now(timezone.utc)
    event_dt = event_time if event_time.tzinfo else event_time.replace(tzinfo=timezone.utc)
    days_since_event = max((now - event_dt).total_seconds() / 86400, 0.0)
    return math.exp(-days_since_event / 14)
