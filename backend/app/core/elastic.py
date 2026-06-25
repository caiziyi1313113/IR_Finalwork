from elasticsearch import AsyncElasticsearch

from app.core.config import get_settings

# 使用单例模式管理全局唯一的 ES 客户端实例
_es_client: AsyncElasticsearch | None = None


def get_es_client() -> AsyncElasticsearch:
    global _es_client
    if _es_client is None:
        settings = get_settings()
        es_kwargs = {}
        if settings.es_request_timeout_seconds > 0:
            es_kwargs["request_timeout"] = settings.es_request_timeout_seconds
        _es_client = AsyncElasticsearch(settings.es_url, **es_kwargs)
    return _es_client


async def close_es_client() -> None:
    global _es_client
    if _es_client is not None:
        await _es_client.close()
        _es_client = None
