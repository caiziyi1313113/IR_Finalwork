from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings
from app.extractors.document import extract_document_text
from app.fetcher import Fetcher
from app.parser import extract_html_record
from app.pipelines.index_record import build_index_record
from app.robots import RobotsCache
from app.seeds import ALLOWED_HOSTS, SEED_SITES
from app.storage.writer import append_jsonl, save_snapshot

DOCUMENT_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}

CHECKPOINT_PATH = Path("/data/clean/crawler_checkpoint.json")


class CrawlRunner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.fetcher = Fetcher(self.settings)
        self.robots = RobotsCache(self.settings.crawl_user_agent)
        
        # 【持久化核心】尝试恢复断点，如果失败则初始化新队列
        frontier_list, seen_list, self.processed_pages = self._load_checkpoint()
        
        self.frontier = deque(frontier_list)
        self.seen_urls: set[str] = set(seen_list)
        self.anchor_memory: dict[str, list[str]] = defaultdict(list)

    def _seed_urls(self) -> list[str]:
        urls: list[str] = []
        for site_meta in SEED_SITES.values():
            urls.extend(site_meta["seeds"])  # type: ignore[arg-type]
        return urls

    def _load_checkpoint(self) -> tuple[list[str], list[str], int]:
        """从本地硬盘读取上次中断的进度"""
        if CHECKPOINT_PATH.exists():
            try:
                data = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
                print(f" Detected previous checkpoint. Resuming from page count: {data['processed_pages']}")
                return data["frontier"], data["seen_urls"], data["processed_pages"]
            except Exception as e:
                print(f"读取断点文件失败，将从头开始: {e}")
        
        print(" No checkpoint found. Starting a fresh crawl.")
        return self._seed_urls(), [], 0

    def save_checkpoint(self) -> None:
        """把当前内存里的进度死死写入硬盘"""
        try:
            # 临时把还没跑完的和已经看过的转成 list 存成 json
            data = {
                "frontier": list(self.frontier),
                "seen_urls": list(self.seen_urls),
                "processed_pages": self.processed_pages
            }
            CHECKPOINT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n Progress saved safely. Saved pages: {self.processed_pages}")
        except Exception as e:
            print(f"保存进度快照失败: {e}")

    async def run(self) -> None:
        raw_path = Path("/data/raw/crawl_raw.jsonl")
        clean_path = Path("/data/clean/crawl_clean.jsonl")

        try:
            while self.frontier and self.processed_pages < self.settings.crawl_max_pages:
                batch = []
                while self.frontier and len(batch) < self.settings.crawl_concurrency:
                    url = self.frontier.popleft()
                    if url in self.seen_urls:
                        continue
                    self.seen_urls.add(url)
                    batch.append(url)

                if not batch:
                    break

                await asyncio.gather(*(self._handle_url(url, raw_path, clean_path) for url in batch))
                
                # 每跑完一个批次，自动悄悄保存一下进度，防止突然暴毙
                if self.processed_pages % 20 == 0:
                    self.save_checkpoint()
                    
        except asyncio.CancelledError:
            print("\n 收到中断信号(Ctrl+C)，正在紧急保存进度...")
        finally:
            # 无论是因为爬完了、报错了、还是你手动 Ctrl+C 强退了，都会走进这里保存硬盘
            self.save_checkpoint()
            await self.fetcher.close()
            self._write_adjacency()
            print(f"Crawl finished/paused. processed_pages={self.processed_pages}")

    async def _handle_url(self, url: str, raw_path: Path, clean_path: Path) -> None:
        try:
            host = urlparse(url).netloc
            if host not in ALLOWED_HOSTS:
                return
            if not await self.robots.allowed(url, self.fetcher.session):
                return

            result = await self.fetcher.fetch(url)
            if result is None:
                return

            doc_kind = DOCUMENT_CONTENT_TYPES.get(result.content_type)
            if result.content_type in {"text/html", "application/xhtml+xml"} or url.endswith((".htm", ".html")):
                await self._handle_html(result.url, result.body, result.content_type, raw_path, clean_path)
            elif doc_kind:
                await self._handle_document(result.url, result.body, result.content_type, doc_kind, raw_path, clean_path)
                
        except asyncio.TimeoutError:
            # 【核心安全补丁】捕获本轮让你闪退的超时异常，打印警告，绝不崩溃！
            print(f"[Timeout Warning] 请求超时，已安全跳过: {url}")
            return
        except Exception as e:
            print(f"[Unknown Warning] 遇到未知网络错误: {e}")
            return

    async def _handle_html(self, url: str, body: bytes, content_type: str, raw_path: Path, clean_path: Path) -> None:
        parsed = extract_html_record(url=url, body=body)
        if not parsed["content"]:
            return

        snapshot_path = save_snapshot(url=url, body=body, suffix=".html")
        out_links = []

        for target_url, anchor_text in parsed["links"]:
            target_host = urlparse(target_url).netloc
            if target_host in ALLOWED_HOSTS:
                self.frontier.append(target_url)
                out_links.append(target_url)
                if anchor_text:
                    self.anchor_memory[target_url].append(anchor_text)

        for attachment_url, anchor_text in parsed["attachments"]:
            target_host = urlparse(attachment_url).netloc
            if target_host in ALLOWED_HOSTS:
                self.frontier.append(attachment_url)
                out_links.append(attachment_url)
                if anchor_text:
                    self.anchor_memory[attachment_url].append(anchor_text)

        raw_record = {
            "url": url,
            "title": parsed["title"],
            "content_type": content_type,
            "out_links": out_links,
            "snapshot_path": snapshot_path,
        }
        append_jsonl(raw_path, raw_record)

        record = build_index_record(
            url=url,
            title=parsed["title"],
            content=parsed["content"],
            anchor_texts=self.anchor_memory[url],
            doc_kind="html",
            content_type=content_type,
            snapshot_path=snapshot_path,
            out_links=out_links,
        )
        append_jsonl(clean_path, record)
        self.processed_pages += 1

    async def _handle_document(
        self,
        url: str,
        body: bytes,
        content_type: str,
        doc_kind: str,
        raw_path: Path,
        clean_path: Path,
    ) -> None:
        try:
            content = await extract_document_text(self.settings.tika_url, body)
        except Exception:
            return

        if not content.strip():
            return

        snapshot_path = save_snapshot(url=url, body=body, suffix=f".{doc_kind}")
        raw_record = {
            "url": url,
            "title": url.split("/")[-1],
            "content_type": content_type,
            "snapshot_path": snapshot_path,
        }
        append_jsonl(raw_path, raw_record)

        record = build_index_record(
            url=url,
            title=url.split("/")[-1],
            content=content,
            anchor_texts=self.anchor_memory[url],
            doc_kind=doc_kind,
            content_type=content_type,
            snapshot_path=snapshot_path,
            out_links=[],
        )
        append_jsonl(clean_path, record)
        self.processed_pages += 1

    def _write_adjacency(self) -> None:
        clean_path = Path("/data/clean/crawl_clean.jsonl")
        adjacency: dict[str, list[str]] = {}

        if clean_path.exists():
            for line in clean_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                adjacency[record["url"]] = record.get("out_links", [])

        Path("/data/clean/adjacency.json").write_text(
            json.dumps(adjacency, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


async def main() -> None:
    runner = CrawlRunner()
    await runner.run()


if __name__ == "__main__":
    # 彻底杜绝由于用户疯狂 Ctrl+C 导致没进 finally 的极端情况
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n 手动终止。")