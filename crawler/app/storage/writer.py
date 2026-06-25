from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from urllib.parse import urlparse


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def snapshot_path_for(url: str, suffix: str) -> Path:
    host = urlparse(url).netloc.replace(":", "_")
    name = sha1(url.encode("utf-8")).hexdigest()
    return Path("/data/snapshots") / host / f"{name}{suffix}"


def save_snapshot(url: str, body: bytes, suffix: str) -> str:
    path = snapshot_path_for(url=url, suffix=suffix)
    ensure_parent(path)
    path.write_bytes(body)
    return str(path)


def append_jsonl(path: Path, record: dict) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

