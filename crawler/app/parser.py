from __future__ import annotations
import logging
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
import trafilatura

# 设置一个简单的日志器，用来记录跳过的脏数据，方便调试
logger = logging.getLogger("crawler.parser")

DOCUMENT_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def extract_html_record(url: str, body: bytes) -> dict:
    html = body.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else ""
    main_text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""

    links: list[tuple[str, str]] = []
    attachments: list[tuple[str, str]] = []
    
    for anchor in soup.select("a[href]"):
        try:
            raw_href = anchor["href"].strip()
            
            # 【防御机制 1】过滤掉空链接、JavaScript 伪协议、或纯锚点跳转
            if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
                
            # 【防御机制 2】如果 href 里面包含空格、中文字符，且根本没有 http 影子，通常是无意写错的新闻标题，直接过滤
            if " " in raw_href and "http" not in raw_href:
                continue

            # 执行可能抛出 ValueError 的 URL 拼接
            target = urljoin(url, raw_href)
            target, _ = urldefrag(target)
            target = target.strip()
            
            if not target.startswith("http"):
                continue
                
            anchor_text = anchor.get_text(" ", strip=True)
            path = urlparse(target).path.lower()
            
            if any(path.endswith(suffix) for suffix in DOCUMENT_SUFFIXES):
                attachments.append((target, anchor_text))
            else:
                links.append((target, anchor_text))
                
        except ValueError as ve:
            # 【防御机制 3】金钟罩：捕获所有类似 Unicode 归一化失败、畸形字符等导致的 URL 解析错误
            print(f"[Warning] 跳过畸形 URL 脏数据: '{anchor.get('href')}' | 错误原因: {ve}")
            continue
        except Exception as e:
            # 捕获其他未知异常，确保单条超链接错误绝不导致整个爬虫主线程退出
            print(f"[Warning] 遇到未知脏链接错误: {e}")
            continue

    return {
        "title": title,
        "content": main_text,
        "links": links,
        "attachments": attachments,
        "html": html,
    }

