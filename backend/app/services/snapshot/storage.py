import re
from html import escape
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.core.elastic import get_es_client


SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>.*?</script\s*>")
BASE_RE = re.compile(r"(?is)<base\b[^>]*>")
META_REFRESH_RE = re.compile(r'(?is)<meta\b[^>]+http-equiv\s*=\s*["\']?refresh["\']?[^>]*>')


def _inject_head_tag(html: str, original_url: str) -> str:
    safe_url = escape(original_url, quote=True)
    extra_head = (
        f'<base href="{safe_url}">\n'
        '<meta name="referrer" content="no-referrer">\n'
    )

    if re.search(r"(?is)<head\b[^>]*>", html):
        return re.sub(r"(?is)(<head\b[^>]*>)", rf"\1\n{extra_head}", html, count=1)
    if re.search(r"(?is)<html\b[^>]*>", html):
        return re.sub(r"(?is)(<html\b[^>]*>)", rf"\1\n<head>\n{extra_head}</head>", html, count=1)
    return f"<head>\n{extra_head}</head>\n{html}"


def _prepare_html_snapshot(html: str, original_url: str) -> str:
    cleaned = SCRIPT_RE.sub("", html)
    cleaned = BASE_RE.sub("", cleaned)
    cleaned = META_REFRESH_RE.sub("", cleaned)
    return _inject_head_tag(cleaned, original_url)


async def read_snapshot_text(doc_id: str) -> str:
    settings = get_settings()
    es = get_es_client()
    response = await es.get(index=settings.es_index, id=doc_id)
    snapshot_path = response["_source"].get("snapshot_path")
    original_url = str(response["_source"].get("url") or "").strip()
    if not snapshot_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该文档没有可用快照")

    path = Path(snapshot_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照文件不存在")

    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        html = path.read_text(encoding="utf-8", errors="ignore")
        if original_url:
            return _prepare_html_snapshot(html, original_url)
        return html

    # Binary documents are wrapped in a simple HTML shell so the browser can still display metadata.
    return f"""
    <html>
      <head><meta charset="utf-8"><title>附件快照</title></head>
      <body>
        <h2>附件快照</h2>
        <p>原始文件路径: {path}</p>
        <p>浏览器无法直接嵌入该格式时，可根据本地文件路径打开原件。</p>
      </body>
    </html>
    """
