"""Change alerts for 盯梢: PushPlus (微信推送) per watch, plus an optional owner webhook."""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)
PUSHPLUS = "https://www.pushplus.plus/send"


async def changed(watch: dict[str, Any], token: str, link: str) -> None:
    labels = {"true": "属实", "false": "不实", "mixed": "部分属实", "unknown": "查不到"}
    title = f"盯梢提醒：结论从「{labels.get(watch['previous_verdict'], '?')}」变成「{labels.get(watch['verdict'], '?')}」"
    last = watch["history"][-1] if watch["history"] else {}
    body = f"<p><b>{watch['claim']}</b></p><p>{last.get('explanation', '')}</p><p><a href=\"{link}\">查看证据</a></p>"
    async with httpx.AsyncClient(timeout=10) as http:
        if token:
            try:
                await http.post(PUSHPLUS, json={"token": token, "title": title, "content": body, "template": "html"})
            except httpx.HTTPError as exc:
                logger.warning("pushplus failed: %s", exc)
        hook = os.getenv("ALERT_WEBHOOK_URL")
        if hook:
            try:
                await http.post(hook, json={"title": title, "claim": watch["claim"], "link": link,
                                            "verdict": watch["verdict"], "previous": watch["previous_verdict"]})
            except httpx.HTTPError as exc:
                logger.warning("webhook failed: %s", exc)
