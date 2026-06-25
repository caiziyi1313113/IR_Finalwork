import asyncio

from app.core.config import get_settings
from app.core.elastic import close_es_client, get_es_client
from app.services.indexing.index_schema import build_index_schema

# 这是 Elasticsearch 索引初始化脚本，用于在首次部署时创建搜索索引
async def ensure_index() -> None:
    settings = get_settings()
    es = get_es_client()
    exists = await es.indices.exists(index=settings.es_index)
    if exists:
        print(f"Index already exists: {settings.es_index}")
        return
    await es.indices.create(index=settings.es_index, body=build_index_schema())
    print(f"Created index: {settings.es_index}")


if __name__ == "__main__":
    try:
        asyncio.run(ensure_index())
    finally:
        asyncio.run(close_es_client())

