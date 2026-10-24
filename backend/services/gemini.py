"""Thin async wrapper over the Gemini REST API: JSON answers, optionally reading an image."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash")

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=90.0)
    return _client


def _key() -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return key


async def generate_json(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg",
                        thinking: str = "low") -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    if image_b64:
        parts.append({"inlineData": {"mimeType": mime, "data": image_b64}})
    parts.append({"text": prompt})
    resp = await _http().post(
        f"{BASE}/{TEXT_MODEL}:generateContent",
        headers={"x-goog-api-key": _key(), "Content-Type": "application/json"},
        json={
            "contents": [{"parts": parts}],
            # Judging evidence wants a little thinking; low keeps a call to a few seconds.
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
                "thinkingConfig": {"thinkingLevel": thinking},
            },
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini {TEXT_MODEL} {resp.status_code}: {resp.text[:300]}")
    try:
        parts_out = resp.json()["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError("Gemini returned no content") from exc
    text = "".join(p.get("text", "") for p in parts_out if not p.get("thought"))
    return json.loads(text)
