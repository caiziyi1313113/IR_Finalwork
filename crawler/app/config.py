from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CrawlSettings(BaseSettings):
    """爬虫配置类 - 使用 Pydantic 管理所有配置项"""

    # 忽略未定义的环境变量，避免报错
    model_config = SettingsConfigDict(extra="ignore")

    # elasticsearch 配置
    es_url: str = Field(default="http://elasticsearch:9200", alias="ES_URL")
    es_index: str = Field(default="nku_pages", alias="ES_INDEX")
    
    # tika 工具配置，用于文档内容解析，比如paf,word
    tika_url: str = Field(default="http://tika:9998", alias="TIKA_URL")

    # 爬虫配置
    crawl_max_pages: int = Field(default=120000, alias="CRAWL_MAX_PAGES")
    crawl_concurrency: int = Field(default=12, alias="CRAWL_CONCURRENCY")
    # 每个主机的爬取间隔，单位为秒，避免过于频繁地访问同一主机导致被封禁
    crawl_per_host_delay_seconds: float = Field(default=1.5, alias="CRAWL_PER_HOST_DELAY_SECONDS")
    # 爬取超时时间，单位为秒，避免爬虫长时间卡在某个请求上
    crawl_timeout_seconds: int = Field(default=20, alias="CRAWL_TIMEOUT_SECONDS")
    # 爬虫使用的 User-Agent，标明爬虫身份，避免被误认为恶意爬虫而被封禁
    crawl_user_agent: str = Field(
        default="NK-XiaoLingTong-CourseBot/1.0 (+https://www.nankai.edu.cn/)",
        alias="CRAWL_USER_AGENT",
    )


@lru_cache
def get_settings() -> CrawlSettings:
    return CrawlSettings()

