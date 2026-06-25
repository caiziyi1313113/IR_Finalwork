import asyncio
import json
from pathlib import Path

from elasticsearch.helpers import async_bulk

from app.core.config import get_settings
from app.core.elastic import close_es_client, get_es_client
from app.services.indexing.enrichment import enrich_record_for_index
from app.services.search.semantic_service import build_document_semantic_text, get_semantic_service


async def bulk_load(clean_dir: Path | None = None) -> None:
    settings = get_settings()
    es = get_es_client()
    semantic_service = get_semantic_service()
    clean_dir = clean_dir or Path("/data/clean")

    if settings.semantic_enabled:
        await asyncio.to_thread(semantic_service.preload_indexing_models)

    actions: list[dict] = []
    pending_records: list[dict] = []

    async def flush_records() -> None:
        nonlocal actions, pending_records
        if not pending_records:
            return

        if settings.semantic_enabled:
            semantic_texts = [
                build_document_semantic_text(record, max_chars=settings.semantic_text_max_chars)
                for record in pending_records
            ]
            vectors = await asyncio.to_thread(semantic_service.encode_documents, semantic_texts)

            for record, vector in zip(pending_records, vectors, strict=False):
                record[settings.vector_field_name] = vector
                actions.append(
                    {
                        "_index": settings.es_index,
                        "_id": record["doc_id"],
                        "_source": record,
                    }
                )
        else:
            for record in pending_records:
                actions.append(
                    {
                        "_index": settings.es_index,
                        "_id": record["doc_id"],
                        "_source": record,
                    }
                )

        pending_records = []

        if len(actions) >= 500:
            await async_bulk(es, actions)
            actions.clear()

    for jsonl_path in clean_dir.glob("*.jsonl"):
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                pending_records.append(enrich_record_for_index(json.loads(line)))
                if len(pending_records) >= settings.embedding_batch_size:
                    await flush_records()

    await flush_records()
    if actions:
        await async_bulk(es, actions)
    print("Bulk load complete.")


if __name__ == "__main__":
    try:
        asyncio.run(bulk_load())
    finally:
        asyncio.run(close_es_client())
