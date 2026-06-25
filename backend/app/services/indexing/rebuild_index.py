import asyncio

from app.core.config import get_settings
from app.core.elastic import close_es_client, get_es_client
from app.services.indexing.index_schema import build_index_schema

# 增加了拼音和汉字自动补全后的索引重建

async def rebuild_index() -> None:
    settings = get_settings()
    es = get_es_client()

    exists = await es.indices.exists(index=settings.es_index)
    if exists:
        await es.indices.delete(index=settings.es_index)
        print(f"Deleted index: {settings.es_index}")

    await es.indices.create(index=settings.es_index, body=build_index_schema())
    print(f"Created index: {settings.es_index}")


if __name__ == "__main__":
    try:
        asyncio.run(rebuild_index())
    finally:
        asyncio.run(close_es_client())
