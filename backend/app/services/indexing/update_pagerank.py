import asyncio
import json
from hashlib import sha1
from pathlib import Path

from elasticsearch.helpers import async_streaming_bulk

from app.core.config import get_settings
from app.core.elastic import close_es_client, get_es_client
from app.services.ranking.pagerank import compute_pagerank  # 自定义pagerank的实现

CLEAN_JSONL_PATH = Path("/data/clean/crawl_clean.jsonl")


# pagerank 计算脚本

def load_or_build_adjacency(adjacency_path: Path, clean_jsonl_path: Path = CLEAN_JSONL_PATH) -> dict[str, list[str]]:
    if adjacency_path.exists():
        return json.loads(adjacency_path.read_text(encoding="utf-8"))

    if not clean_jsonl_path.exists():
        raise FileNotFoundError(
            f"adjacency file not found: {adjacency_path}; crawl data not found either: {clean_jsonl_path}"
        )

    adjacency: dict[str, list[str]] = {}
    with clean_jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            url = record.get("url")
            if not url:
                continue
            # 取出出链，构建邻接表
            out_links = record.get("out_links") or []
            if not isinstance(out_links, list):
                out_links = []
            adjacency[url] = [str(link) for link in out_links if isinstance(link, str) and link]

    adjacency_path.parent.mkdir(parents=True, exist_ok=True)
    adjacency_path.write_text(json.dumps(adjacency, ensure_ascii=False), encoding="utf-8")
    print(f"Built adjacency file from crawl data: {adjacency_path}")
    return adjacency

# 计算 PageRank 并更新到 Elasticsearch 索引中
async def update_pagerank(adjacency_path: Path | None = None) -> None:
    settings = get_settings()
    es = get_es_client()
    adjacency_path = adjacency_path or Path("/data/clean/adjacency.json")
    adjacency = load_or_build_adjacency(adjacency_path=adjacency_path)
    pagerank_scores = compute_pagerank(adjacency)

    if not pagerank_scores:
        print("No PageRank scores produced. Check whether crawl_clean.jsonl contains valid url/out_links data.")
        return

    actions = (
        {
            "_op_type": "update",
            "_index": settings.es_index,
            "_id": sha1(record_id.encode("utf-8")).hexdigest(),
            "doc": {"pagerank": score},
            "doc_as_upsert": False,
        }
        for record_id, score in pagerank_scores.items()
    )

    updated = 0
    async for ok, result in async_streaming_bulk(es, actions):
        if not ok:
            print(f"failed to update pagerank: {result}")
            continue
        updated += 1
    print(f"Updated pagerank for {updated} documents.")


if __name__ == "__main__":
    try:
        asyncio.run(update_pagerank())
    finally:
        asyncio.run(close_es_client())
