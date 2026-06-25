from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from urllib.parse import urlparse

from app.seeds import SEED_SITES


def build_index_record(
    url: str,
    title: str,
    content: str,
    anchor_texts: list[str],
    doc_kind: str,
    content_type: str,
    snapshot_path: str,
    out_links: list[str],
) -> dict:
    host = urlparse(url).netloc
    site_meta = SEED_SITES.get(host, {})
    cleaned_anchor_texts = [item for item in anchor_texts if item]
    doc_id = sha1(url.encode("utf-8")).hexdigest()

    return {
        "doc_id": doc_id,
        "url": url,
        "title": title or url,
        "content": content[:200000],
        "anchor_texts": " ".join(cleaned_anchor_texts[:30]),
        "anchor_wc": " ".join(cleaned_anchor_texts[:10]),
        "title_wc": title or url,
        "site_name": site_meta.get("site_name", host),
        "departments": site_meta.get("departments", []),
        "audiences": site_meta.get("audiences", []),
        "doc_kind": doc_kind,
        "content_type": content_type,
        "file_extension": doc_kind,
        "publish_time": datetime.now(timezone.utc).isoformat(),
        "pagerank": 0.0,
        "snapshot_path": snapshot_path,
        "source_domain": host,
        "out_links": out_links[:300],
        "suggest": {
            "input": list(
                dict.fromkeys(
                    [title]
                    + cleaned_anchor_texts[:10]
                    + list(site_meta.get("departments", []))
                    + [site_meta.get("site_name", host)]
                )
            )
        },
    }

