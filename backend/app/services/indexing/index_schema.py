from app.core.config import get_settings


def build_index_schema() -> dict:
    settings = get_settings()

    return {
        "settings": {
            "analysis": {
                "filter": {
                    "zh_shingle_filter": {
                        "type": "shingle",
                        "min_shingle_size": 2,
                        "max_shingle_size": 3,
                    }
                },
                "analyzer": {
                    "zh_shingle_analyzer": {
                        "type": "custom",
                        "tokenizer": "smartcn_tokenizer",
                        "filter": ["lowercase", "zh_shingle_filter"],
                    }
                },
            }
        },
        "mappings": {
            "properties": {
                "url": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "smartcn",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 512},
                        "shingle": {"type": "text", "analyzer": "zh_shingle_analyzer"},
                    },
                },
                "content": {
                    "type": "text",
                    "analyzer": "smartcn",
                    "term_vector": "with_positions_offsets",
                },
                "anchor_texts": {"type": "text", "analyzer": "smartcn"},
                "anchor_wc": {"type": "wildcard"},
                "title_wc": {"type": "wildcard"},
                "site_name": {"type": "keyword"},
                "departments": {"type": "keyword"},
                "audiences": {"type": "keyword"},
                "doc_kind": {"type": "keyword"},
                "content_type": {"type": "keyword"},
                "file_extension": {"type": "keyword"},
                "suggest_text": {
                    "type": "search_as_you_type",
                    "analyzer": "smartcn",
                    "max_shingle_size": 3,
                },
                "suggest_pinyin": {
                    "type": "search_as_you_type",
                    "analyzer": "simple",
                    "max_shingle_size": 3,
                },
                "suggest_initials": {
                    "type": "search_as_you_type",
                    "analyzer": "simple",
                    "max_shingle_size": 3,
                },
                settings.vector_field_name: {
                    "type": "dense_vector",
                    "dims": settings.embedding_dim,
                    "index": True,
                    "similarity": "cosine",
                    "index_options": {
                        "type": "hnsw",
                        "m": 16,
                        "ef_construction": 100,
                    },
                },
                "publish_time": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
                "pagerank": {"type": "float"},
                "snapshot_path": {"type": "keyword"},
                "source_domain": {"type": "keyword"},
                "out_links": {"type": "keyword", "index": False},
                "suggest": {"type": "completion", "analyzer": "smartcn"},
            }
        },
    }
