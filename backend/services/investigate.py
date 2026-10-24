"""The investigation: read the rumor, split it into checkable claims, search in rounds, judge on evidence.

Every verdict must point at sources that 元宝搜索 actually returned. Citations of unknown sources
are dropped, quotes are checked against the source text, and a claim left with no evidence is
forced to 「查不到」 — the model is never allowed to answer from its own memory.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from . import credibility, llm, yuanbao

logger = logging.getLogger(__name__)

MAX_CLAIMS = 3
MAX_ROUNDS = 3
PAGES_PER_QUERY = 6
PASSAGE_CHARS = 700
VERDICTS = {"true": "属实", "false": "不实", "mixed": "部分属实", "unknown": "查不到"}

Emit = Callable[[dict[str, Any]], Awaitable[None]]

PLAN = """你是「查得到，信得过」的调查员，专门帮普通人查证家族群、朋友圈里的传言。
今天是 {today}。

用户给你的内容：
<<<
{text}
>>>
{image_note}

请完成：
1. 如果有截图，把截图里的文字和要查证的说法原样读出来，写进 readable_text；没有截图就复述用户的文字。
2. 判断是否属于不能查的范围：时政（政党、领导人、国家政策争议、选举、战争立场）或针对某个普通个人的消息（隐私、八卦、人肉）。是的话 off_limits=true 并说明原因，claims 留空。
3. 把内容拆成最多 {max_claims} 条可以独立查证的具体说法（事实性的，有明确对错的）。空泛的情绪话、祝福、广告不算。
4. 每条说法给 2 个搜索词，适合在中文搜索引擎里搜：一个直接搜说法本身，一个搜权威来源的说法（如 "辟谣"、"官方"、"研究"、机构名）。

只输出 JSON：
{{"title": "10字以内的标题", "readable_text": "...", "off_limits": false, "off_limits_reason": "",
  "claims": [{{"claim": "具体说法", "queries": ["搜索词1", "搜索词2"]}}]}}"""

JUDGE = """你是严谨的事实核查员。今天是 {today}。只能依据下面搜索到的来源判断，绝不能用你自己的记忆补充事实。

要查证的说法：{claim}

已经搜索过的词：{queries}

来源（编号 / 网站（类型）/ 日期 / 标题 / 摘录）：
{sources}

判断规则：
- true=属实，false=不实，mixed=部分属实或要看条件，unknown=来源不足以判断。
- 每个判断必须引用来源编号，并从该来源的摘录里原样摘一句话作为 quote（必须是摘录里出现过的原文）。
- 优先相信官方机构、权威媒体、专业机构的来源；自媒体、营销号的说法要打折扣。来源之间互相矛盾时写进 conflicts。
- 证据不够、来源都不权威、或者只是有人这么说但没有证实，就判 unknown。宁可说不知道，也不要猜。
- 如果再搜一轮可能查清楚（第 {round} 轮，最多 {max_rounds} 轮），need_more=true，并给 1-2 个新的搜索词（换个角度，不要重复已经搜过的）。

只输出 JSON：
{{"verdict": "true|false|mixed|unknown", "confidence": 0到100的整数,
  "explanation": "两三句话，用长辈能看懂的大白话解释结论和依据",
  "evidence": [{{"source": "S1", "quote": "原文摘句", "stance": "support|refute|context"}}],
  "conflicts": "来源之间的矛盾，没有就留空",
  "need_more": false, "next_queries": []}}"""

SUMMARY = """你在帮用户把查证结果转发回家族群。今天是 {today}。
原始传言：{text}
逐条结论：
{results}

写：
- headline：一句话说清真相（20字以内），不要以「不实」「属实」这类结论词开头（页面上已经有结论印章），比如「隔夜茶本身不会致癌」。
- family_message：一段可以直接发到家族群的话，80字以内，语气亲切尊重，不嘲讽长辈，说清楚结论，提醒看下面的来源链接。
只输出 JSON：{{"headline": "...", "family_message": "..."}}"""


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y年%m月%d日")


def _norm(s: str) -> str:
    return re.sub(r"[\s　，。、,.!！?？:：;；\"'“”‘’()（）\[\]【】…—-]+", "", s or "").lower()


class SourcePool:
    """All pages one investigation has seen, numbered S1, S2… and deduped by URL."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict[str, Any]] = {}
        self._by_url: dict[str, str] = {}

    def add(self, page: yuanbao.Page, query: str) -> str:
        if page.url in self._by_url:
            sid = self._by_url[page.url]
            src = self.by_id[sid]
            if query not in src["queries"]:
                src["queries"].append(query)
            if len(page.passage) > len(src["passage"]):
                src["passage"] = page.passage
            return sid
        sid = f"S{len(self.by_id) + 1}"
        self._by_url[page.url] = sid
        t = credibility.tier(page.url, page.site)
        self.by_id[sid] = {"id": sid, **page.to_dict(), "queries": [query],
                           "tier": t, "tier_label": credibility.TIERS[t]}
        return sid


async def _search(query: str, pool: SourcePool) -> tuple[list[str], str | None]:
    try:
        pages = await yuanbao.search(query)
    except Exception as exc:  # noqa: BLE001 — a failed query is reported, not fatal
        logger.warning("search %r failed: %s", query, exc)
        return [], str(exc)
    return [pool.add(p, query) for p in pages[:PAGES_PER_QUERY]], None


def _card(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s[k] for k in ("id", "title", "url", "site", "date", "tier", "tier_label")}


def _format_sources(ids: list[str], pool: SourcePool) -> str:
    lines = []
    for sid in ids:
        s = pool.by_id[sid]
        passage = re.sub(r"\s+", " ", s["passage"])[:PASSAGE_CHARS]
        lines.append(f"[{sid}] {s['site'] or '-'}（{s['tier_label']}）/ {s['date'] or '日期不详'} / {s['title']}\n    {passage}")
    return "\n".join(lines) or "（没有搜到任何来源）"


def _check(judged: dict[str, Any], seen: list[str], pool: SourcePool) -> dict[str, Any]:
    """Keep only evidence that cites a source this claim actually saw, and check each quote."""
    evidence = []
    for ev in judged.get("evidence") or []:
        sid = str(ev.get("source", "")).strip().upper()
        if sid not in seen:
            continue
        quote = str(ev.get("quote", "")).strip()
        evidence.append({
            "source": sid,
            "quote": quote,
            "stance": ev.get("stance") if ev.get("stance") in ("support", "refute", "context") else "context",
            # True when the quote really appears in the page text 元宝搜索 returned.
            "quote_found": bool(quote) and _norm(quote) in _norm(pool.by_id[sid]["passage"]),
        })
    verdict = judged.get("verdict") if judged.get("verdict") in VERDICTS else "unknown"
    try:
        confidence = max(0, min(100, int(judged.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0
    explanation = str(judged.get("explanation", ""))
    guard = ""
    if verdict != "unknown" and not any(e["quote_found"] for e in evidence):
        guard = f"AI 本来想判「{VERDICTS[verdict]}」，但它引用的原文在搜到的网页里核对不上，按规则改判为「查不到」。"
        verdict, confidence = "unknown", min(confidence, 30)
        explanation = "搜到的来源不足以确认这条说法，先不下结论。"
    return {
        "verdict": verdict,
        "verdict_label": VERDICTS[verdict],
        "confidence": confidence,
        "explanation": explanation,
        "conflicts": str(judged.get("conflicts", "") or ""),
        "evidence": evidence,
        "guard": guard,
        "need_more": bool(judged.get("need_more")),
        "next_queries": [str(q) for q in (judged.get("next_queries") or []) if str(q).strip()][:2],
    }


async def check_claim(index: int, claim: str, queries: list[str], pool: SourcePool, emit: Emit) -> dict[str, Any]:
    """Search → judge, up to MAX_ROUNDS rounds, and return the claim's result with its evidence chain."""
    seen: list[str] = []
    asked: list[str] = []
    chain: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    todo = [q for q in queries if q.strip()][:2] or [claim]
    for rnd in range(1, MAX_ROUNDS + 1):
        todo = [q for q in todo if q not in asked]
        if not todo:
            break
        asked += todo
        await emit({"type": "searching", "claim": index, "round": rnd, "queries": todo,
                    "why": "" if rnd == 1 else chain[-1]["next_reason"]})
        searches = []
        for q, (ids, err) in zip(todo, await asyncio.gather(*(_search(q, pool) for q in todo))):
            new = [i for i in ids if i not in seen]
            seen += new
            searches.append({"query": q, "found": len(ids), "new": len(new), "sources": ids, "error": err})
            await emit({"type": "search", "claim": index, "round": rnd, "query": q,
                        "found": len(ids), "new": len(new), "error": err,
                        "sources": [_card(pool.by_id[i]) for i in new]})
        await emit({"type": "judging", "claim": index, "round": rnd, "sources": len(seen)})
        try:
            judged = await llm.generate_json(JUDGE.format(
                today=_today(), claim=claim, queries="、".join(asked), sources=_format_sources(seen, pool),
                round=rnd, max_rounds=MAX_ROUNDS,
            ))
        except Exception as exc:  # noqa: BLE001 — one claim failing must not sink the report
            logger.warning("judge failed for %r: %s", claim, exc)
            judged = {"verdict": "unknown", "explanation": "这一条在分析证据时出错了，暂时给不出结论。"}
        result = _check(judged, seen, pool)
        settled = result["verdict"] != "unknown" and result["confidence"] >= 75
        more = not settled and result["need_more"] and rnd < MAX_ROUNDS and bool(result["next_queries"])
        step = {"round": rnd, "searches": searches, "sources": len(seen), "verdict": result["verdict"],
                "confidence": result["confidence"], "note": result["explanation"],
                "evidence": len(result["evidence"]),
                "verified": sum(1 for e in result["evidence"] if e["quote_found"]),
                "guard": bool(result["guard"]),
                "next_reason": "证据还不够，换个角度再搜一轮" if more else ""}
        chain.append(step)
        await emit({"type": "round", "claim": index, **{k: v for k, v in step.items() if k != "searches"},
                    "next_queries": result["next_queries"] if more else []})
        if not more:
            break
        todo = result["next_queries"]
    out = {
        "index": index,
        "claim": claim,
        **{k: v for k, v in result.items() if k not in ("need_more", "next_queries")},
        "chain": chain,
        "searched": asked,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    await emit({"type": "claim", "claim": index, "result": out})
    return out


async def plan(text: str, image_b64: str | None, mime: str) -> dict[str, Any]:
    note = "用户还附了一张截图（见图片），里面的说法也要查。" if image_b64 else ""
    data = await llm.generate_json(
        PLAN.format(today=_today(), text=text.strip() or "（只有截图）", image_note=note, max_claims=MAX_CLAIMS),
        image_b64=image_b64, mime=mime,
    )
    claims = []
    for c in (data.get("claims") or [])[:MAX_CLAIMS]:
        claim = str(c.get("claim", "")).strip()
        if claim:
            claims.append({"claim": claim, "queries": [str(q) for q in (c.get("queries") or [])][:2]})
    return {
        "title": str(data.get("title") or "查证报告"),
        "readable_text": str(data.get("readable_text") or text),
        "off_limits": bool(data.get("off_limits")),
        "off_limits_reason": str(data.get("off_limits_reason") or ""),
        "claims": claims,
    }


def overall(results: list[dict[str, Any]]) -> str:
    verdicts = {r["verdict"] for r in results}
    if not verdicts or verdicts == {"unknown"}:
        return "unknown"
    if len(verdicts - {"unknown"}) == 1 and "unknown" not in verdicts:
        return verdicts.pop()
    if verdicts <= {"false", "unknown"}:
        return "false"
    if verdicts <= {"true", "unknown"}:
        return "true"
    return "mixed"


async def run(text: str, image_b64: str | None, mime: str, emit: Emit) -> dict[str, Any]:
    await emit({"type": "step", "stage": "plan", "text": "AI 正在阅读内容，拆解成可以查证的说法…"})
    p = await plan(text, image_b64, mime)
    await emit({"type": "plan", **p})
    report: dict[str, Any] = {
        "title": p["title"], "input_text": text, "readable_text": p["readable_text"],
        "had_image": bool(image_b64), "created_at": datetime.now(timezone.utc).isoformat(),
        "claims": [], "sources": [], "headline": "", "family_message": "", "verdict": "unknown",
        "off_limits": p["off_limits"], "off_limits_reason": p["off_limits_reason"],
    }
    if p["off_limits"] or not p["claims"]:
        report["headline"] = ("这类内容不在查证范围内" if p["off_limits"] else "没找到可以查证的具体说法")
        report["verdict_label"] = VERDICTS["unknown"]
        return report

    pool = SourcePool()
    await emit({"type": "step", "stage": "search", "text": f"拆出 {len(p['claims'])} 条说法，开始用元宝搜索多轮查证…"})
    results = await asyncio.gather(*(
        check_claim(i, c["claim"], c["queries"], pool, emit) for i, c in enumerate(p["claims"])
    ))
    report["claims"] = list(results)
    cited = {e["source"] for r in results for e in r["evidence"]}
    report["sources"] = [{**s, "cited": s["id"] in cited} for s in pool.by_id.values()]
    report["verdict"] = overall(report["claims"])
    report["verdict_label"] = VERDICTS[report["verdict"]]

    await emit({"type": "step", "stage": "summary", "text": "所有说法查完了，正在整理证据链、写给家人的话…"})
    lines = "\n".join(f"{i + 1}. {r['claim']} → {r['verdict_label']}：{r['explanation']}" for i, r in enumerate(results))
    try:
        s = await llm.generate_json(SUMMARY.format(today=_today(), text=p["readable_text"], results=lines),
                                       thinking="minimal")
        report["headline"] = str(s.get("headline", ""))
        report["family_message"] = str(s.get("family_message", ""))
    except Exception as exc:  # noqa: BLE001 — the report stands without the summary
        logger.warning("summary failed: %r", exc)
        report["headline"] = f"{report['verdict_label']}：{p['title']}"
    return report


async def recheck(claim: str, queries: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Re-run one claim from scratch (for 盯梢). Returns the result and the sources it saw."""
    pool = SourcePool()

    async def _quiet(_: dict[str, Any]) -> None:
        return None

    result = await check_claim(0, claim, queries, pool, _quiet)
    cited = {e["source"] for e in result["evidence"]}
    return result, [{**s, "cited": s["id"] in cited} for s in pool.by_id.values()]
