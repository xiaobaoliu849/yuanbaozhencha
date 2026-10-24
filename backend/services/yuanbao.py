"""元宝搜索 (Tencent Cloud WSA SearchPro) client.

Docs: https://cloud.tencent.com/document/product/1806/130615
POST https://api.wsa.cloud.tencent.com/SearchPro, Bearer API key, body {"Query": ...}.
Each item of Response.Pages is a JSON *string* with title/url/site/date/passage/favicon.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

URL = os.getenv("YUANBAO_API_URL", "https://api.wsa.cloud.tencent.com/SearchPro")
# Optional extra body fields as JSON, e.g. {"Cnt": 10}; off by default so an unknown field can't fail the call.
EXTRA = json.loads(os.getenv("YUANBAO_EXTRA", "{}") or "{}")
TIMEOUT = float(os.getenv("YUANBAO_TIMEOUT", "20"))


@dataclass
class Page:
    title: str
    url: str
    site: str = ""
    date: str = ""
    passage: str = ""
    favicon: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SearchError(RuntimeError):
    pass


_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=TIMEOUT)
    return _client


def _key() -> str:
    key = os.getenv("YUANBAO_API_KEY") or os.getenv("TENCENTCLOUD_WSA_APIKEY") or ""
    if not key:
        raise SearchError("YUANBAO_API_KEY is not set")
    return key


def configured() -> bool:
    return bool(os.getenv("YUANBAO_API_KEY") or os.getenv("TENCENTCLOUD_WSA_APIKEY"))


def _parse_page(raw: Any) -> Page | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict) or not raw.get("url"):
        return None
    try:
        score = float(raw.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    return Page(
        title=str(raw.get("title") or raw["url"]),
        url=str(raw["url"]),
        site=str(raw.get("site") or ""),
        date=str(raw.get("date") or ""),
        passage=str(raw.get("passage") or raw.get("content") or ""),
        favicon=str(raw.get("favicon") or ""),
        score=score,
    )


async def search(query: str) -> list[Page]:
    resp = await _http().post(
        URL,
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json; charset=utf-8"},
        json={"Query": query, **EXTRA},
    )
    try:
        data = resp.json()
    except ValueError as exc:
        raise SearchError(f"元宝搜索 HTTP {resp.status_code}: {resp.text[:200]}") from exc
    body = data.get("Response", data)
    if body.get("Error"):
        err = body["Error"]
        raise SearchError(f"元宝搜索 {err.get('Code')}: {err.get('Message', '')}")
    if resp.status_code != 200:
        raise SearchError(f"元宝搜索 HTTP {resp.status_code}: {resp.text[:200]}")
    pages = [p for p in (_parse_page(r) for r in body.get("Pages") or []) if p]
    logger.info("yuanbao %r -> %d pages", query, len(pages))
    return pages
