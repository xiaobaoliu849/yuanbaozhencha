"""查得到，信得过 — FastAPI backend.

Holds the 元宝搜索 and Gemini keys, runs investigations (streamed as NDJSON), stores reports and
盯梢 watches in SQLite, rechecks watches daily, and serves the built frontend from ../frontend/dist.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


def _load_dotenv() -> None:
    """Read KEY=VALUE lines from the repo's .env so local runs need no exported variables."""
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_dotenv()

from .services import investigate, llm, notify, store, yuanbao  # noqa: E402 — keys must be loaded first

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chade")

WATCH_HOURS = float(os.getenv("WATCH_INTERVAL_HOURS", "24"))
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "40"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
CRON_TOKEN = os.getenv("CRON_TOKEN", "")
MAX_IMAGE_B64 = 8 * 1024 * 1024


async def _watch_loop() -> None:
    """Recheck due watches once an hour while the server is up. External cron can hit /api/cron too."""
    while True:
        try:
            await run_due()
        except Exception:  # noqa: BLE001
            logger.exception("watch loop failed")
        await asyncio.sleep(3600)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_watch_loop())
    yield
    task.cancel()


app = FastAPI(title="查得到，信得过", lifespan=lifespan)
_usage: dict[tuple[str, date], int] = defaultdict(int)


def _client_ip(request: Request) -> str:
    # Never read X-Forwarded-For here: clients can write anything in it. uvicorn's --proxy-headers
    # fills request.client from it only when the request came through a trusted proxy (our nginx, or
    # the platform proxy listed in the Dockerfile's FORWARDED_ALLOW_IPS).
    return request.client.host if request.client else "?"


def _charge(request: Request) -> None:
    """Count one search-heavy call (investigation or recheck) against the caller's daily limit."""
    today = date.today()
    for old in [k for k in _usage if k[1] != today]:
        del _usage[old]
    key = (_client_ip(request), today)
    if _usage[key] >= DAILY_LIMIT:
        raise HTTPException(429, "今天查得太多啦，明天再来吧")
    _usage[key] += 1


def _link(path: str, request: Request | None = None) -> str:
    base = PUBLIC_URL or (str(request.base_url).rstrip("/") if request else "")
    return f"{base}{path}"


# ---------------------------------------------------------------------------
# investigation
# ---------------------------------------------------------------------------

class InvestigateIn(BaseModel):
    text: str = ""
    image_b64: str | None = None
    image_mime: str = "image/jpeg"


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "yuanbao": yuanbao.configured(), "llm": llm.provider(), "images": llm.can_read_images()}


@app.get("/api/models")
async def models() -> dict[str, Any]:
    """Which models the OpenAI-compatible endpoint offers, to pick LLM_MODEL / LLM_VISION_MODEL."""
    try:
        return {"models": await llm.list_models()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/investigate")
async def investigate_ep(body: InvestigateIn, request: Request) -> StreamingResponse:
    text = body.text.strip()[:2000]
    if not text and not body.image_b64:
        raise HTTPException(400, "请输入要查的内容，或上传一张截图")
    if body.image_b64 and not llm.can_read_images():
        raise HTTPException(400, "当前没有配置能看图的模型，请把截图里的文字粘贴进来")
    if body.image_b64 and len(body.image_b64) > MAX_IMAGE_B64:
        raise HTTPException(413, "截图太大了，请压缩到 6MB 以内")
    _charge(request)

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def work() -> None:
        try:
            report = await investigate.run(text, body.image_b64, body.image_mime, emit)
            report["id"] = store.save_report(report)
            await emit({"type": "done", "report": report})
        except Exception as exc:  # noqa: BLE001
            logger.exception("investigation failed")
            await emit({"type": "error", "message": f"调查中断了：{exc}"})
        finally:
            await queue.put(None)

    async def stream() -> AsyncIterator[bytes]:
        task = asyncio.create_task(work())
        try:
            while (event := await queue.get()) is not None:
                yield (json.dumps(event, ensure_ascii=False) + "\n").encode()
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/reports/recent")
async def recent_reports() -> list[dict[str, Any]]:
    return store.recent_reports()


@app.get("/api/reports/{rid}")
async def get_report(rid: str) -> dict[str, Any]:
    report = store.get_report(rid)
    if report is None:
        raise HTTPException(404, "报告不存在")
    return report


# ---------------------------------------------------------------------------
# 盯梢 watches
# ---------------------------------------------------------------------------

class WatchIn(BaseModel):
    owner: str
    report_id: str
    claim_index: int
    push_token: str = ""


class OwnerIn(BaseModel):
    owner: str


def _owned(wid: str, owner: str) -> dict[str, Any]:
    w = store.get_watch(wid)
    if w is None or w["owner"] != owner:
        raise HTTPException(404, "没有这条盯梢")
    return w


@app.post("/api/watches")
async def add_watch(body: WatchIn) -> dict[str, Any]:
    report = store.get_report(body.report_id)
    if report is None or not 0 <= body.claim_index < len(report["claims"]):
        raise HTTPException(404, "报告或说法不存在")
    if len(body.owner) < 8:
        raise HTTPException(400, "bad owner")
    # Reports from before the flag existed have no "changes" key; only an explicit False is refused.
    if report["claims"][body.claim_index].get("changes") is False:
        raise HTTPException(400, "这条说法的结论不会随时间变化，不需要盯梢")
    return store.add_watch(body.owner, body.report_id, report["claims"][body.claim_index], report["sources"],
                           body.push_token)


@app.get("/api/watches")
async def list_watches(owner: str) -> list[dict[str, Any]]:
    return store.list_watches(owner)


async def _recheck(w: dict[str, Any]) -> dict[str, Any]:
    result, sources = await investigate.recheck(w["claim"], w["queries"])
    updated = store.record_check(w["id"], result, sources)
    if updated["just_changed"]:
        await notify.changed(updated, store.push_token(w["id"]), _link(f"/r/{w['report_id']}"))
    return updated


@app.post("/api/watches/{wid}/recheck")
async def recheck_watch(wid: str, body: OwnerIn, request: Request) -> dict[str, Any]:
    w = _owned(wid, body.owner)
    _charge(request)
    return await _recheck(w)


@app.post("/api/watches/{wid}/ack")
async def ack_watch(wid: str, body: OwnerIn) -> dict[str, bool]:
    _owned(wid, body.owner)
    store.ack_watch(wid, body.owner)
    return {"ok": True}


@app.post("/api/watches/{wid}/stop")
async def stop_watch(wid: str, body: OwnerIn) -> dict[str, bool]:
    _owned(wid, body.owner)
    store.stop_watch(wid, body.owner)
    return {"ok": True}


async def run_due() -> int:
    before = (datetime.now(timezone.utc) - timedelta(hours=WATCH_HOURS)).isoformat()
    due = store.due_watches(before)
    for w in due:
        try:
            await _recheck(w)
        except Exception:  # noqa: BLE001
            logger.exception("recheck %s failed", w["id"])
    if due:
        logger.info("rechecked %d watches", len(due))
    return len(due)


@app.post("/api/cron")
async def cron(token: str = "") -> dict[str, int]:
    if not CRON_TOKEN or token != CRON_TOKEN:
        raise HTTPException(403, "bad token")
    return {"rechecked": await run_due()}


# ---------------------------------------------------------------------------
# frontend
# ---------------------------------------------------------------------------

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str) -> FileResponse:
        target = DIST / path
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
