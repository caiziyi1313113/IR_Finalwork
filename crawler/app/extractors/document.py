from __future__ import annotations

import httpx


async def extract_document_text(tika_url: str, content: bytes) -> str:
    # Tika normalizes office files and PDFs into plain text so that the search
    # layer can index them with the same schema as HTML pages.
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.put(
            f"{tika_url}/tika",
            content=content,
            headers={"Accept": "text/plain"},
        )
        response.raise_for_status()
        return response.text

