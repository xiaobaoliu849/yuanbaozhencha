"""SQLite storage for reports (shareable links) and watches (盯梢)."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIRM_CONFIDENCE = 60
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
_db = sqlite3.connect(DATA_DIR / "chade.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
_lock = threading.Lock()
_db.executescript("""
CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, created_at TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS watches (
    id TEXT PRIMARY KEY, owner TEXT, report_id TEXT, claim TEXT, queries TEXT,
    created_at TEXT, last_checked TEXT, verdict TEXT, changed INTEGER DEFAULT 0,
    push_token TEXT DEFAULT '', active INTEGER DEFAULT 1, history TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS watches_owner ON watches(owner);
""")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_report(report: dict[str, Any]) -> str:
    rid = secrets.token_urlsafe(6)
    report["id"] = rid
    with _lock:
        _db.execute("INSERT INTO reports VALUES (?, ?, ?)", (rid, now(), json.dumps(report, ensure_ascii=False)))
        _db.commit()
    return rid


def get_report(rid: str) -> dict[str, Any] | None:
    row = _db.execute("SELECT body FROM reports WHERE id = ?", (rid,)).fetchone()
    return json.loads(row["body"]) if row else None


def recent_reports(limit: int = 8) -> list[dict[str, Any]]:
    """Latest reports that actually checked something, trimmed to what a list card shows."""
    out = []
    for row in _db.execute("SELECT body FROM reports ORDER BY created_at DESC LIMIT ?", (limit * 4,)):
        r = json.loads(row["body"])
        if r.get("off_limits") or not r.get("claims"):
            continue
        out.append({"id": r["id"], "headline": r.get("headline") or r.get("title", ""), "verdict": r["verdict"],
                    "verdict_label": r.get("verdict_label", ""), "created_at": r["created_at"],
                    "claims": len(r["claims"]), "sources": len(r.get("sources", []))})
        if len(out) >= limit:
            break
    return out


def _watch(row: sqlite3.Row) -> dict[str, Any]:
    w = dict(row)
    w["queries"] = json.loads(w["queries"] or "[]")
    w["history"] = json.loads(w["history"] or "[]")
    w["changed"] = bool(w["changed"])
    w["active"] = bool(w["active"])
    w["has_push"] = bool(w.pop("push_token"))
    return w


def add_watch(owner: str, report_id: str, claim: dict[str, Any], sources: list[dict[str, Any]],
              push_token: str = "") -> dict[str, Any]:
    wid = secrets.token_urlsafe(6)
    first = {"at": claim.get("checked_at") or now(), "verdict": claim["verdict"],
             "confidence": claim.get("confidence", 0), "explanation": claim.get("explanation", ""),
             "sources": _top_sources(claim, sources)}
    with _lock:
        _db.execute(
            "INSERT INTO watches (id, owner, report_id, claim, queries, created_at, last_checked, verdict, push_token,"
            " history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (wid, owner, report_id, claim["claim"], json.dumps(claim.get("searched", [])[:3], ensure_ascii=False),
             now(), first["at"], claim["verdict"], push_token.strip(), json.dumps([first], ensure_ascii=False)),
        )
        _db.commit()
    return get_watch(wid)  # type: ignore[return-value]


def _top_sources(claim: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """The URLs a verdict rests on, kept small so a watch's history stays light."""
    if sources is None:
        return []
    by_id = {s["id"]: s for s in sources}
    out = []
    for e in claim.get("evidence", []):
        s = by_id.get(e["source"])
        if s and s["url"] not in {o["url"] for o in out}:
            out.append({"title": s["title"], "url": s["url"], "site": s.get("site", ""), "date": s.get("date", "")})
    return out[:4]


def get_watch(wid: str) -> dict[str, Any] | None:
    row = _db.execute("SELECT * FROM watches WHERE id = ?", (wid,)).fetchone()
    return _watch(row) if row else None


def push_token(wid: str) -> str:
    row = _db.execute("SELECT push_token FROM watches WHERE id = ?", (wid,)).fetchone()
    return row["push_token"] if row else ""


def list_watches(owner: str) -> list[dict[str, Any]]:
    rows = _db.execute("SELECT * FROM watches WHERE owner = ? AND active = 1 ORDER BY created_at DESC", (owner,))
    return [_watch(r) for r in rows]


def due_watches(before: str) -> list[dict[str, Any]]:
    rows = _db.execute("SELECT * FROM watches WHERE active = 1 AND last_checked < ?", (before,))
    return [_watch(r) for r in rows]


def record_check(wid: str, result: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    w = get_watch(wid)
    if w is None:
        raise KeyError(wid)
    entry = {"at": now(), "verdict": result["verdict"], "confidence": result["confidence"],
             "explanation": result["explanation"], "sources": _top_sources(result, sources)}
    # The model wobbles between runs, so a new verdict only counts once it is confident or comes out
    # the same twice in a row; until then the watch keeps its old verdict and the check sits in history.
    # 「查不到」 never counts: it is what an outage or a spent search quota looks like, not news.
    last = w["history"][-1]["verdict"] if w["history"] else None
    changed = (result["verdict"] not in (w["verdict"], "unknown")
               and (result["confidence"] >= CONFIRM_CONFIDENCE or result["verdict"] == last))
    verdict = result["verdict"] if changed else w["verdict"]
    history = (w["history"] + [entry])[-30:]
    with _lock:
        _db.execute(
            "UPDATE watches SET last_checked = ?, verdict = ?, changed = ?, history = ? WHERE id = ?",
            (entry["at"], verdict, 1 if changed or w["changed"] else 0,
             json.dumps(history, ensure_ascii=False), wid),
        )
        _db.commit()
    out = get_watch(wid)
    out["just_changed"] = changed  # type: ignore[index]
    out["previous_verdict"] = w["verdict"]  # type: ignore[index]
    return out  # type: ignore[return-value]


def ack_watch(wid: str, owner: str) -> None:
    with _lock:
        _db.execute("UPDATE watches SET changed = 0 WHERE id = ? AND owner = ?", (wid, owner))
        _db.commit()


def stop_watch(wid: str, owner: str) -> None:
    with _lock:
        _db.execute("UPDATE watches SET active = 0 WHERE id = ? AND owner = ?", (wid, owner))
        _db.commit()
